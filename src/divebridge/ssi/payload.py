"""Build the `save_divelog` payload (CreateDive) for a canonical Dive.

Field list and semantics ported from agrippa1994/divessi-log-importer
(src/lib/integrations/ssi/create-dive.ts, suunto/converter.ts – MIT). SSI expects the full
object; unknown/unused fields are sent as null exactly like the MySSI app does.
"""

from __future__ import annotations

import json
from typing import Any

from ..model import Dive, Sample
from ..units import bar_to_psi, c_to_f, m_to_ft

SAMPLE_INTERVAL_S = 5

# DivePhaseFlag bitmask for `mf`
FLAG_DIVE = 0x08000000
FLAG_AT_DEPTH = 0x00010000
FLAG_SAFETY_STOP = 0x00020000
FLAG_SURFACED = 0x04000000

# default "variable" ids observed in the MySSI app (fun dive, salt water, steel tank)
VAR_DIVETYPE_FUN = 24
VAR_WATERTYPE_SALT = 4
VAR_TANKTYPE_STEEL = 19
VAR_TANKTYPE_ALU = 20
FRD_DIVETYPE_DEFAULT = 50


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None else round(v, nd)


def _interp(samples: list[Sample], t: float) -> tuple[float, Sample]:
    """Linear depth interpolation at time t; returns (depth, nearest-or-previous sample)."""
    prev = samples[0]
    for s in samples:
        if s.t_s == t:
            return s.depth_m, s
        if s.t_s > t:
            if s.t_s == prev.t_s:
                return s.depth_m, s
            f = (t - prev.t_s) / (s.t_s - prev.t_s)
            d = prev.depth_m + f * (s.depth_m - prev.depth_m)
            return d, (s if f > 0.5 else prev)
        prev = s
    return prev.depth_m, prev


def resample(dive: Dive, interval_s: int = SAMPLE_INTERVAL_S) -> list[dict[str, Any]]:
    """Fixed-interval samples in the SSI `diveSamples` shape."""
    src = dive.samples
    if not src:
        return []
    temps = [s for s in src if s.temp_c is not None]
    out: list[dict[str, Any]] = []
    t_end = max(dive.duration_s, int(src[-1].t_s))
    at_depth = False
    n = 1
    for t in range(0, t_end + 1, interval_s):
        depth, near = _interp(src, float(t))
        depth = round(depth, 2)
        # temperature: nearest sample that has one
        temp = near.temp_c
        if temp is None and temps:
            temp = min(temps, key=lambda s: abs(s.t_s - t)).temp_c
        ndl = near.ndl_min if near.ndl_min is not None else 99
        ndl = min(max(ndl, 0), 99)
        if depth >= 8.5:
            at_depth = True
        elif depth < 6.0:
            at_depth = False
        mf = FLAG_DIVE
        if at_depth:
            mf |= FLAG_AT_DEPTH
        if depth <= 1.0:
            mf |= FLAG_SURFACED
        sample: dict[str, Any] = {
            "a": 0,
            "d": depth,
            "dr": False,
            "gs": 0,
            "mf": mf,
            "n": n,
            "ndl": round(ndl, 1) if isinstance(ndl, float) else ndl,
            "o": False,
            "s": 0,
            "t": t * 1000,
            "te": round(temp, 2) if temp is not None else 0,
        }
        if near.pressure_bar is not None:
            sample["pressure"] = round(near.pressure_bar, 2)
        out.append(sample)
        n += 1
    return out


