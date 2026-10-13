from datetime import datetime

from divebridge.model import Dive, Source
from divebridge.ssi.dedup import find_existing, next_log_number


def _dive(start: str) -> Dive:
    return Dive(start=datetime.fromisoformat(start), duration_s=600, max_depth_m=10,
                source=Source("test", "f", "1"))


def test_find_by_ref_and_time():
    log = [
        {"odin_user_log_nr": 5, "odin_user_log_date": "2025-10-15", "odin_user_log_entry_time": "02:57",
         "odin_user_log_divecomputer_dive_ref": "x"},
        {"odin_user_log_nr": 6, "odin_user_log_date": "2025-10-16", "odin_user_log_entry_time": "10:00",
         "odin_user_log_divecomputer_dive_ref": "2025-10-16T10:00:00", "odin_user_log_deleted": 0},
        {"odin_user_log_nr": 9, "odin_user_log_date": "2025-10-17", "odin_user_log_entry_time": "10:00",
         "odin_user_log_deleted": 1},
    ]
    assert find_existing(_dive("2025-10-15T02:56:07"), log)["odin_user_log_nr"] == 5  # within 2 min
    assert find_existing(_dive("2025-10-16T10:00:00"), log)["odin_user_log_nr"] == 6  # by ref
    assert find_existing(_dive("2025-10-17T10:00:00"), log) is None  # deleted entry ignored
    assert find_existing(_dive("2025-10-15T03:30:00"), log) is None
    assert next_log_number(log) == 7
    assert next_log_number([]) == 1


def test_prefer_log_number_among_duplicates():
    log = [
        {"odin_user_log_nr": 8, "odin_user_log_date": "2026-10-12", "odin_user_log_entry_time": "15:01",
         "odin_user_log_divecomputer_dive_ref": "2026-10-12T15:01:05", "odin_user_log_verified": True},
        {"odin_user_log_nr": 10, "odin_user_log_date": "2026-10-12", "odin_user_log_entry_time": "15:01",
         "odin_user_log_divecomputer_dive_ref": "2026-10-12T15:01:05"},
    ]
    d = _dive("2026-10-12T15:01:05")
    assert find_existing(d, log)["odin_user_log_nr"] == 8            # default: first match (duplicate check)
    assert find_existing(d, log, prefer_nr=10)["odin_user_log_nr"] == 10  # read-back after an allowed duplicate upload
    assert find_existing(d, log, prefer_nr=99)["odin_user_log_nr"] == 8   # unknown number: fall back
