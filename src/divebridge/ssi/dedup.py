"""Find dives that already exist in the SSI logbook."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..model import Dive

TOLERANCE = timedelta(minutes=2)


def _entry_start(entry: dict[str, Any]) -> datetime | None:
    date = entry.get("odin_user_log_date")
    time_ = entry.get("odin_user_log_entry_time")
    if not date or not time_:
        return None
    try:
        return datetime.strptime(f"{str(date)[:10]} {str(time_)[:5]}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def find_existing(dive: Dive, logbook_details: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the logbook entry matching this dive (by computer dive ref, else by start time)."""
    for entry in logbook_details:
        if entry.get("odin_user_log_deleted") in (1, True):
            continue
        if entry.get("odin_user_log_divecomputer_dive_ref") == dive.dive_ref:
            return entry
    target = dive.start.replace(second=0, microsecond=0)
    for entry in logbook_details:
        if entry.get("odin_user_log_deleted") in (1, True):
            continue
        es = _entry_start(entry)
        if es is not None and abs(es - target) <= TOLERANCE:
            return entry
    return None


def next_log_number(logbook_details: list[dict[str, Any]]) -> int:
    nrs = [int(e["odin_user_log_nr"]) for e in logbook_details
           if e.get("odin_user_log_nr") is not None and e.get("odin_user_log_deleted") not in (1, True)]
    return (max(nrs) if nrs else 0) + 1