def build_payload(dive: Dive, log_nr: int, site_id: int | None,
                  divetype_id: int = VAR_DIVETYPE_FUN, watertype_id: int = VAR_WATERTYPE_SALT,
                  tanktype_id: int | None = VAR_TANKTYPE_STEEL) -> dict[str, Any]:
    samples = resample(dive)
    dt = dive.start
    date_str = f"{dt:%Y-%m-%d}"
    entry_time = f"{dt:%H:%M}"
    datetime_str = f"{date_str}+{dt:%H:%M:%S}.{dt.microsecond // 1000:03d}"

    temps = [s["te"] for s in samples if s["te"] != 0]
    wt_min = dive.water_temp_min_c if dive.water_temp_min_c is not None else (min(temps) if temps else None)
    wt_max = dive.water_temp_max_c if dive.water_temp_max_c is not None else (max(temps) if temps else None)

    p_start = dive.start_pressure_bar
    p_end = dive.end_pressure_bar
    has_pressure = any("pressure" in s for s in samples)
    tank_pressure_ds = json.dumps([s.get("pressure") for s in samples]) if has_pressure else None

    comp = dive.computer
    device_name = comp.display_name if comp else "Unknown dive computer"
    gas = dive.primary_gas
    ean = None if gas.is_air else 1
    tank_vol = next((t.volume_l for t in dive.tanks if t.volume_l), None)
    site = dive.site

    avg = dive.avg_depth_m if dive.avg_depth_m is not None else (
        round(sum(s["d"] for s in samples) / len(samples), 2) if samples else dive.max_depth_m)

    payload: dict[str, Any] = {
        # --- bookkeeping ---
        "odin_user_log_id": None,
        "odin_user_log_nr": log_nr,
        "localSiteId": None,
        "localBuddyIds": [],
        "odin_user_log_crdate": None,
        "reset_profile_divelog_number_with_deletion": None,
        "needsUpload": True,
        "needsVerificationUpload": None,
        "needsUnverifyUpload": None,
        "uploadError": None,
        # --- core ---
        "odin_user_log_datetime": datetime_str,
        "odin_user_log_depth_m": _r(dive.max_depth_m),
        "odin_user_log_depth_ft": _r(m_to_ft(dive.max_depth_m)),
        "odin_user_log_avg_depth_m": _r(avg),
        "odin_user_log_avg_depth_ft": _r(m_to_ft(avg)),
        "odin_user_log_divetime": dive.duration_min,
        "odin_user_log_dive_type": 0,
        "odin_user_log_rating": None,
        "odin_user_log_airtemp_c": None,
        "odin_user_log_airtemp_f": None,
        "odin_user_log_watertemp_c": _r(wt_min),
        "odin_user_log_watertemp_f": _r(c_to_f(wt_min)) if wt_min is not None else None,
        "odin_user_log_watertemp_max_c": _r(wt_max),
        "odin_user_log_watertemp_max_f": _r(c_to_f(wt_max)) if wt_max is not None else None,
        # --- pressure ---
        "odin_user_log_pressure_start_bar": _r(p_start),
        "odin_user_log_pressure_start_psi": round(bar_to_psi(p_start)) if p_start else None,
        "odin_user_log_pressure_end_bar": _r(p_end),
        "odin_user_log_pressure_end_psi": round(bar_to_psi(p_end)) if p_end else None,
        # --- site, buddies, gear ---
        "odin_user_log_dive_sites_id": site_id,
        "odin_user_log_buddy_ids": [],
        "odin_user_log_animal_ids": [],
        "odin_user_log_gear": [],
        "odin_user_log_user_master_id": None,
        "odin_user_log_leader_nr": None,
        "odin_user_log_comment": dive.notes,
        "odin_user_log_deleted": False,
        # --- date/time ---
        "odin_user_log_date": date_str,
        "odin_user_log_entry_time": entry_time,
        # --- variables ---
        "odin_user_log_var_divetype_id": divetype_id,
        "odin_user_log_var_water_body_id": None,
        "odin_user_log_var_watertype_id": watertype_id,
        "odin_user_log_var_entry_id": None,
        "odin_user_log_var_current_id": None,
        "odin_user_log_var_surface_id": None,
        "odin_user_log_var_weather_id": None,
        "odin_user_log_var_tanktype_id": tanktype_id,
        "odin_user_log_vis_m": None,
        "odin_user_log_vis_ft": None,
        "odin_user_log_weight_kg": None,
        "odin_user_log_weight_lb": None,
        "odin_user_log_tank_vol_l": _r(tank_vol, 1),
        "odin_user_log_tank_vol_cuft": None,
        "odin_user_log_ean": ean,
        "odin_user_log_ean_percent": round(gas.o2) if ean else None,
        "odin_user_log_var_specialdive_id": None,
        "odin_user_log_amv_l": None,
        "odin_user_log_amv_psi": None,
        # --- freediving ---
        "odin_user_log_frd_weight_kg": None,
        "odin_user_log_frd_weight_lb": None,
        "odin_user_log_frd_neutral_m": None,
        "odin_user_log_frd_neutral_ft": None,
        "odin_user_log_frd_divetype_id": FRD_DIVETYPE_DEFAULT,
        "odin_user_log_frd_suit": None,
        "odin_user_log_frd_NOTES": None,
        "odin_user_log_frdwater_body_id": None,
        "odin_user_log_frddisc": None,
        # --- confirmation ---
        "odin_user_log_divecenter_confirmed": None,
        "odin_user_log_divecenter_confirmed_id": None,
        "odin_user_log_divecenter_confirmed_name": None,
        "odin_user_log_divecenter_confirmed_logo": None,
        "odin_user_log_leader_confirmed_id": None,
        "odin_user_log_leader_confirmed_name": None,
        "odin_user_log_user_confirmed_id": None,
        "odin_user_log_user_confirmed_name": None,
        "odin_user_log_transferDate": None,
        "odin_user_log_confirmed": None,
        "odin_user_log_verified": None,
        "timestamp": None,
        # --- dive computer ---
        "odin_user_log_diveComputer": device_name,
        "odin_user_log_diveComputerData": None,
        "odin_user_log_divecomputer_id": None,
        "odin_user_log_divecomputer_name": device_name,
        "odin_user_log_divecomputer_serial_nr": comp.serial if comp else None,
        "odin_user_log_divecomputer_ble_id": None,
        "odin_user_log_divecomputer_firmware": (comp.firmware if comp else None) or "",
        "odin_user_log_divecomputer_manufacturer": comp.manufacturer if comp else None,
        "odin_user_log_divecomputer_ref": comp.ref if comp else None,
        "odin_user_log_divecomputer_dive_ref": dive.dive_ref,
        "odin_user_log_divecomputer_imported": False,
        "odin_user_log_divecomputer_raw_data_header": None,
        "odin_user_log_divecomputer_raw_data_details": None,
        "odin_user_log_divecomputer_max_sensor_depth": None,
        "odin_user_log_divecomputer_bottomtimer": None,
        "odin_user_log_divecomputer_productname": None,
        # --- datasets (JSON strings!) ---
        "odin_user_log_depthDataset": json.dumps([s["d"] for s in samples]),
        "odin_user_log_tempDataset": json.dumps([s["te"] for s in samples]),
        "odin_user_log_alarmDataset": None,
        "odin_user_log_gfnowDataset": None,
        "odin_user_log_gfSurfDataset": json.dumps([s["gs"] for s in samples]),
        "odin_user_log_deepestDecoDataset": None,
        "odin_user_log_tankPressureDataset": tank_pressure_ds,
        "odin_user_log_freeDiveSessionCharts": None,
        "odin_user_log_pressureDataset": tank_pressure_ds,
        "odin_user_log_locationDataset": None,
        "odin_user_log_diveSamples": json.dumps(samples, separators=(",", ":")),
        # --- deco ---
        "odin_user_log_si_before": round(dive.surface_interval_s / 60) if dive.surface_interval_s else None,
        "odin_user_log_gf_set": None,
        "odin_user_log_gf_set_1": None,
        "odin_user_log_gf_set_2": None,
        "odin_user_log_gf_end": None,
        "odin_user_log_cns_start": None,
        "odin_user_log_cns_end": None,
        "odin_user_log_otu_start": None,
        "odin_user_log_otu_end": None,
        "odin_user_log_deco_dive": None,
        "odin_user_log_deco_time": None,
        "odin_user_log_deco_gas": None,
        "odin_user_log_deco_gas_tanktype_id": None,
        "odin_user_log_deco_gas_tank_vol_l": None,
        "odin_user_log_deco_gas_tank_vol_cuft": None,
        "odin_user_log_deco_gas_o2": None,
        "odin_user_log_deco_gas_start_bar": None,
        "odin_user_log_deco_gas_end_bar": None,
        "odin_user_log_deco_gas_start_psi": None,
        "odin_user_log_deco_gas_end_psi": None,
        "odin_user_log_alarm_fast_ascent": None,
        "odin_user_log_alarm_deco_stop": None,
        "odin_user_log_alarm_deco_violation": None,
        # --- linked / extended ---
        "log_linked_facility_id": None,
        "log_linked_brevet_rule_id": None,
        "odin_user_log_gearconfiguration_id": None,
        "log_extended_data_cleanup_weight_kg": None,
        "log_extended_data_cleanup_weight_lb": None,
        # --- GPS ---
        "odin_user_log_pos_start_latitude": site.lat if site else None,
        "odin_user_log_pos_start_longitude": site.lon if site else None,
        "odin_user_log_pos_end_latitude": None,
        "odin_user_log_pos_end_longitude": None,
        # --- apple watch / sensors ---
        "odin_user_log_apple_watch": 0,
        "odin_user_log_apple_watch_log_id": None,
        "odin_user_log_apple_watch_id": None,
        "odin_user_log_apple_watch_app_version": None,
        "odin_user_log_apple_watch_os_version": None,
        "odin_user_log_heartRateMin": None,
        "odin_user_log_heartRateMax": None,
        "odin_user_log_heartRateAvg": None,
        "odin_user_log_heartRateDataset": None,
        "odin_user_log_batteryLevelDataset": None,
        "odin_user_log_batteryLevelStart": None,
        "odin_user_log_batteryLevelEnd": None,
        "odin_user_log_accelerationDataset": None,
        "odin_user_log_gyroDataset": None,
        # --- misc ---
        "odin_user_log_dive_on_own_risk": 0,
        "odin_user_log_dive_on_own_risk_os_app": None,
        "odin_user_log_housing_local_dive_media": None,
    }
    # XR / SCR / CCR blocks: all null, generated to keep the payload complete
    for key in _XR_SCR_CCR_KEYS:
        payload.setdefault(key, None)
    return payload


