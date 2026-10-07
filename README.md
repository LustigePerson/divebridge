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
   to **SSI** – with a dry run that shows the exact payload first. The UDDF carries the buddies,
   dive site and notes chosen in the review form, so it is a complete archive of what went to SSI.

Everything is also available on the command line (`divebridge --help`).

## Install as Home Assistant add-on

**From GitHub (recommended):** Settings → Add-ons → Add-on Store → ⋮ → *Repositories* → add
`https://github.com/LustigePerson/divebridge`. "divebridge" appears in the store; install it, set
`ssi_email` / `ssi_password` in the options (optional – you can also log in inside the UI), start it,
enable *Show in sidebar*. Updates arrive through the store like for any other add-on.

**As a local add-on:** copy/clone this repository to `/addons/divebridge` on the HA host (Samba share
"addons" or the SSH add-on), then ⋮ → *Check for updates*; it shows up under *Local add-ons*.

Open "divebridge" from the sidebar – also in the HA companion app while on holiday.

UDDF files are additionally written to `/share/divebridge/uddf/` (configurable).

## Local development

```bash
uv sync                                   # creates .venv with all dependencies
uv run pytest                             # unit tests (use the sample export in tests/data/)
uv run divebridge inspect tests/data/cressi/*.xlsx
uv run divebridge export-uddf -o out/ tests/data/cressi/*.xlsx
export SSI_EMAIL=you@example.com SSI_PASSWORD=...
uv run divebridge ssi-login               # check credentials
uv run divebridge ssi-sites "Monterey"    # search the SSI site database (downloaded + cached in .data/)
uv run divebridge ssi-push tests/data/cressi/*.xlsx            # dry run, prints what would be sent
uv run divebridge ssi-push --send --site-id 1234 file.xlsx   # really upload
uv run divebridge serve --reload          # web UI on http://localhost:8099
```

### Test inside a real Supervisor (official devcontainer)

Home Assistant ships a devcontainer that runs a complete Supervisor + Home Assistant inside Docker,
so the add-on can be installed and started exactly like on a real host:

1. VS Code with the *Dev Containers* extension and Docker installed.
2. Open this folder in VS Code → "Reopen in Container" (uses `.devcontainer.json`).
3. Run the task **Start Home Assistant** (`supervisor_run`). First start takes a few minutes.
4. Open <http://localhost:7123>, finish onboarding, then Settings → Add-ons/Apps → Store:
   divebridge is listed under *Local*. Or use the tasks **Install divebridge** / **Rebuild and start divebridge**.
5. Ingress, options and `/share` behave like in production. Logs: task output or the add-on's log tab.

