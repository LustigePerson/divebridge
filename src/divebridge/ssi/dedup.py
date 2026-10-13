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


def find_all(dive: Dive, logbook_details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """All logbook entries matching this dive: by computer dive ref first, then by start time."""
    live = [e for e in logbook_details if e.get("odin_user_log_deleted") not in (1, True)]
    by_ref = [e for e in live if e.get("odin_user_log_divecomputer_dive_ref") == dive.dive_ref]
    target = dive.start.replace(second=0, microsecond=0)
    by_time = [e for e in live if e not in by_ref
               and (es := _entry_start(e)) is not None and abs(es - target) <= TOLERANCE]
    return by_ref + by_time


def find_existing(dive: Dive, logbook_details: list[dict[str, Any]],
                  prefer_nr: int | None = None) -> dict[str, Any] | None:
    """The logbook entry for this dive. With duplicates (allowed uploads) `prefer_nr` picks the
    entry with that log number – e.g. the one just uploaded – instead of the first match."""
    matches = find_all(dive, logbook_details)
    if not matches:
        return None
    if prefer_nr is not None:
        for e in matches:
            if _as_int(e.get("odin_user_log_nr")) == prefer_nr:
                return e
    return matches[0]


def _as_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def next_log_number(logbook_details: list[dict[str, Any]]) -> int:
    nrs = [n for e in logbook_details if e.get("odin_user_log_deleted") not in (1, True)
           if (n := _as_int(e.get("odin_user_log_nr"))) is not None]
    return (max(nrs) if nrs else 0) + 1
