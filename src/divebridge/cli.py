"""Command line interface – everything the web UI does, usable without Home Assistant."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .exporters.ssi import push_dives
from .exporters.uddf import dives_to_uddf, uddf_filename
from .importers import IMPORTERS, parse_file
from .model import Dive
from .settings import Settings
from .ssi.client import APIError, SsiClient
from .ssi.sites import SiteIndex


def _load(paths: list[str]) -> list[Dive]:
    from .importers.registry import expand_archive, is_zip_archive

    dives: list[Dive] = []
    files: list[Path] = []
    for p in paths:
        path = Path(p)
        files.extend(sorted(f for f in path.iterdir() if f.is_file() and not f.name.startswith(".")) if path.is_dir() else [path])
    for path in files:
        data = path.read_bytes()
        entries = expand_archive(path.name, data) if is_zip_archive(path.name, data) else [(path.name, data)]
        for name, blob in entries:
            dives.extend(parse_file(name, blob))
    dives.sort(key=lambda d: d.start)
    return dives


def _client(settings: Settings) -> SsiClient:
    """SSI client from SSI_EMAIL / SSI_PASSWORD; missing values are asked interactively (no shell quoting issues)."""
    email, password = settings.ssi_email, settings.ssi_password
    if sys.stdin.isatty():
        if not email:
            email = input("SSI e-mail: ").strip()
        if not password:
            import getpass

            password = getpass.getpass("SSI password: ")
    # no credentials is fine for offline dry runs; any real SSI call raises a clear APIError
    return SsiClient(email, password, data_dir=settings.data_dir)


def cmd_formats(_: argparse.Namespace, __: Settings) -> int:
    for imp in IMPORTERS:
        print(f"{imp.name:20s} {', '.join(imp.extensions):8s} {imp.description}")
    return 0


def cmd_inspect(args: argparse.Namespace, _: Settings) -> int:
    for d in _load(args.files):
        print(d.summary())
        if args.details:
            print(f"   avg {d.avg_depth_m} m, temp {d.water_temp_min_c}–{d.water_temp_max_c} °C, "
                  f"gas {d.primary_gas.name}, computer {d.computer.display_name if d.computer else '-'} "
                  f"({d.computer.serial if d.computer else '-'}), SI {d.surface_interval_s}s, "
                  f"tanks {len(d.tanks)}, deco {d.deco}, source {d.source.filename}#{d.source.dive_id}")
    return 0


def cmd_export_uddf(args: argparse.Namespace, settings: Settings) -> int:
    dives = _load(args.files)
    out = Path(args.output or settings.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.single:
        f = out / "dives.uddf"
        f.write_bytes(dives_to_uddf(dives))
        print(f"wrote {f} ({len(dives)} dives)")
    else:
        for d in dives:
            f = out / uddf_filename(d)
            f.write_bytes(dives_to_uddf([d]))
            print(f"wrote {f}")
    return 0


def cmd_ssi_login(_: argparse.Namespace, settings: Settings) -> int:
    c = _client(settings)
    c.authenticate()
    me = c.get_user_data()
    print(f"logged in as {me.get('user_forename')} {me.get('user_lastname')} ({me.get('user_email')}), "
          f"{me.get('user_no_dives')} dives")
    return 0


def cmd_ssi_logbook(args: argparse.Namespace, settings: Settings) -> int:
    lb = _client(settings).get_divelog()
    details = lb.get("logbook_details", [])
    sites = {s["odin_dive_sites_id"]: s.get("odin_dive_sites_name") for s in lb.get("logbook_sites", [])}
    for e in details[-args.last:]:
        print(f"#{e.get('odin_user_log_nr'):>4} {e.get('odin_user_log_date')} {e.get('odin_user_log_entry_time')} "
              f"{e.get('odin_user_log_divetime')} min {e.get('odin_user_log_depth_m')} m "
              f"{sites.get(e.get('odin_user_log_dive_sites_id'), '?')}  "
              f"[{e.get('odin_user_log_divecomputer_name') or 'manual'}] ref={e.get('odin_user_log_divecomputer_dive_ref')}")
    print(f"{len(details)} dives in logbook")
    return 0


def _print_diffs(diffs, verbose: bool) -> None:
    for d in diffs:
        if verbose or not d.ok:
            print(f"   {'ok ' if d.ok else '!! '}{d.label:22s} sent={d.sent!r:30.30} stored={d.stored!r:30.30}")


def cmd_ssi_verify(args: argparse.Namespace, settings: Settings) -> int:
    """Compare dives from export files with what the SSI logbook stores for them."""
    from .ssi.dedup import find_existing
    from .ssi.payload import build_payload
    from .ssi.verify import compare, summarize

    dives = _load(args.files)
    details = _client(settings).get_divelog().get("logbook_details", [])
    rc = 0
    for d in dives:
        stored = find_existing(d, details)
        if stored is None:
            print(f"missing   {d.summary()}")
            rc = 1
            continue
        payload = build_payload(d, log_nr=int(stored.get("odin_user_log_nr") or 0),
                                site_id=stored.get("odin_user_log_dive_sites_id"))
        diffs = compare(payload, stored)
        print(f"#{stored.get('odin_user_log_nr'):<4} {d.summary()}  -> {summarize(diffs)}")
        _print_diffs(diffs, args.all_fields)
    return rc


def cmd_ssi_vars(args: argparse.Namespace, settings: Settings) -> int:
    """Print the SSI logbook variable definitions (id -> name) as the MySSI app loads them."""
    from .ssi.vars import GROUPS, VarIndex, pretty

    idx = VarIndex(settings.data_dir, _client(settings))
    if args.refresh:
        idx.refresh()
    table = idx.table()
    groups = table if args.all else {g: table.get(g, {}) for g in GROUPS}
    for group, items in groups.items():
        print(f"{group}:")
        for i, n in sorted(items.items()):
            print(f"  {i:>4}  {pretty(n)}")
    return 0


def cmd_ssi_sites(args: argparse.Namespace, settings: Settings) -> int:
    idx = SiteIndex(settings.data_dir, _client(settings))
    if args.refresh:
        idx.ensure(force=True)
    if args.near:
        lat, lon = (float(x) for x in args.near.split(","))
        m = idx.nearest(lat, lon)
        print(m.label if m else "no site within 5 km")
        return 0
    for m in idx.search(args.query):
        print(f"{m.id:>8}  {m.label}")
    print(f"({len(idx)} sites in index)")
    return 0


def cmd_ssi_push(args: argparse.Namespace, settings: Settings) -> int:
    dives = _load(args.files)
    client = _client(settings)
    site_ids: dict[int, int | None] = {}
    logbook = None
    idx = None
    online = bool(settings.ssi_email or client.has_token)
    if online:
        idx = SiteIndex(settings.data_dir, client)
        try:
            logbook = client.get_divelog()
        except APIError as e:
            if args.send:
                raise
            print(f"(SSI logbook not available: {e})")
    if args.site_id:
        site_ids = {i: args.site_id for i in range(len(dives))}
    elif not args.no_site_lookup and idx is not None:
        visited = {int(s["odin_dive_sites_id"]) for s in (logbook or {}).get("logbook_sites", []) if s.get("odin_dive_sites_id")}
        for i, d in enumerate(dives):
            if d.site and d.site.name:
                hits = idx.search(d.site.name, limit=1, prefer=visited)
                site_ids[i] = hits[0].id if hits else None
                print(f"site for {d.site.name!r}: {hits[0].label if hits else 'not found'}")
    from .ssi.payload import DiveOptions

    results = push_dives(client, dives, site_ids, dry_run=not args.send, skip_duplicates=not args.allow_duplicates,
                         logbook=logbook, options=DiveOptions(mark_imported=not args.no_imported_flag),
                         site_bow=(lambda sid: (m.bow if (m := idx.get(sid)) else None)) if idx else None)
    for r in results:
        print(f"{r.status:18s} {r.dive.summary()}  -> {r.message}")
        if args.dump_payload and r.payload:
            out = Path(args.dump_payload)
            out.mkdir(parents=True, exist_ok=True)
            f = out / f"payload_{r.dive.start:%Y%m%d_%H%M}.json"
            f.write_text(json.dumps(r.payload, indent=2))
            print(f"   payload written to {f}")
        if r.response is not None and args.verbose:
            print("   response:", json.dumps(r.response)[:500])
        if r.diffs:
            _print_diffs(r.diffs, args.verbose)
    if not args.send:
        print("\nDry run – nothing was sent. Add --send to upload.")
    return 0 if all(r.status != "error" for r in results) else 1


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    uvicorn.run("divebridge.web.app:app", host=args.host, port=args.port or settings.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="divebridge", description="Dive computer exports -> SSI logbook / UDDF")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("formats", help="list supported input formats").set_defaults(fn=cmd_formats)

    s = sub.add_parser("inspect", help="parse files and print the dives")
    s.add_argument("files", nargs="+")
    s.add_argument("-v", "--details", action="store_true", dest="details")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("export-uddf", help="write UDDF files")
    s.add_argument("files", nargs="+")
    s.add_argument("-o", "--output", help="output directory (default: DIVEBRIDGE_OUTPUT_DIR)")
    s.add_argument("--single", action="store_true", help="one file with all dives instead of one per dive")
    s.set_defaults(fn=cmd_export_uddf)

    s = sub.add_parser("ssi-login", help="check SSI credentials (SSI_EMAIL / SSI_PASSWORD)")
    s.set_defaults(fn=cmd_ssi_login)

    s = sub.add_parser("ssi-logbook", help="print the SSI logbook")
    s.add_argument("--last", type=int, default=20)
    s.set_defaults(fn=cmd_ssi_logbook)

    s = sub.add_parser("ssi-verify", help="compare export files with the dives stored in the SSI logbook")
    s.add_argument("files", nargs="+")
    s.add_argument("-v", "--all-fields", action="store_true", dest="all_fields", help="show all fields, not only differences")
    s.set_defaults(fn=cmd_ssi_verify)

    s = sub.add_parser("ssi-vars", help="show SSI logbook variable ids (weather, water, entry, ...)")
    s.add_argument("--all", action="store_true", help="include freediving/XR/CCR groups")
    s.add_argument("--refresh", action="store_true", help="re-download from SSI")
    s.set_defaults(fn=cmd_ssi_vars)

    s = sub.add_parser("ssi-sites", help="search the SSI dive site database")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--near", help="lat,lon – nearest site instead of name search")
    s.add_argument("--refresh", action="store_true", help="re-download the site database")
    s.set_defaults(fn=cmd_ssi_sites)

    s = sub.add_parser("ssi-push", help="upload dives to SSI (dry run unless --send)")
    s.add_argument("files", nargs="+")
    s.add_argument("--send", action="store_true", help="really upload")
    s.add_argument("--site-id", type=int, help="SSI dive site id for all dives")
    s.add_argument("--no-site-lookup", action="store_true")
    s.add_argument("--allow-duplicates", action="store_true")
    s.add_argument("--no-imported-flag", action="store_true", help="do not mark dives as imported from a dive computer")
    s.add_argument("--dump-payload", metavar="DIR", help="write payload JSON per dive into DIR")
    s.set_defaults(fn=cmd_ssi_push)

    s = sub.add_parser("serve", help="run the web UI")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # httpx/httpcore log full request URLs – with the SSI API that includes password and token. Never.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    settings = Settings.from_env()
    try:
        sys.exit(args.fn(args, settings))
    except APIError as e:
        print(f"SSI error: {e}", file=sys.stderr)
        sys.exit(2)
