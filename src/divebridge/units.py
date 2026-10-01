"""Unit conversions and sentinel handling. Canonical model is metric."""

from __future__ import annotations

import math

FT_PER_M = 3.28084
PSI_PER_BAR = 14.5038
KELVIN_OFFSET = 273.15

# Cressi/DiveSync writes 0xFFFF for "no value" (e.g. tank pressure without transmitter)
SENTINEL_U16 = 65535


def ft_to_m(ft: float) -> float:
    return ft / FT_PER_M


def m_to_ft(m: float) -> float:
    return m * FT_PER_M


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def c_to_k(c: float) -> float:
    return c + KELVIN_OFFSET


def psi_to_bar(psi: float) -> float:
    return psi / PSI_PER_BAR


def bar_to_psi(bar: float) -> float:
    return bar * PSI_PER_BAR


def bar_to_pa(bar: float) -> float:
    return bar * 100_000.0


def to_float(value: object) -> float | None:
    """Parse a spreadsheet cell into a float; '', None, 'NaN' and non-numbers become None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        f = float(value)
        return None if math.isnan(f) else f
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return None if math.isnan(f) else f


def to_int(value: object) -> int | None:
    f = to_float(value)
    return None if f is None else int(f)


def u16_or_none(value: object) -> float | None:
    """Float value, but the 0xFFFF sentinel becomes None."""
    f = to_float(value)
    if f is None or int(f) == SENTINEL_U16:
        return None
    return f


def u16_signed(value: object) -> float | None:
    """Interpret a uint16 cell as a signed int16 (DiveSync stores negative speeds wrapped)."""
    f = to_float(value)
    if f is None:
        return None
    i = int(f)
    return float(i - 65536) if i > 32767 else float(i)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
