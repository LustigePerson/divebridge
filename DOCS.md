# divebridge add-on

Upload dive computer exports (Cressi DiveSync Excel files), review them, download UDDF
or push them to your SSI / MySSI logbook.

## Options

| Option | Description |
|---|---|
| `ssi_email` / `ssi_password` | MySSI login. Optional – you can also log in inside the UI (kept in memory only). |
| `output_dir` | Where UDDF files are written in addition to the browser download. Default `/share/divebridge/uddf`. |
| `dry_run_default` | Tick "dry run" by default on the review page (`false`). A dry run shows the SSI payload without sending. |
| `log_level` | `debug`, `info`, `warning`, `error` |

## Usage

1. Open the add-on from the sidebar (works in the companion app).
2. Upload one or more `.xlsx` files exported from DiveSync (*Share / Export to Excel*).
3. Check the list: date, duration, depth, suggested SSI dive site (type to search), and whether
   the dive already exists in your SSI logbook.
4. *Download UDDF* or *Upload to SSI*. Keep *dry run* ticked the first time: it shows the payload
   without sending anything.

## Several files from the phone

The Home Assistant companion app hands over only one file per upload (its WebView ignores
multi-selection results), so inside the app the upload field takes one file: a single export or a
ZIP containing all exports (file manager: select the files → compress). In the phone's browser
several files can be selected directly.

## After uploading

The MySSI app does not notice server-side changes immediately: pull to refresh the logbook or
restart the app. Dives are listed by dive date, so an older dive may appear further down.

## Notes

- SSI has no official API. The add-on uses the same endpoints as the MySSI app; this may stop
  working at any time. Imported dives appear as "unconfirmed".
- Duplicate detection compares the dive computer reference and the start time (±2 min) with
  your existing logbook.
- The SSI dive site database (~ tens of MB) is downloaded once and cached for 7 days in `/data`.