_XR_KEYS = [
    "odin_user_log_xr_divetype_id", "odin_user_log_xr_planned_bottom_time", "odin_user_log_xr_total_deco_time",
    "odin_user_log_xr_planned_depth", "odin_user_log_xr_planned_deco_time", "odin_user_log_xr_back",
    "odin_user_log_xr_back_tanktype_id", "odin_user_log_xr_deco_tanktype_id", "odin_user_log_xr_back_vol_l",
    "odin_user_log_xr_back_vol_cuft", "odin_user_log_xr_back_ean", "odin_user_log_xr_back_tmx",
    "odin_user_log_xr_back_o2", "odin_user_log_xr_back_he", "odin_user_log_xr_back_start_bar",
    "odin_user_log_xr_back_end_bar", "odin_user_log_xr_back_start_psi", "odin_user_log_xr_back_end_psi",
    "odin_user_log_xr_sac_bottom_l", "odin_user_log_xr_sac_bottom_psi", "odin_user_log_xr_sac_deco_l",
    "odin_user_log_xr_sac_deco_psi",
]
for _i in (1, 2, 3):
    _XR_KEYS += [f"odin_user_log_xr_deco{_i}{s}" for s in (
        "", "_tanktype_id", "_vol_l", "_vol_cuft", "_o2", "_he", "_start_bar", "_end_bar", "_start_psi", "_end_psi")]
    _XR_KEYS += [f"odin_user_log_xr_deco{_i}_ean", f"odin_user_log_xr_deco{_i}_tmx"] if _i < 3 else ["odin_user_log_xr_deco3_ean_o2"]

