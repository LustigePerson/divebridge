"""Web UI: upload exports -> review -> UDDF download / SSI upload. Designed for Home Assistant ingress."""

from __future__ import annotations

import io
import json
import logging
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..exporters.ssi import PushResult, push_dives
from ..exporters.uddf import dives_to_uddf, uddf_filename
from ..importers import ImportError_, detect, parse_file
from ..model import Dive
from ..settings import Settings
from ..ssi.client import APIError, SsiClient
from ..ssi.dedup import find_existing
from ..ssi.sites import SiteIndex, SiteMatch

log = logging.getLogger(__name__)
HA_INGRESS_IP = "172.30.32.2"


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

    def sites(self) -> SiteIndex:
        if self._sites is None:
            self._sites = SiteIndex(self.settings.data_dir, self.client())
        return self._sites

    def refresh_logbook(self) -> dict[str, Any] | None:
        if not self.ssi_configured:
            return None
        try:
            self.logbook = self.client().get_divelog()
            self.last_error = None
        except (APIError, Exception) as e:  # noqa: BLE001
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
        "root": _root(request), "state": state, "version": __version__, **ctx})


@app.middleware("http")
async def ingress_guard(request: Request, call_next):
    if settings.ingress_only and request.client and request.client.host != HA_INGRESS_IP:
        return Response("forbidden", status_code=403)
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    batches = sorted(state.batches.values(), key=lambda b: b.created, reverse=True)
    return render(request, "index.html", batches=batches)


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    state.email, state.password = email.strip(), password
    state.reset_client()
    try:
        state.client().authenticate()
        state.last_error = None
    except (APIError, Exception) as e:  # noqa: BLE001
        state.last_error = f"SSI login failed: {e}"
    return RedirectResponse(url=f"{_root(request)}/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    state.client().forget_token()
    state.email = settings.ssi_email
    state.password = settings.ssi_password
    state.reset_client()
    return RedirectResponse(url=f"{_root(request)}/", status_code=303)


@app.post("/upload")
async def upload(request: Request, files: list[UploadFile] = File(...)):
    bid = secrets.token_hex(4)
    batch = Batch(id=bid, created=datetime.now(), files=[], dives=[])
    upload_dir = settings.data_dir / "uploads" / bid
    for f in files:
        data = await f.read()
        name = Path(f.filename or "upload").name
        if not data:
            continue
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
    state.batches[bid] = batch

    # enrich with SSI data when available (never fail the upload because of SSI)
    if state.ssi_configured and batch.dives:
        logbook = state.refresh_logbook()
        details = logbook.get("logbook_details", []) if logbook else []
        for i, d in enumerate(batch.dives):
            batch.existing[i] = find_existing(d, details) if details else None
            if d.site and d.site.name:
                try:
                    hits = state.sites().search(d.site.name, limit=1)
                    batch.site_suggestions[i] = hits[0] if hits else None
                except Exception as e:  # noqa: BLE001
                    state.last_error = f"SSI site index: {e}"
                    log.warning("site lookup failed: %s", e)
    return RedirectResponse(url=f"{_root(request)}/batch/{bid}", status_code=303)


@app.get("/batch/{bid}", response_class=HTMLResponse)
def batch_page(request: Request, bid: str):
    batch = state.batches.get(bid)
    if batch is None:
        return RedirectResponse(url=f"{_root(request)}/", status_code=303)
    return render(request, "batch.html", batch=batch)


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
    try:
        results = push_dives(state.client(), dives, local_sites, dry_run=dry_run,
                             skip_duplicates=form.get("allow_duplicates") != "1")
        state.last_error = None
    except (APIError, Exception) as e:  # noqa: BLE001
        log.exception("push failed")
        state.last_error = f"SSI: {e}"
        results = []
    batch.results = results
    if not dry_run and results:
        state.logbook = None  # force refresh next time
    return render(request, "result.html", batch=batch, results=results, dry_run=dry_run,
                  payload_json=lambda r: json.dumps(r.payload, indent=1) if r.payload else "")


@app.get("/api/sites")
def api_sites(q: str = "", limit: int = 15):
    if not state.ssi_configured:
        return JSONResponse([], status_code=200)
    try:
        return [{"id": m.id, "label": m.label} for m in state.sites().search(q, limit=limit)]
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=503)
