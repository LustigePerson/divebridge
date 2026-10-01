"""Web UI: upload exports -> review -> UDDF download / SSI upload. Designed for Home Assistant ingress."""

from __future__ import annotations

import io
import json
import logging
import secrets
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..exporters.ssi import PushResult, push_dives
from ..exporters.uddf import dives_to_uddf, uddf_filename
from ..importers import ImportError_, detect, parse_file
from ..importers.registry import expand_archive, is_zip_archive
from ..model import Dive
from ..settings import Settings
from ..ssi.client import SsiClient
from ..ssi.dedup import find_existing
from ..ssi.payload import DiveOptions
from ..ssi.vars import GROUPS, MULTI_GROUPS, VarIndex
from ..ssi.sites import SiteIndex, SiteMatch

log = logging.getLogger(__name__)
HA_INGRESS_IP = "172.30.32.2"
MAX_BATCHES = 20  # older uploads (and their files under data_dir/uploads) are dropped


@dataclass
class Batch:
    id: str
    created: datetime
    files: list[str]
    dives: list[Dive]
    errors: list[str] = field(default_factory=list)
    site_suggestions: dict[int, SiteMatch | None] = field(default_factory=dict)
    existing: dict[int, dict[str, Any] | None] = field(default_factory=dict)
    results: list[PushResult] | None = None


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.batches: dict[str, Batch] = {}
        self.email = settings.ssi_email
        self.password = settings.ssi_password
        self._client: SsiClient | None = None
        self._sites: SiteIndex | None = None
        self._vars: VarIndex | None = None
        self.logbook: dict[str, Any] | None = None
        self.last_error: str | None = None
        settings.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def ssi_configured(self) -> bool:
        return bool(self.email and self.password)

    def client(self) -> SsiClient:
        if self._client is None:
            self._client = SsiClient(self.email, self.password, data_dir=self.settings.data_dir)
        return self._client

    def reset_client(self) -> None:
        if self._client:
            self._client.close()
        self._client = None
        self.logbook = None

    def vars(self) -> VarIndex:
        if self._vars is None or (self._vars.client is None and self.ssi_configured):
            self._vars = VarIndex(self.settings.data_dir, self.client() if self.ssi_configured else None)
        return self._vars

    def remember(self, batch: Batch) -> None:
        """Keep the newest MAX_BATCHES uploads; delete the files of the rest."""
        self.batches[batch.id] = batch
        if len(self.batches) <= MAX_BATCHES:
            return
        for old in sorted(self.batches.values(), key=lambda b: b.created)[: len(self.batches) - MAX_BATCHES]:
            self.batches.pop(old.id, None)
            shutil.rmtree(self.settings.data_dir / "uploads" / old.id, ignore_errors=True)

    def sites(self) -> SiteIndex:
        if self._sites is None:
            self._sites = SiteIndex(self.settings.data_dir, self.client())
        return self._sites

    def buddies(self) -> list[tuple[int, str]]:
        """(id, name) of the buddies known in the SSI logbook."""
        lb = self.logbook or {}
        out = []
        for b in lb.get("logbook_buddies", []):
            if b.get("deleted") in (1, True):
                continue
            name = " ".join(x for x in (b.get("firstname"), b.get("lastname")) if x) or b.get("nickname") or str(b.get("id"))
            out.append((int(b["id"]), name))
        return sorted(out, key=lambda x: x[1].lower())

    def refresh_logbook(self) -> dict[str, Any] | None:
        if not self.ssi_configured:
            return None
        try:
            self.logbook = self.client().get_divelog()
            self.last_error = None
        except Exception as e:  # noqa: BLE001
            self.last_error = f"SSI: {e}"
            log.warning("SSI logbook unavailable: %s", e)
        return self.logbook


settings = Settings.from_env()
state = AppState(settings)
app = FastAPI(title="divebridge", version=__version__)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _root(request: Request) -> str:
    """URL prefix under Home Assistant ingress (header set by the Supervisor proxy)."""
    return request.headers.get("X-Ingress-Path", "").rstrip("/")


def render(request: Request, name: str, **ctx: Any) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {
        "root": _root(request), "state": state, "version": __version__,
        "var_groups": GROUPS, "multi_groups": MULTI_GROUPS, "var_options": state.vars().options, **ctx})


def _num(v: Any) -> float | None:
    s = str(v or "").strip().replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _id(v: Any) -> int | None:
    s = str(v or "").strip()
    return int(s) if s.isdigit() else None


