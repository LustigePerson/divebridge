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
    assert p["odin_user_log_divecomputer_manufacturer"] == "XS Scuba"
    assert p["odin_user_log_divecomputer_name"] == "XS Scuba Skiff"
    assert p["odin_user_log_diveComputer"] == ""  # shown as partner/center text by the app
    assert p["odin_user_log_divecomputer_imported"] is True  # app shows computer icon + field
    assert p["odin_user_log_divecomputer_ref"] == "XS Scuba Skiff_000002"
    assert p["odin_user_log_divecomputer_dive_ref"] == "2025-10-15T02:56:07"
    assert p["odin_user_log_tankPressureDataset"] is None
    assert p["odin_user_log_si_before"] == 445  # seconds
    assert p["odin_user_log_var_watertype_id"] is None  # "auto" without a site -> null, never a wrong id
    assert p["odin_user_log_var_divetype_id"] == 24 and p["odin_user_log_var_tanktype_id"] == 19
    depths = json.loads(p["odin_user_log_depthDataset"])
    samples = json.loads(p["odin_user_log_diveSamples"])
    assert len(depths) == len(samples) == 265
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

    defaults = DiveOptions(tanktype_id=20, tank_volume_l=12, weight_kg=6, buddy_ids=[42], notes="boat dive",
                           specialdive_ids=[40, 47])
    override = DiveOptions(divetype_id=None, tanktype_id=None, weight_kg=8)
    merged = defaults.merged(override)
    assert merged.weight_kg == 8 and merged.tank_volume_l == 12 and merged.tanktype_id == 20
    assert merged.divetype_id == 24
    assert DiveOptions(mark_imported=True).merged(DiveOptions(mark_imported=False)).mark_imported is False
    p = build_payload(sample_dives[0], log_nr=1, site_id=None, options=merged)
    assert p["odin_user_log_var_tanktype_id"] == 20
    assert p["odin_user_log_tank_vol_l"] == 12
    assert p["odin_user_log_weight_kg"] == 8 and p["odin_user_log_weight_lb"] == 17.6
    assert p["odin_user_log_buddy_ids"] == [42]
    assert p["odin_user_log_comment"] == "boat dive"
    assert p["odin_user_log_var_specialdive_id"] == "40,47"
    assert p["odin_user_log_gf_set"] == "89 / 89" and p["odin_user_log_gf_set_1"] == 89
    assert p["odin_user_log_deco_dive"] is None
    assert set(p) == REF_KEYS


def test_watertype_auto_from_site(sample_dives):
    from divebridge.ssi.payload import DiveOptions

    o = DiveOptions()
    o.resolve_watertype("salt")
    assert build_payload(sample_dives[0], 1, 5, options=o)["odin_user_log_var_watertype_id"] == 5
    o = DiveOptions(watertype_id=4)
    o.resolve_watertype("salt")  # explicit choice wins
    assert build_payload(sample_dives[0], 1, 5, options=o)["odin_user_log_var_watertype_id"] == 4


def test_bundled_vars():
    from divebridge.ssi.vars import VarIndex, bundled_vars

    t = bundled_vars()
    assert t["watertype"] == {4: "fresh", 5: "salt"}
    assert t["entry"][21] == "shore" and t["divetype"][23] == "education"
    idx = VarIndex()  # offline -> bundled copy
    assert ("boat", ) == tuple(n for i, n in idx.options("entry") if i == 22)


def test_resample_ends_at_last_sample_with_surface_point():
    from pathlib import Path

    from divebridge.importers import parse_file
    from divebridge.ssi.payload import FLAG_SURFACED, resample

    f = Path(__file__).parent / "data" / "cressi" / "DAVINCI_002001_10_07_2026_135139.xlsx"
    d = parse_file(f.name, f.read_bytes())[0]
    s = resample(d)
    assert d.duration_s == 887 and s[-2]["t"] == 346000 and s[-1]["t"] == 351000
    assert s[-2]["d"] == 2.5 and s[-1]["d"] == 0.0 and s[-1]["mf"] & FLAG_SURFACED
    p = build_payload(d, 1, None)
    assert p["odin_user_log_divetime"] == 14.8 and p["odin_user_log_divecomputer_name"] == "Cressi Da Vinci"


def test_unknown_device_name_kept_as_is():
    from divebridge.importers.cressi_divesync import CressiDiveSyncImporter

    row = {"DiveID": 1, "DiveStartLocalTime": "10/15/2025 02:56:07", "TotalDiveTime": 60, "MaxDepthFT": 10,
           "DeviceName": "GRAVITON", "SerialNo": "7", "StartingMixIdx": 1, "Mix1Fo2Percent": 21}
    d = CressiDiveSyncImporter()._dive("f.xlsx", row, [], [], {})
    assert d.computer.display_name == "GRAVITON" and d.computer.manufacturer == ""
    assert build_payload(d, 1, None)["odin_user_log_divecomputer_manufacturer"] is None