_SCR_KEYS = [
    "odin_user_log_scr_unit_id", "odin_user_log_scr_total_deco_time", "odin_user_log_scr_sac_bailout_l",
    "odin_user_log_scr_sac_bailout_psi", "odin_user_log_scr_sac_deco_l", "odin_user_log_scr_sac_deco_psi",
    "odin_user_log_scr_bottom_tanktype_id", "odin_user_log_scr_bottom_tank_vol_l", "odin_user_log_scr_bottom_tank_vol_cuft",
    "odin_user_log_scr_bottom_o2", "odin_user_log_scr_bottom_setpoint", "odin_user_log_scr_bottom_start_bar",
    "odin_user_log_scr_bottom_start_psi", "odin_user_log_scr_bottom_end_bar", "odin_user_log_scr_bottom_end_psi",
    "odin_user_log_scr_deco", "odin_user_log_scr_deco_tanktype_id", "odin_user_log_scr_deco_tank_vol_l",
    "odin_user_log_scr_deco_tank_vol_cuft", "odin_user_log_scr_deco_o2", "odin_user_log_scr_deco_setpoint",
    "odin_user_log_scr_deco_start_bar", "odin_user_log_scr_deco_start_psi", "odin_user_log_scr_deco_end_bar",
    "odin_user_log_scr_deco_end_psi", "odin_user_log_scr_start_time", "odin_user_log_scr_end_time", "odin_user_log_scr_oc",
]