Build the add-on container locally (without Supervisor):

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
tests/                  pytest, fixtures use tests/data/cressi/*.xlsx
config.yaml, build.yaml, Dockerfile, run.sh   Home Assistant add-on packaging
```

### Adding another input format

1. Create `src/divebridge/importers/<format>.py` with a class that has `name`, `description`,
   `extensions`, `can_handle(filename, data)` and `parse(filename, data) -> list[Dive]`.
2. Append an instance to `IMPORTERS` in `importers/registry.py`.
3. Add a sample file under `tests/data/<format>/` and a test.

### Input format notes (Cressi DiveSync)

Sheets `DiveLog` (one row per dive, **imperial**: ft, °F, psi), `DiveProfile` (one row per sample,
**metric**), `TankData`, hidden `_DiveSync_Metadata`. `65535` means "no value" (e.g. tank pressure
without transmitter), `SpeedFpm` is an unsigned 16-bit value that wraps for negative speeds.
The device reports its platform name (`SKIFF`); it is mapped to the product name "Da Vinci".

### Verified against a real MySSI logbook (2026-10-01)

Uploaded dives are read back and compared field by field (`ssi-verify`, also automatic after upload).
Known facts and quirks:

- Surface interval (`si_before`) is in **seconds**; MySSI shows it as hh:mm.
- Water type ids: 5 = salt, 4 = fresh (the reference project had this the other way round).
  Default "auto" takes it from the chosen SSI dive site.
- Gradient factors are sent as the export reports them (e.g. 89/89) even though DiveSync displays
  the conservatism preset as "C0 90/90". The export has no column for the preset.
- Memo from DiveSync becomes the SSI note; UI notes are appended.
- The Da Vinci records profile points only under water; the SSI profile ends at the last recorded
  point (as in the DiveSync app) plus one surface point if the last point is still under water.
  The dive time is sent separately and may be longer than the profile.
- Dive time is stored as whole minutes (22.6 -> 23); the serial number loses leading zeros.
- `odin_user_log_divecomputer_imported: true` makes the app show a computer icon and a "dive computer"
  field (the reference sends false). Default on, switchable in the UI / `--no-imported-flag`.
- `odin_user_log_diveComputer` (legacy free text) is shown by the app in the partner/center line,
  so it is left empty; the computer is identified by the `divecomputer_*` fields.
- Deleted dives are not returned by the SSI API at all, so they do not count as duplicates.
- Home Assistant companion app (Android): its WebView drops multi-file selections (`<input multiple>`
  returns nothing), so the add-on serves a single-file input to Android WebViews – upload one export
  or a ZIP with all of them; verified working. Reported upstream as
  [home-assistant/android#7548](https://github.com/home-assistant/android/issues/7548). The app does
  not support browser geolocation; use the phone's browser for that.
- The MySSI app caches the logbook: after an upload, pull to refresh or restart the app, and
  remember the list is sorted by dive date, not by upload time.
- Variable lists (weather, entry, body of water, special dive, …) come from `what=get_divelog_vars`;
  a copy is bundled for offline use. Multi-value "special dive" is sent as `"40,47"`.

## Status / TODO

Done and verified (2026-10-01): DiveSync XLSX import, UDDF export, SSI upload with profile and all
optional fields, duplicate detection, read-back verification against a real MySSI logbook, dive
site search with distance / map, web UI, CLI, add-on installed from this repository on a real
Home Assistant and used from the companion app (single file / ZIP) and from the phone browser.

Open:

- [ ] First export from a real Cressi Da Vinci: date format with non-US settings, memo, nitrox,
      several dives in one file, device name (currently `SKIFF` is mapped to "Da Vinci").
- [ ] Surface interval: DiveSync's `SurfTime` before the *first* dive of a day is the time since the
      computer was switched on (82 min observed for a first pool dive), not a real surface interval.
      Observe with real dives first; possibly a bug report to the app vendor, or a UI override.
- [ ] Verify dive site mapping with real dives; use GPS from the export (`GPSStartDive`) for the
      nearest-site lookup once a real export shows the coordinate format.
- [ ] Companion app: once [home-assistant/android#7549](https://github.com/home-assistant/android/pull/7549)
      is released, drop the single-file input for Android WebViews (`is_companion_app` in
      `web/app.py`) and allow multi-select in the app again. Browser geolocation in the app needs
      a separate upstream fix (draft in `.data/issues/`, not filed).
- [ ] SSI gear / equipment (`odin_user_log_gear`): needs the equipment list from the SSI profile
      (API call still to be found) and a multi-select in the UI.
- [ ] Dive center field (`log_linked_facility_id`, centers come from `APP_CACHE_CENTER.zip`).
- [ ] v2: push directly to divelogs.de (official REST API, `POST /api/dives`).
- [ ] More importers (UDDF/Subsurface as input, other apps).
- [ ] Optional: contribute the DiveSync parser upstream to divessi-log-importer.

## Credits

- **[agrippa1994/divessi-log-importer](https://github.com/agrippa1994/divessi-log-importer)** (Manuel Leitold, MIT) –
  the SSI API calls, the `save_divelog` payload structure and the sample encoding were ported from this project.
  If you use a Suunto, use that project directly.
- **[gerardpuig/divessi-export](https://github.com/gerardpuig/divessi-export)** (MIT) – read-only SSI export in Python,
  confirmed the authentication flow.
- UDDF specification: <http://www.streit.cc/extern/uddf_v321/en/>

## License

MIT – see [LICENSE](LICENSE).
