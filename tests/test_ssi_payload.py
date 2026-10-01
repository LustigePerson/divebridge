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
    assert p["odin_user_log_si_before"] == 445  # seconds
    assert p["odin_user_log_var_watertype_id"] is None  # "auto" without a site -> null, never a wrong id
    assert p["odin_user_log_var_divetype_id"] == 24 and p["odin_user_log_var_tanktype_id"] == 19
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


def test_options_merge_and_payload(sample_dives):
    from divebridge.ssi.payload import DiveOptions

    defaults = DiveOptions(tanktype="alu", tank_volume_l=12, weight_kg=6, buddy_ids=[42], notes="boat dive")
    override = DiveOptions(divetype="", watertype="", tanktype="", weight_kg=8)
    merged = defaults.merged(override)
    assert merged.weight_kg == 8 and merged.tank_volume_l == 12 and merged.tanktype == "alu"
    p = build_payload(sample_dives[0], log_nr=1, site_id=None, options=merged)
    assert p["odin_user_log_var_tanktype_id"] == 20
    assert p["odin_user_log_tank_vol_l"] == 12
    assert p["odin_user_log_weight_kg"] == 8 and p["odin_user_log_weight_lb"] == 17.6
    assert p["odin_user_log_buddy_ids"] == [42]
    assert p["odin_user_log_comment"] == "boat dive"
    assert p["odin_user_log_gf_set"] == "89 / 89" and p["odin_user_log_gf_set_1"] == 89
    assert p["odin_user_log_deco_dive"] is None
    assert set(p) == REF_KEYS


def test_watertype_auto_from_site(sample_dives):
    from divebridge.ssi.payload import DiveOptions

    o = DiveOptions()
    o.resolve_watertype("salt")
    assert build_payload(sample_dives[0], 1, 5, options=o)["odin_user_log_var_watertype_id"] == 5
    o = DiveOptions(watertype="fresh")
    o.resolve_watertype("salt")  # explicit choice wins
    assert build_payload(sample_dives[0], 1, 5, options=o)["odin_user_log_var_watertype_id"] == 4
