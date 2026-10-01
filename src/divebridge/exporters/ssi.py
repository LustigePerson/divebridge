"""Push canonical dives into the SSI logbook."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..model import Dive
from ..ssi.client import APIError, SsiClient
from ..ssi.dedup import find_existing, next_log_number
from ..ssi.payload import DiveOptions, build_payload
from ..ssi.verify import FieldDiff, compare

log = logging.getLogger(__name__)


@dataclass
class PushResult:
    dive: Dive
    status: str  # "uploaded" | "dry-run" | "skipped-duplicate" | "error"
    log_nr: int | None = None
    site_id: int | None = None
    message: str = ""
    payload: dict[str, Any] | None = None
    response: Any = None
    existing: dict[str, Any] | None = field(default=None, repr=False)
    stored: dict[str, Any] | None = field(default=None, repr=False)  # logbook entry read back after upload
    diffs: list[FieldDiff] = field(default_factory=list)


def push_dives(client: SsiClient, dives: list[Dive], site_ids: dict[int, int | None] | None = None,
               dry_run: bool = True, skip_duplicates: bool = True,
               logbook: dict[str, Any] | None = None,
               options: DiveOptions | None = None,
               per_dive_options: dict[int, DiveOptions] | None = None,
               site_bow: Callable[[int], str | None] | None = None) -> list[PushResult]:
    """Upload dives in chronological order, numbering them after the last logbook entry.

    site_ids / per_dive_options map index-in-`dives` -> value; `options` are the batch defaults.
    """
    defaults = options or DiveOptions()
    if logbook is None:
        try:
            logbook = client.get_divelog()
        except APIError:
            if not dry_run:
                raise
            # offline dry run: no numbering / duplicate information available
            log.warning("SSI logbook not available – dry run without duplicate check, numbering from 1")
            logbook = {}
    details: list[dict[str, Any]] = list(logbook.get("logbook_details", []))
    nr = next_log_number(details)
    results: list[PushResult] = []
    order = sorted(range(len(dives)), key=lambda i: dives[i].start)
    for i in order:
        dive = dives[i]
        site_id = (site_ids or {}).get(i)
        existing = find_existing(dive, details)
        if existing is not None and skip_duplicates:
            results.append(PushResult(dive, "skipped-duplicate", log_nr=existing.get("odin_user_log_nr"),
                                      site_id=site_id, existing=existing,
                                      message=f"already in logbook as #{existing.get('odin_user_log_nr')}"))
            continue
        opts = defaults.merged((per_dive_options or {}).get(i))
        if site_id is not None and site_bow is not None:
            try:
                opts.resolve_watertype(site_bow(site_id))
            except Exception as e:  # noqa: BLE001
                log.warning("water type lookup for site %s failed: %s", site_id, e)
        payload = build_payload(dive, log_nr=nr, site_id=site_id, options=opts)
        if dry_run:
            results.append(PushResult(dive, "dry-run", log_nr=nr, site_id=site_id, payload=payload,
                                      message="not sent (dry run)"))
            nr += 1
            continue
        try:
            resp = client.save_divelog(payload)
        except Exception as e:  # noqa: BLE001
            log.exception("save_divelog failed for %s", dive.summary())
            results.append(PushResult(dive, "error", log_nr=nr, site_id=site_id, payload=payload, message=str(e)))
            continue
        results.append(PushResult(dive, "uploaded", log_nr=nr, site_id=site_id, payload=payload, response=resp,
                                  message=f"uploaded as #{nr}"))
        # keep local view of the logbook current so a re-run in the same batch dedups correctly
        details.append({"odin_user_log_nr": nr, "odin_user_log_divecomputer_dive_ref": dive.dive_ref,
                        "odin_user_log_date": f"{dive.start:%Y-%m-%d}", "odin_user_log_entry_time": f"{dive.start:%H:%M}"})
        nr += 1
    # round-trip check: read the logbook back and compare every uploaded dive
    if not dry_run and any(r.status == "uploaded" for r in results):
        try:
            fresh = client.get_divelog().get("logbook_details", [])
        except Exception as e:  # noqa: BLE001
            log.warning("read-back failed: %s", e)
            fresh = []
        for r in results:
            if r.status != "uploaded" or not r.payload:
                continue
            r.stored = find_existing(r.dive, fresh)
            if r.stored is None:
                r.message += " – NOT found in logbook on read-back!"
                continue
            r.diffs = compare(r.payload, r.stored)
            bad = [d for d in r.diffs if not d.ok]
            r.message += f" – read back ok" if not bad else f" – read back differs: {', '.join(d.label for d in bad)}"
    # restore original order
    by_idx = {id(r.dive): r for r in results}
    return [by_idx[id(d)] for d in dives]
