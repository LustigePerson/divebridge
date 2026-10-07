from divebridge.importers import detect, parse_file
from divebridge.importers.base import ImportError_
import pytest


def test_detect(sample_bytes):
    imp = detect("whatever.xlsx", sample_bytes)
    assert imp is not None and imp.name == "cressi_divesync"
    assert detect("x.xlsx", b"not a zip") is None


def test_parse_summary(sample_dives):
    assert len(sample_dives) == 1
    d = sample_dives[0]
    assert d.number == 1
    assert d.start.isoformat() == "2025-10-15T02:56:07"
    assert d.duration_s == 1319
    assert abs(d.max_depth_m - 38.09) < 0.01
    assert abs(d.avg_depth_m - 19.23) < 0.01
    assert d.water_temp_min_c == 20.7
    assert d.water_temp_max_c == 23.9
    assert d.site.name == "Monterey"
    assert d.computer.manufacturer == "XS Scuba"
    assert d.computer.model == "Skiff"
    assert d.computer.serial == "000002"
    assert d.primary_gas.is_air
    assert d.tanks == []  # 65535 sentinel = no transmitter
    assert d.gf_low == 89 and d.gf_high == 89
    assert d.surface_interval_s == 445
    assert d.source.dive_id == "8"


def test_parse_profile(sample_dives):
    d = sample_dives[0]
    assert len(d.samples) == 634
    first, last = d.samples[0], d.samples[-1]
    assert first.t_s == 0 and first.depth_m == 2.8 and first.temp_c == 23.9
    assert last.t_s == 1318
    assert max(s.depth_m for s in d.samples) == 38.0
    assert all(s.pressure_bar is None for s in d.samples)
    assert all(s.gas_index == 0 for s in d.samples)
    # uint16 wrap-around of speed must give negative values somewhere (descending)
    assert any(s.speed_m_min is not None and s.speed_m_min < 0 for s in d.samples)
    assert d.samples == sorted(d.samples, key=lambda s: s.t_s)


def test_bad_file():
    with pytest.raises(ImportError_):
        parse_file("x.xlsx", b"PK\x03\x04garbage")


def test_parse_other_exports():
    from pathlib import Path

    d = Path(__file__).parent / "data" / "cressi"
    got = {}
    for f in sorted(d.glob("SKIFF_*.xlsx")):
        dives = parse_file(f.name, f.read_bytes())
        assert len(dives) == 1
        got[f.name] = dives[0]
    catalina = got["SKIFF_000002_10_15_2025_041216.xlsx"]
    assert catalina.site.name == "Catalina Island" and catalina.number == 2
    assert catalina.duration_s == 1354 and abs(catalina.max_depth_m - 27.7) < 0.1
    assert catalina.surface_interval_s == 3250 and len(catalina.samples) == 653
    san_diego = got["SKIFF_000002_10_15_2025_100612.xlsx"]
    assert san_diego.site.name == "San Diego" and san_diego.number == 3
    assert len(san_diego.samples) == 402 and san_diego.water_temp_min_c == 21.0
    # one physical computer, three distinct dive refs
    assert len({d.computer.ref for d in got.values()}) == 1
    assert len({d.dive_ref for d in got.values()}) == 3


def test_real_da_vinci_pool_dive():
    """First real export (pool, 2026-10-07): DateFormat=1 but MM/DD/YYYY, no site ("---"),
    tank pressures 0.0 = not entered, device DAVINCI."""
    from pathlib import Path

    f = Path(__file__).parent / "data" / "cressi" / "DAVINCI_002001_10_07_2026_135139.xlsx"
    d = parse_file(f.name, f.read_bytes())[0]
    assert d.start.isoformat() == "2026-10-07T13:51:39"  # not 10 July
    assert d.computer.manufacturer == "Cressi" and d.computer.model == "Da Vinci" and d.computer.serial == "002001"
    assert d.site is None
    assert d.tanks == [] and d.start_pressure_bar is None
    assert d.duration_s == 887 and len(d.samples) == 6 and d.samples[-1].t_s == 346
    assert d.gf_low == 34 and d.gf_high == 84
    assert d.surface_interval_s == 4929
