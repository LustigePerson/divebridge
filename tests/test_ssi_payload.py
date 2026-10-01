import json
from pathlib import Path

from divebridge.ssi.payload import FLAG_AT_DEPTH, FLAG_DIVE, FLAG_SURFACED, build_payload, resample

REF_KEYS = set((Path(__file__).parent / "data" / "create_dive_keys.txt").read_text().split())


def test_payload_has_all_reference_keys(sample_dives):
    p = build_payload(sample_dives[0], log_nr=42, site_id=123)
    missing = REF_KEYS - set(p)
    extra = set(p) - REF_KEYS
    assert not missing, f"missing: {sorted(missing)}"
    assert not extra, f"extra: {sorted(extra)}"
    json.dumps(p)  # must be serialisable


def test_payload_values(sample_dives):
    p = build_payload(sample_dives[0], log_nr=42, site_id=123)
    assert p["odin_user_log_nr"] == 42
    assert p["odin_user_log_dive_sites_id"] == 123
    assert p["odin_user_log_id"] is None and p["needsUpload"] is True
    assert p["odin_user_log_datetime"] == "2025-10-15+02:56:07.000"
    assert p["odin_user_log_date"] == "2025-10-15"
    assert p["odin_user_log_entry_time"] == "02:56"
    assert p["odin_user_log_divetime"] == 22.0
    assert p["odin_user_log_depth_m"] == 38.09
    assert p["odin_user_log_depth_ft"] == 124.97
    assert p["odin_user_log_watertemp_c"] == 20.7
    assert p["odin_user_log_watertemp_max_c"] == 23.9
    assert p["odin_user_log_ean"] is None
    assert p["odin_user_log_divecomputer_manufacturer"] == "Cressi"
    assert p["odin_user_log_divecomputer_ref"] == "Cressi Da Vinci_000002"
    assert p["odin_user_log_divecomputer_dive_ref"] == "2025-10-15T02:56:07"
    assert p["odin_user_log_tankPressureDataset"] is None
    depths = json.loads(p["odin_user_log_depthDataset"])
    samples = json.loads(p["odin_user_log_diveSamples"])
    assert len(depths) == len(samples) == 264
    assert samples[0]["t"] == 0 and samples[1]["t"] == 5000
    assert set(samples[0]) == {"a", "d", "dr", "gs", "mf", "n", "ndl", "o", "s", "t", "te"}
    assert max(s["d"] for s in samples) == 38.0


def test_resample_flags(sample_dives):
    s = resample(sample_dives[0])
    deep = next(x for x in s if x["d"] > 20)
    assert deep["mf"] & FLAG_DIVE and deep["mf"] & FLAG_AT_DEPTH
    assert all(x["ndl"] <= 99 for x in s)
    shallow = [x for x in s if x["d"] <= 1.0]
    assert all(x["mf"] & FLAG_SURFACED for x in shallow)
