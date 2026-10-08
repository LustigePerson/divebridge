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

## Connection check from a Home Assistant automation

The add-on answers `GET http://<addon-hostname>:8099/api/check?level=read|write` with JSON
(`ok`, `steps`, …). The hostname is shown on the add-on's start page under *Connection check*
(e.g. `local-divebridge` or `<repo-id>-divebridge`). `write` uploads a one-minute test dive dated
2000-01-01 and deletes it again – that is the only check that proves uploads really work.

`configuration.yaml`:

```yaml
rest_command:
  divebridge_check:
    url: "http://<addon-hostname>:8099/api/check?level=write"
    timeout: 120
```

Automation (run it when you like – before a holiday, weekly, by button):

```yaml
alias: divebridge SSI check
triggers:
  - trigger: time
    at: "04:00:00"
conditions: []
actions:
  - action: rest_command.divebridge_check
    response_variable: result
  - if:
      - condition: template
        value_template: "{{ not result.content.ok }}"
    then:
      - action: persistent_notification.create
        data:
          title: "divebridge: SSI check failed"
          notification_id: divebridge_ssi_check
          message: >-
            {% for s in result.content.steps if not s.ok %}{{ s.name }}: {{ s.detail }}
            {% endfor %}{{ result.content.error or '' }}
    else:
      - action: persistent_notification.dismiss
        data:
          notification_id: divebridge_ssi_check
```

## After uploading

The MySSI app does not notice server-side changes immediately: pull to refresh the logbook or
restart the app. Dives are listed by dive date, so an older dive may appear further down.

## Notes

- SSI has no official API. The add-on uses the same endpoints as the MySSI app; this may stop
  working at any time. Imported dives appear as "unconfirmed".
- Duplicate detection compares the dive computer reference and the start time (±2 min) with
  your existing logbook.
- The SSI dive site database (~ tens of MB) is downloaded once and cached for 7 days in `/data`.