def _options_from_form(form: Any, suffix: str = "") -> DiveOptions:
    """Read the optional SSI fields (batch defaults: suffix "", per dive: suffix "_<i>")."""
    g = lambda k: form.get(f"o_{k}{suffix}")  # noqa: E731
    rating = _num(g("rating"))
    return DiveOptions(
        divetype_id=_id(g("divetype")),
        watertype_id=_id(g("watertype")),
        tanktype_id=_id(g("tanktype")),
        entry_id=_id(g("entry")),
        water_body_id=_id(g("water_body")),
        weather_id=_id(g("weather")),
        surface_id=_id(g("surface")),
        current_id=_id(g("current")),
        specialdive_ids=[int(x) for x in form.getlist(f"o_specialdive{suffix}") if str(x).isdigit()],
        tank_volume_l=_num(g("tank_volume_l")),
        start_bar=_num(g("start_bar")),
        end_bar=_num(g("end_bar")),
        weight_kg=_num(g("weight_kg")),
        visibility_m=_num(g("visibility_m")),
        air_temp_c=_num(g("air_temp_c")),
        buddy_ids=[int(b) for b in form.getlist(f"o_buddy{suffix}") if str(b).isdigit()],
        notes=str(g("notes") or "").strip() or None,
        rating=int(rating) if rating else None,
        mark_imported=(form.get("mark_imported") != "0") if not suffix else None,
    )


@app.middleware("http")
async def ingress_guard(request: Request, call_next):
    if settings.ingress_only and request.client and request.client.host != HA_INGRESS_IP:
        log.warning("rejected request from %s (ingress-only mode; expected %s)", request.client.host, HA_INGRESS_IP)
        return Response("forbidden (ingress only)", status_code=403)
    response = await call_next(request)
    # one line per request so the add-on log shows what the browser/app actually sends
    log.info("%s %s -> %s (ua: %s)", request.method, request.url.path, response.status_code,
             request.headers.get("user-agent", "-")[:120])
    return response


@app.get("/diag", response_class=HTMLResponse)
def diag(request: Request, echo: str = ""):
    """Diagnostics for file picking in WebViews (companion app): what reaches the page / the server."""
    return render(request, "diag.html", ua=request.headers.get("user-agent", "-"),
                  companion=is_companion_app(request), client=request.client.host if request.client else "-", echo=echo)


@app.post("/diag/echo", response_class=HTMLResponse)
async def diag_echo(request: Request, files: list[UploadFile] = File(default=[])):
    parts = []
    for f in files:
        data = await f.read()
        parts.append(f"{f.filename!r}: {len(data)} bytes, {f.content_type}")
    msg = "server received " + (", ".join(parts) if parts else "no file part")
    log.info("diag: %s", msg)
    return render(request, "diag.html", ua=request.headers.get("user-agent", "-"),
                  companion=is_companion_app(request), client=request.client.host if request.client else "-", echo=msg)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def is_companion_app(request: Request) -> bool:
    """The HA Android app's WebView drops multi-file selections (ClipData is ignored); its UA
    contains 'Home Assistant/<version>'. With a single-file input the picker returns intent.data,
    which the app handles – so we offer one file (or a ZIP) there instead of a broken multi-select."""
    return "Home Assistant/" in request.headers.get("user-agent", "")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    batches = sorted(state.batches.values(), key=lambda b: b.created, reverse=True)
    companion = is_companion_app(request)
    log.info("index: serving %s upload form", "single-file (companion app)" if companion else "multi-file")
    return render(request, "index.html", batches=batches, companion=companion)


def _safe_next(next_: str | None) -> str:
    """Only allow relative in-app targets (e.g. "batch/abc")."""
    n = (next_ or "").strip()
    if not n or n.startswith(("/", "http:", "https:", "//")) or ".." in n:
        return ""
    return n


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("")):
    state.email, state.password = email.strip(), password
    state.reset_client()
    try:
        state.client().authenticate()
        state.last_error = None
        for b in state.batches.values():
            _enrich(b)
    except Exception as e:  # noqa: BLE001
        state.last_error = f"SSI login failed: {e}"
        state.email, state.password = settings.ssi_email, settings.ssi_password  # back to the add-on options
        state.reset_client()
    return RedirectResponse(url=f"{_root(request)}/{_safe_next(next)}", status_code=303)


@app.post("/logout")
def logout(request: Request):
    state.client().forget_token()
    state.email = settings.ssi_email
    state.password = settings.ssi_password
    state.reset_client()
    return RedirectResponse(url=f"{_root(request)}/", status_code=303)


