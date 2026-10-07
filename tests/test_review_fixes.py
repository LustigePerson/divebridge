"""Regression tests for the findings of the 2026-10-01 code review."""

import io
import json
import zipfile

import pytest

from divebridge.importers.base import ImportError_
from divebridge.importers.registry import expand_archive
from divebridge.ssi.dedup import next_log_number
from divebridge.ssi.payload import DiveOptions, build_payload


def test_mark_imported_not_forced_by_per_dive_override(sample_dives):
    batch = DiveOptions(mark_imported=False)
    per_dive = DiveOptions(divetype_id=None, tanktype_id=None, mark_imported=None)
    assert batch.merged(per_dive).mark_imported is False
    assert build_payload(sample_dives[0], 1, None, options=batch.merged(per_dive))["odin_user_log_divecomputer_imported"] is False
    assert DiveOptions(mark_imported=True).merged(DiveOptions(mark_imported=False)).mark_imported is False


def test_next_log_number_tolerates_garbage():
    assert next_log_number([{"odin_user_log_nr": ""}, {"odin_user_log_nr": "7"}, {"odin_user_log_nr": None},
                            {"odin_user_log_nr": "x"}, {"odin_user_log_nr": 9, "odin_user_log_deleted": 1}]) == 8


def test_archive_limits():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.xlsx", b"x")
    assert expand_archive("a.zip", buf.getvalue()) == [("a.xlsx", b"x")]
    big = zipfile.ZipInfo("big.bin")
    big.file_size = 10**9
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("big.bin", b"\0" * 10)
    import divebridge.importers.registry as reg
    old = reg.MAX_MEMBER_BYTES
    reg.MAX_MEMBER_BYTES = 5
    try:
        with pytest.raises(ImportError_):
            expand_archive("big.zip", buf.getvalue())
    finally:
        reg.MAX_MEMBER_BYTES = old


def test_imperial_tank_size_is_capacity_not_volume():
    from divebridge.importers.cressi_divesync import CressiDiveSyncImporter
    from divebridge.model import Dive

    imp = CressiDiveSyncImporter()
    row = {"DiveID": 1, "DiveStartLocalTime": "10/15/2025 02:56:07", "TotalDiveTime": 600, "MaxDepthFT": 33,
           "StartingMixIdx": 1, "Mix1Fo2Percent": 21}
    tanks = [{"DiveID": 1, "TankNo": 1, "TankUnit": 0, "CylinderSize": 80, "WorkingPressure": 3000,
              "StartPressure": 3000, "EndPressure": 700}]
    d: Dive = imp._dive("f.xlsx", row, [], tanks, {})
    assert 10.5 < d.tanks[0].volume_l < 11.5  # AL80 ≈ 11.1 l water volume
    assert abs(d.tanks[0].start_bar - 206.8) < 0.5


def test_gas_index_ignores_sentinel_mix():
    from divebridge.importers.cressi_divesync import CressiDiveSyncImporter

    imp = CressiDiveSyncImporter()
    row = {"DiveID": 1, "DiveStartLocalTime": "10/15/2025 02:56:07", "TotalDiveTime": 30, "MaxDepthFT": 33,
           "StartingMixIdx": 1, "Mix1Fo2Percent": 21, "Mix2Fo2Percent": 32}
    profile = [{"DiveID": 1, "DiveTime": 0, "DepthMeters": 5, "CurrentUsedMixIdx": 1},
               {"DiveID": 1, "DiveTime": 10, "DepthMeters": 5, "CurrentUsedMixIdx": 255},
               {"DiveID": 1, "DiveTime": 20, "DepthMeters": 5, "CurrentUsedMixIdx": 2}]
    d = imp._dive("f.xlsx", row, profile, [], {})
    assert [g.o2 for g in d.gases] == [21, 32]
    assert [s.gas_index for s in d.samples] == [0, None, 1]


def test_api_error_never_contains_credentials(monkeypatch):
    import httpx

    from divebridge.ssi.client import APIError, SsiClient

    c = SsiClient("me@x.de", "s3cret")
    monkeypatch.setattr(c._http, "request", lambda *a, **k: httpx.Response(503, request=httpx.Request("GET", "https://api.divessi.com/app/a21.php?p=s3cret")))
    with pytest.raises(APIError) as e:
        c.authenticate()
    assert "s3cret" not in str(e.value) and "503" in str(e.value)

    def boom(*a, **k):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", "https://api.divessi.com/?p=s3cret"))
    monkeypatch.setattr(c._http, "request", boom)
    with pytest.raises(APIError) as e:
        c.authenticate()
    assert "s3cret" not in str(e.value) and "ConnectError" in str(e.value)


def test_site_cache_survives_failed_refresh(tmp_path, monkeypatch):
    import os
    import time

    from divebridge.ssi.sites import SiteIndex

    f = tmp_path / "ssi-sites.json"
    f.write_text(json.dumps({"divesites": [{"odin_dive_sites_id": 1, "odin_dive_sites_name": "Old Site"}]}))
    old = time.time() - 30 * 24 * 3600
    os.utime(f, (old, old))

    class Dead:
        def download_sites_zip(self):
            raise RuntimeError("offline")
    idx = SiteIndex(tmp_path, Dead())
    assert [m.name for m in idx.search("old")] == ["Old Site"]
    with pytest.raises(RuntimeError):
        idx.ensure(force=True)


def test_resample_matches_sample_grid(sample_dives):
    from divebridge.ssi.payload import resample

    from divebridge.ssi.payload import FLAG_SURFACED

    s = resample(sample_dives[0])
    # demo dive ends at 1318 s / 1.0 m (= surface threshold): last point is the last sample, no extra point
    assert len(s) == 265 and s[0]["d"] == 2.8 and s[-1]["t"] == 1318000
    assert s[-1]["d"] == 1.0 and s[-1]["mf"] & FLAG_SURFACED
    assert all(x["te"] != 0 for x in s)


def test_upload_not_stored_is_an_error(sample_dives):
    """SSI may answer save_divelog with a success stub and store nothing (seen 2026-10-07)."""
    from divebridge.exporters.ssi import push_dives

    class StubClient:
        def get_divelog(self):
            return {"logbook_details": []}   # never contains the dive

        def save_divelog(self, payload):
            return {"success": {"ok": "added to Log", "error": "", "temp_id": "", "odin_user_log_id": 999909158}}

    res = push_dives(StubClient(), sample_dives, {}, dry_run=False)
    assert res[0].status == "error"
    assert "NOT in the logbook" in res[0].message and "added to Log" in res[0].message


def test_upload_stored_is_ok(sample_dives):
    from divebridge.exporters.ssi import push_dives
    from divebridge.ssi.payload import build_payload

    class GoodClient:
        def __init__(self): self.stored = []
        def get_divelog(self):
            return {"logbook_details": self.stored}
        def save_divelog(self, payload):
            self.stored.append(dict(payload, odin_user_log_date=payload["odin_user_log_date"]))
            return dict(payload)

    res = push_dives(GoodClient(), sample_dives, {}, dry_run=False)
    assert res[0].status == "uploaded" and "read back" in res[0].message


def test_client_uses_app_user_agent():
    """SSI stores writes only with the MySSI app's (Dart) User-Agent since 2026-10-07."""
    from divebridge.ssi.client import USER_AGENT, SsiClient

    c = SsiClient("a@b.c", "x")
    assert c._http.headers["user-agent"] == USER_AGENT == "Dart/3.12 (dart:io)"
