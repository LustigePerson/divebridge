"""Connection check against SSI: read-only (login, logbook, variables, sites) or a full write
round trip (upload a minimal test dive, read it back, delete it, confirm it is gone).

Meant to be triggered on demand – from the add-on page, the CLI or a Home Assistant automation
via the add-on's /api/check endpoint – not as a nightly job on every installation.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..model import Dive, DiveComputer, Sample, Source
from .client import APIError, SsiClient
from .dedup import find_existing, next_log_number
from .payload import DiveOptions, build_payload
from .sites import SiteIndex
from .vars import VarIndex

TEST_DIVE_NOTE = "divebridge connection test – deleted automatically"


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""
    ms: int = 0


@dataclass
class CheckResult:
    level: str
    ok: bool
    steps: list[Step] = field(default_factory=list)
    started: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        failed = [s for s in self.steps if not s.ok]
        if self.ok:
            return f"SSI {self.level} check ok ({len(self.steps)} steps)"
        return "SSI check FAILED: " + "; ".join(f"{s.name}: {s.detail}" for s in failed) + (f"; {self.error}" if self.error else "")


def _test_dive() -> Dive:
    """A tiny, clearly artificial dive: year 2000, 1 minute, 1.5 m, 'divebridge check' computer."""
    start = datetime(2000, 1, 1, 0, 0, 0)
    samples = [Sample(t_s=t, depth_m=1.5 if 0 < t < 60 else 0.0, temp_c=20.0) for t in (0, 5, 30, 55, 60)]
    return Dive(start=start, duration_s=60, max_depth_m=1.5, avg_depth_m=1.2, water_temp_min_c=20.0,
                water_temp_max_c=20.0, computer=DiveComputer("divebridge", "check", serial="0"),
                samples=samples, notes=TEST_DIVE_NOTE, source=Source("check", "-", "check"))


def run_check(client: SsiClient, level: str = "read", data_dir: Path | None = None) -> CheckResult:
    res = CheckResult(level=level, ok=True, started=datetime.now().replace(microsecond=0).isoformat())

    def step(name: str, fn, detail_fn=lambda v: "") -> Any:
        t0 = time.time()
        try:
            v = fn()
            res.steps.append(Step(name, True, detail_fn(v), int((time.time() - t0) * 1000)))
            return v
        except Exception as e:  # noqa: BLE001
            res.steps.append(Step(name, False, str(e)[:200], int((time.time() - t0) * 1000)))
            res.ok = False
            raise

    try:
        client.forget_token()  # a check must prove that a fresh login works, not that a cached token does
        step("authenticate", client.authenticate, lambda t: "token received")
        me = step("get_user_data", client.get_user_data, lambda m: f"{m.get('user_forename', '')} {m.get('user_lastname', '')}".strip())
        logbook = step("get_divelog", client.get_divelog, lambda lb: f"{len(lb.get('logbook_details', []))} dives")
        step("get_divelog_vars", lambda: VarIndex(data_dir, client).refresh(), lambda t: f"{len(t)} groups")
        if data_dir is not None:
            step("sites", lambda: (lambda idx: (idx.ensure(), len(idx))[1])(SiteIndex(data_dir, client)), lambda n: f"{n} sites")
        if level != "write":
            return res

        dive = _test_dive()
        details = logbook.get("logbook_details", [])
        if find_existing(dive, details) is not None:
            # leftover from an interrupted earlier check – remove it first
            step("cleanup", lambda: delete_dive(client, find_existing(dive, details)), lambda r: "old test dive removed")
            details = client.get_divelog().get("logbook_details", [])
        payload = build_payload(dive, log_nr=next_log_number(details), site_id=None,
                                options=DiveOptions(mark_imported=False))
        step("save_divelog", lambda: client.save_divelog(payload),
             lambda r: "stored record echoed" if isinstance(r, dict) and "odin_user_log_nr" in r else f"unexpected answer: {str(r)[:80]}")
        stored = step("read back", lambda: find_existing(dive, client.get_divelog().get("logbook_details", [])) or _raise("test dive not in logbook after upload"),
                      lambda s: f"stored as #{s.get('odin_user_log_nr')} id {s.get('odin_user_log_id')}")
        step("delete", lambda: delete_dive(client, stored), lambda r: str(r.get("success", {}).get("ok", r))[:60] if isinstance(r, dict) else str(r)[:60])
        step("read back after delete", lambda: None if find_existing(dive, client.get_divelog().get("logbook_details", [])) is None else _raise("test dive still in logbook after delete"),
             lambda _: "gone")
    except Exception as e:  # noqa: BLE001
        res.ok = False
        if not res.steps or res.steps[-1].ok:
            res.error = str(e)[:200]
    return res


def _raise(msg: str):
    raise APIError(msg)


def delete_dive(client: SsiClient, stored: dict[str, Any]) -> Any:
    """Delete a logbook entry: the app sends the record back with the deleted flag set.
    Verified 2026-10-08: answer {"success": {"ok": "deleted", ...}} and the entry disappears."""
    payload = {k: v for k, v in stored.items() if k.startswith("odin_user_log_") or k in ("needsUpload",)}
    payload["odin_user_log_id"] = stored["odin_user_log_id"]
    payload["odin_user_log_deleted"] = True
    payload["needsUpload"] = True
    r = client.save_divelog(payload)
    ok = isinstance(r, dict) and str(r.get("success", {}).get("ok", "")).lower().startswith("deleted")
    if not ok:
        raise APIError(f"delete not confirmed: {str(r)[:120]}")
    return r