def _ingest(batch: Batch, incoming: list[tuple[str, bytes]]) -> None:
    """Parse uploaded/collected files into the batch; ZIPs are expanded, unknown files reported."""
    upload_dir = settings.data_dir / "uploads" / batch.id
    expanded: list[tuple[str, bytes]] = []
    for name, data in incoming:
        if is_zip_archive(name, data):
            try:
                inner = expand_archive(name, data)
            except (ImportError_, zipfile.BadZipFile) as e:
                batch.errors.append(str(e))
                continue
            expanded.extend(inner)
            batch.files.append(f"{name} (zip, {len(inner)} files)")
        else:
            expanded.append((name, data))
    for name, data in expanded:
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / name).write_bytes(data)
        imp = detect(name, data)
        if imp is None:
            batch.errors.append(f"{name}: unknown format")
            continue
        try:
            dives = parse_file(name, data, imp)
        except ImportError_ as e:
            batch.errors.append(str(e))
            continue
        batch.files.append(f"{name} ({imp.name}, {len(dives)} dives)")
        batch.dives.extend(dives)
    batch.dives.sort(key=lambda d: d.start)


def _new_batch() -> Batch:
    return Batch(id=secrets.token_hex(4), created=datetime.now(), files=[], dives=[])


@app.post("/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    batch = _new_batch()
    incoming: list[tuple[str, bytes]] = []
    log.info("upload: %d file part(s) received", len(files))
    for f in files:
        data = await f.read()
        name = Path(f.filename or "upload").name
        log.info("upload: %r, %d bytes, content-type %s", name, len(data), f.content_type)
        if data:
            incoming.append((name, data))
    await run_in_threadpool(_ingest, batch, incoming)
    log.info("upload: batch %s -> %d dive(s), %d error(s): %s", batch.id, len(batch.dives), len(batch.errors), batch.errors)
    state.remember(batch)
    await run_in_threadpool(_enrich, batch)
    return RedirectResponse(url=f"{_root(request)}/batch/{batch.id}", status_code=303)


def _enrich(batch: Batch) -> None:
    """Add SSI duplicate status and site suggestions. Never fails: SSI may be offline / not logged in."""
    if not state.ssi_configured or not batch.dives:
        return
    logbook = state.refresh_logbook()
    details = logbook.get("logbook_details", []) if logbook else []
    visited = {int(s["odin_dive_sites_id"]) for s in (logbook or {}).get("logbook_sites", []) if s.get("odin_dive_sites_id")}
    for i, d in enumerate(batch.dives):
        batch.existing[i] = find_existing(d, details) if details else None
        if d.site and d.site.name and i not in batch.site_suggestions:
            try:
                hits = state.sites().search(d.site.name, limit=1, prefer=visited)
                batch.site_suggestions[i] = hits[0] if hits else None
            except Exception as e:  # noqa: BLE001
                state.last_error = f"SSI site index: {e}"
                log.warning("site lookup failed: %s", e)


@app.get("/batch/{bid}", response_class=HTMLResponse)
def batch_page(request: Request, bid: str):
    batch = state.batches.get(bid)
    if batch is None:
        return RedirectResponse(url=f"{_root(request)}/", status_code=303)
    return render(request, "batch.html", batch=batch, dive_facts=dive_facts)


@app.get("/batch/{bid}/uddf")
def batch_uddf(request: Request, bid: str):
    batch = state.batches.get(bid)
    if batch is None or not batch.dives:
        return RedirectResponse(url=f"{_root(request)}/", status_code=303)
    out_dir = settings.output_dir
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        out_dir = None
    if len(batch.dives) == 1:
        d = batch.dives[0]
        data, name, ctype = dives_to_uddf([d]), uddf_filename(d), "application/xml"
        if out_dir:
            (out_dir / name).write_bytes(data)
    else:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for d in batch.dives:
                x = dives_to_uddf([d])
                zf.writestr(uddf_filename(d), x)
                if out_dir:
                    (out_dir / uddf_filename(d)).write_bytes(x)
        data, name, ctype = buf.getvalue(), f"divebridge_{bid}.zip", "application/zip"
    return Response(data, media_type=ctype, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/batch/{bid}/ssi", response_class=HTMLResponse)
async def batch_ssi(request: Request, bid: str):
    batch = state.batches.get(bid)
    if batch is None:
        return RedirectResponse(url=f"{_root(request)}/", status_code=303)
    form = await request.form()
    dry_run = form.get("dry_run") == "1"
    selected = [int(x) for x in form.getlist("selected")]
    site_ids: dict[int, int | None] = {}
    for i in selected:
        raw = str(form.get(f"site_id_{i}", "")).strip()
        site_ids[i] = int(raw) if raw.isdigit() else None
    dives = [batch.dives[i] for i in selected]
    local_sites = {k: site_ids[i] for k, i in enumerate(selected)}
    defaults = _options_from_form(form)
    per_dive: dict[int, DiveOptions] = {}
    if form.get("same_for_all") != "1":
        per_dive = {k: _options_from_form(form, f"_{i}") for k, i in enumerate(selected)}
    try:
        results = await run_in_threadpool(
            push_dives, state.client(), dives, local_sites, dry_run=dry_run,
            skip_duplicates=form.get("allow_duplicates") != "1",
            options=defaults, per_dive_options=per_dive,
            site_bow=lambda sid: (m.bow if (m := state.sites().get(sid)) else None))
        state.last_error = None
    except Exception as e:  # noqa: BLE001
        log.exception("push failed")
        state.last_error = f"SSI: {e}"
        results = []
    batch.results = results
    if not dry_run and results:
        state.logbook = None  # force refresh next time
    return render(request, "result.html", batch=batch, results=results, dry_run=dry_run,
                  payload_json=lambda r: json.dumps(r.payload, indent=1) if r.payload else "")


def _site_json(m: SiteMatch, visited: set[int]) -> dict[str, Any]:
    return {"id": m.id, "label": m.label + (" ★" if m.id in visited else ""), "name": m.name,
            "lat": m.lat, "lon": m.lon, "bow": m.bow,
            "distance_km": round(m.distance_m / 1000, 1) if m.distance_m is not None else None}


@app.get("/api/sites")
def api_sites(q: str = "", limit: int = 15, lat: float | None = None, lon: float | None = None):
    """Name search; with lat/lon the hits carry distances, and an empty query lists sites nearby."""
    if not state.ssi_configured:
        return JSONResponse([], status_code=200)
    try:
        visited = {int(s["odin_dive_sites_id"]) for s in (state.logbook or {}).get("logbook_sites", []) if s.get("odin_dive_sites_id")}
        idx = state.sites()
        if q.strip():
            hits = idx.search(q, limit=limit, prefer=visited)
            if lat is not None and lon is not None:
                hits = idx.with_distance(hits, lat, lon)
                hits.sort(key=lambda m: (m.distance_m if m.distance_m is not None else 1e12))
        elif lat is not None and lon is not None:
            hits = idx.nearby(lat, lon, limit=limit)
        else:
            hits = []
        return [_site_json(m, visited) for m in hits]
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)


def dive_facts(d: Dive) -> list[tuple[str, Any]]:
    """Everything we know about a dive, for the ⓘ view on the review page."""
    g = d.primary_gas
    facts: list[tuple[str, Any]] = [
        ("Start (local)", d.start.strftime("%Y-%m-%d %H:%M:%S")),
        ("Duration", f"{d.duration_min:g} min ({d.duration_s} s)"),
        ("Max / avg depth", f"{d.max_depth_m:.2f} m / {d.avg_depth_m if d.avg_depth_m is not None else '—'} m"),
        ("Water temp min / max", f"{d.water_temp_min_c} / {d.water_temp_max_c} °C"),
        ("Surface interval before", f"{d.surface_interval_s} s" if d.surface_interval_s else "—"),
        ("Gas", f"{g.name} (O2 {g.o2:g} %, He {g.he:g} %)" + (f", {len(d.gases)} gases" if len(d.gases) > 1 else "")),
        ("Tanks", ", ".join(f"#{t.index} {t.volume_l or '?'} l {t.start_bar or '?'}→{t.end_bar or '?'} bar" for t in d.tanks) or "none in export"),
        ("GF low / high", f"{d.gf_low} / {d.gf_high}"),
        ("Deco dive", "yes" if d.deco else "no"),
        ("Samples", f"{len(d.samples)} (every {d.extra.get('sampling_s', '?')} s)"),
        ("Dive computer", f"{d.computer.display_name} · serial {d.computer.serial}" if d.computer else "—"),
        ("Site name in export", d.site.name if d.site and d.site.name else "—"),
        ("Memo", d.notes or "—"),
        ("Dive number (computer)", d.number),
        ("Source", f"{d.source.filename} · {d.source.format} · id {d.source.dive_id}"),
    ]
    for k, v in d.extra.items():
        facts.append((f"export: {k}", v))
    return facts
