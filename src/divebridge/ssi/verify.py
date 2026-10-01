"""Read a dive back from the SSI logbook and compare it with what we sent (round-trip check)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# (label, payload key, logbook key) – keys differ in a few places between upload and download
FIELDS: list[tuple[str, str, str]] = [
    ("log nr", "odin_user_log_nr", "odin_user_log_nr"),
    ("date", "odin_user_log_date", "odin_user_log_date"),
    ("entry time", "odin_user_log_entry_time", "odin_user_log_entry_time"),
    ("dive time (min)", "odin_user_log_divetime", "odin_user_log_divetime"),
    ("max depth (m)", "odin_user_log_depth_m", "odin_user_log_depth_m"),
    ("avg depth (m)", "odin_user_log_avg_depth_m", "odin_user_log_avg_depth_m"),
    ("water temp min (°C)", "odin_user_log_watertemp_c", "odin_user_log_watertemp_c"),
    ("water temp max (°C)", "odin_user_log_watertemp_max_c", "odin_user_log_watertemp_max_c"),
    ("surface interval", "odin_user_log_si_before", "odin_user_log_si_before"),
    ("site id", "odin_user_log_dive_sites_id", "odin_user_log_dive_sites_id"),
    ("dive type id", "odin_user_log_var_divetype_id", "odin_user_log_var_divetype_id"),
    ("water type id", "odin_user_log_var_watertype_id", "odin_user_log_var_watertype_id"),
    ("tank type id", "odin_user_log_var_tanktype_id", "odin_user_log_var_tanktype_id"),
    ("entry id", "odin_user_log_var_entry_id", "odin_user_log_var_entry_id"),
    ("body of water id", "odin_user_log_var_water_body_id", "odin_user_log_var_water_body_id"),
    ("weather id", "odin_user_log_var_weather_id", "odin_user_log_var_weather_id"),
    ("surface id", "odin_user_log_var_surface_id", "odin_user_log_var_surface_id"),
    ("current id", "odin_user_log_var_current_id", "odin_user_log_var_current_id"),
    ("special dive ids", "odin_user_log_var_specialdive_id", "odin_user_log_var_specialdive_id"),
    ("tank volume (l)", "odin_user_log_tank_vol_l", "odin_user_log_tank_vol_l"),
    ("pressure start (bar)", "odin_user_log_pressure_start_bar", "odin_user_log_pressure_start_bar"),
    ("pressure end (bar)", "odin_user_log_pressure_end_bar", "odin_user_log_pressure_end_bar"),
    ("EAN %", "odin_user_log_ean_percent", "odin_user_log_ean_percent"),
    ("weight (kg)", "odin_user_log_weight_kg", "odin_user_log_weight_kg"),
    ("visibility (m)", "odin_user_log_vis_m", "odin_user_log_vis_m"),
    ("air temp (°C)", "odin_user_log_airtemp_c", "odin_user_log_airtemp_c"),
    ("buddies", "odin_user_log_buddy_ids", "odin_user_log_buddy_ids"),
    ("notes", "odin_user_log_comment", "odin_user_log_comment"),
    ("GF set", "odin_user_log_gf_set", "odin_user_log_gf_set"),
    ("deco dive", "odin_user_log_deco_dive", "odin_user_log_deco_dive"),
    ("computer", "odin_user_log_divecomputer_name", "odin_user_log_divecomputer_name"),
    ("computer serial", "odin_user_log_divecomputer_serial_nr", "odin_user_log_divecomputer_serial_nr"),
    ("computer dive ref", "odin_user_log_divecomputer_dive_ref", "odin_user_log_divecomputer_dive_ref"),
    ("datetime", "odin_user_log_datetime", "odin_user_log_datetime"),
]
DATASETS = ["odin_user_log_depthDataset", "odin_user_log_tempDataset", "odin_user_log_diveSamples"]


@dataclass
class FieldDiff:
    label: str
    sent: Any
    stored: Any
    ok: bool


def _norm(v: Any) -> Any:
    if v in ("", None):
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        try:
            return float(v) if "." in v or v.lstrip("-").isdigit() else v.strip()
        except ValueError:
            return v.strip()
    if isinstance(v, (int, float)):
        return float(v)
    return v


def compare(payload: dict[str, Any], stored: dict[str, Any]) -> list[FieldDiff]:
    out: list[FieldDiff] = []
    for label, pk, lk in FIELDS:
        sent, got = payload.get(pk), stored.get(lk)
        if pk == "odin_user_log_datetime" and isinstance(sent, str) and isinstance(got, str):
            # sent "2025-10-15+02:56:07.000", stored "2025-10-15 02:56" – SSI keeps minute precision
            sent, got = sent.replace("+", " ")[:16], got[:16]
        a, b = _norm(sent), _norm(got)
        ok = a == b or (isinstance(a, float) and isinstance(b, float) and abs(a - b) < 0.06)
        if a is None and b in (0.0, [], ""):  # SSI stores "unset" as 0 / empty
            ok = True
        out.append(FieldDiff(label, sent, got, ok))
    for key in DATASETS:
        sent, got = payload.get(key), stored.get(key)
        ls = len(sent) if isinstance(sent, str) else 0
        lg = len(got) if isinstance(got, str) else 0
        out.append(FieldDiff(key.replace("odin_user_log_", "") + " (chars)", ls, lg, ls == lg or (lg > 0 and ls > 0)))
    return out


def summarize(diffs: list[FieldDiff]) -> str:
    bad = [d for d in diffs if not d.ok]
    return "all fields stored as sent" if not bad else "differs: " + ", ".join(d.label for d in bad)
