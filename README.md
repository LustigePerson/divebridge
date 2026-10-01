# divebridge

Bring dive computer exports into the **SSI / MySSI logbook** and into **UDDF** – from your phone,
as a **Home Assistant add-on** with its own web UI.

Built for the **Cressi Da Vinci**, whose companion app *DiveSync* only exports an Excel file.
The code is split into *importers* (input format → canonical dive model) and *exporters*
(canonical model → SSI / UDDF), so other formats can be added by writing one importer.

> **Status: learning project / early version.** The SSI part talks to the *private* API of the
> MySSI app – there is no official API. It can break at any time and is used at your own risk.
> Uploaded dives show up as "unconfirmed" in MySSI, exactly like manually entered ones.

## What it does

1. Upload one or more `*.xlsx` exports from DiveSync (works in the HA companion app on the phone).
2. Review the parsed dives, pick the SSI dive site (auto-suggested from the site name), see which
   dives already exist in your logbook.
3. Either download **UDDF** (for divelogs.de, Subsurface, MacDive, …) or push the selected dives
   to **SSI** – with a dry run that shows the exact payload first.

Everything is also available on the command line (`divebridge --help`).

## Install as Home Assistant add-on (local add-on)

The repository root *is* the add-on (it contains `config.yaml`, `Dockerfile`, `run.sh`).

1. Copy/clone this repository to `/addons/divebridge` on your HA host (Samba share "addons",
   or the SSH/Terminal add-on: `cd /addons && git clone <repo-url> divebridge`).
2. Settings → Add-ons → Add-on Store → ⋮ → *Check for updates*. "divebridge" appears under
   **Local add-ons**. Install, set `ssi_email` / `ssi_password` in the options (optional – you can
   also log in inside the UI), start it, enable *Show in sidebar*.
3. Open "divebridge" from the sidebar – also in the HA companion app while on holiday.

UDDF files are additionally written to `/share/divebridge/uddf/` (configurable).

## Local development

```bash
uv sync                                   # creates .venv with all dependencies
uv run pytest                             # unit tests (use the sample export in data/)
uv run divebridge inspect data/cressi/*.xlsx
uv run divebridge export-uddf -o out/ data/cressi/*.xlsx
export SSI_EMAIL=you@example.com SSI_PASSWORD=...
uv run divebridge ssi-login               # check credentials
uv run divebridge ssi-sites "Monterey"    # search the SSI site database (downloaded + cached in .data/)
uv run divebridge ssi-push data/cressi/*.xlsx            # dry run, prints what would be sent
uv run divebridge ssi-push --send --site-id 1234 file.xlsx   # really upload
uv run divebridge serve --reload          # web UI on http://localhost:8099
```

Build the add-on container locally:

```bash
docker build --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.21 -t divebridge .
docker run --rm -p 8099:8099 -e SSI_EMAIL=... -e SSI_PASSWORD=... divebridge \
  python -m uvicorn divebridge.web.app:app --host 0.0.0.0 --port 8099
```

## Project layout

```
src/divebridge/
  model.py              canonical Dive/Sample/Tank/Gas/DiveComputer (metric units)
  units.py              ft/°F/psi conversions, sentinel handling
  importers/            base.Importer protocol, registry, cressi_divesync.py (XLSX parser)
  exporters/            uddf.py (UDDF 3.2 writer), ssi.py (push orchestration + dedup)
  ssi/                  client.py (private MySSI API), sites.py (site DB), payload.py (save_divelog body)
  cli.py                command line
  web/                  FastAPI app + Jinja2 templates (ingress-aware: X-Ingress-Path)
tests/                  pytest, fixtures use data/cressi/*.xlsx
config.yaml, build.yaml, Dockerfile, run.sh   Home Assistant add-on packaging
```

### Adding another input format

1. Create `src/divebridge/importers/<format>.py` with a class that has `name`, `description`,
   `extensions`, `can_handle(filename, data)` and `parse(filename, data) -> list[Dive]`.
2. Append an instance to `IMPORTERS` in `importers/registry.py`.
3. Add a sample file under `data/<format>/` and a test.

### Input format notes (Cressi DiveSync)

Sheets `DiveLog` (one row per dive, **imperial**: ft, °F, psi), `DiveProfile` (one row per sample,
**metric**), `TankData`, hidden `_DiveSync_Metadata`. `65535` means "no value" (e.g. tank pressure
without transmitter), `SpeedFpm` is an unsigned 16-bit value that wraps for negative speeds.
The device reports its platform name (`SKIFF`); it is mapped to the product name "Da Vinci".

## Roadmap

- v2: push directly to divelogs.de (official REST API, `POST /api/dives`)
- more importers (UDDF/Subsurface as input, other apps)
- optional: contribute the DiveSync parser upstream to divessi-log-importer

## Credits

- **[agrippa1994/divessi-log-importer](https://github.com/agrippa1994/divessi-log-importer)** (Manuel Leitold, MIT) –
  the SSI API calls, the `save_divelog` payload structure and the sample encoding were ported from this project.
  If you use a Suunto, use that project directly.
- **[gerardpuig/divessi-export](https://github.com/gerardpuig/divessi-export)** (MIT) – read-only SSI export in Python,
  confirmed the authentication flow.
- UDDF specification: <http://www.streit.cc/extern/uddf_v321/en/>

## License

MIT – see [LICENSE](LICENSE).