_CCR_KEYS = [
    "odin_user_log_ccr_unit_id", "odin_user_log_ccr_total_deco_time", "odin_user_log_ccr_sac_bailout_l",
    "odin_user_log_ccr_sac_bailout_psi", "odin_user_log_ccr_sac_deco_l", "odin_user_log_ccr_sac_deco_psi",
    "odin_user_log_ccr_bottom_tank_vol_cuft",
    "odin_user_log_ccr_diluent_gas", "odin_user_log_ccr_diluent_tanktype_id", "odin_user_log_ccr_diluent_tank_vol_l",
    "odin_user_log_ccr_diluent_tank_vol_cuft", "odin_user_log_ccr_diluent_o2", "odin_user_log_ccr_diluent_he",
    "odin_user_log_ccr_diluent_start_bar", "odin_user_log_ccr_diluent_start_psi", "odin_user_log_ccr_diluent_end_bar",
    "odin_user_log_ccr_diluent_end_psi", "odin_user_log_ccr_o2_tanktype_id", "odin_user_log_ccr_o2_tank_vol_l",
    "odin_user_log_ccr_o2_tank_vol_cuft", "odin_user_log_ccr_o2_start_bar", "odin_user_log_ccr_o2_start_psi",
    "odin_user_log_ccr_o2_end_bar", "odin_user_log_ccr_o2_end_psi",
]
for _i in ("01", "02", "03"):
    _CCR_KEYS += [f"odin_user_log_ccr_bailout{_i}{s}" for s in (
        "", "_tanktype_id", "_tank_vol_l", "_tank_vol_cuft", "_o2", "_he", "_start_bar", "_start_psi", "_end_bar", "_end_psi")]

_FRD_KEYS = [
    "odin_user_log_frddisc_STA", "odin_user_log_frddisc_STA_WU", "odin_user_log_frddisc_STA_MAX", "odin_user_log_frddisc_STA_CT",
    "odin_user_log_frddisc_STATT", "odin_user_log_frddisc_STATT_RP", "odin_user_log_frddisc_STATT_MAX",
    "odin_user_log_frddisc_WAPN", "odin_user_log_frddisc_WAPN_WU", "odin_user_log_frddisc_WAPN_RP", "odin_user_log_frddisc_WAPN_MAX",
    "odin_user_log_frddisc_DYN", "odin_user_log_frddisc_DYN_WU", "odin_user_log_frddisc_DYN_MAX_m", "odin_user_log_frddisc_DYN_MAX_ft",
    "odin_user_log_frddisc_DYNTT", "odin_user_log_frddisc_DYNTT_RP", "odin_user_log_frddisc_DYNTT_MAX_m", "odin_user_log_frddisc_DYNTT_MAX_ft",
    "odin_user_log_frddisc_FRC", "odin_user_log_frddisc_FRC_RP", "odin_user_log_frddisc_FRC_MAX_m", "odin_user_log_frddisc_FRC_MAX_ft",
    "odin_user_log_frddisc_DNF", "odin_user_log_frddisc_DNF_WU", "odin_user_log_frddisc_DNF_MAX_m", "odin_user_log_frddisc_DNF_MAX_ft",
]
for _d in ("FIM", "CWT", "CNF", "VWT"):
    _FRD_KEYS += [f"odin_user_log_frddisc_{_d}{s}" for s in ("", "_WU", "_MAX_m", "_MAX_ft", "_TIME")]

_XR_SCR_CCR_KEYS = _XR_KEYS + _SCR_KEYS + _CCR_KEYS + _FRD_KEYS
