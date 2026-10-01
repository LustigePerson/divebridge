"""UDDF 3.2 writer (Universal Dive Data Format, http://www.streit.cc/extern/uddf_v321/en/).

UDDF units: metres, seconds, Kelvin, Pascal, cubic metres. Readers: Subsurface, divelogs.de, MacDive, ...
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .. import __version__
from ..model import Dive, Gas
from ..units import bar_to_pa, c_to_k

UDDF_NS = "http://www.streit.cc/uddf/3.2/"
UDDF_VERSION = "3.2.3"


def _sub(parent: ET.Element, tag: str, text: object = None, **attrs: str) -> ET.Element:
    el = ET.SubElement(parent, tag, attrs)
    if text is not None:
        el.text = str(text)
    return el


def _gas_id(g: Gas) -> str:
    return f"mix_o2_{g.o2:g}_he_{g.he:g}".replace(".", "_")


def dives_to_uddf(dives: list[Dive], owner_name: str | None = None) -> bytes:
    ET.register_namespace("", UDDF_NS)
    root = ET.Element(f"{{{UDDF_NS}}}uddf", {"version": UDDF_VERSION})

    gen = _sub(root, "generator")
    _sub(gen, "name", "divebridge")
    _sub(gen, "version", __version__)
    _sub(gen, "datetime", datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    _sub(gen, "type", "logbook")

    # diver / owner / dive computers
    diver = _sub(root, "diver")
    owner = _sub(diver, "owner", id="owner")
    personal = _sub(owner, "personal")
    if owner_name:
        _sub(personal, "firstname", owner_name)
    equipment = _sub(owner, "equipment")
    computers: dict[str, str] = {}
    for d in dives:
        if d.computer and d.computer.ref not in computers:
            cid = f"dc_{len(computers) + 1}"
            computers[d.computer.ref] = cid
            dc = _sub(equipment, "divecomputer", id=cid)
            _sub(dc, "name", d.computer.display_name)
            _sub(dc, "model", d.computer.model)
            man = _sub(dc, "manufacturer")
            _sub(man, "name", d.computer.manufacturer)
            if d.computer.serial:
                _sub(dc, "serialnumber", d.computer.serial)

    # dive sites
    sites: dict[str, str] = {}
    divesite = _sub(root, "divesite")
    for d in dives:
        if d.site and d.site.name and d.site.name not in sites:
            sid = f"site_{len(sites) + 1}"
            sites[d.site.name] = sid
            s = _sub(divesite, "site", id=sid)
            _sub(s, "name", d.site.name)
            if d.site.lat is not None and d.site.lon is not None:
                geo = _sub(s, "geography")
                _sub(geo, "latitude", f"{d.site.lat:.6f}")
                _sub(geo, "longitude", f"{d.site.lon:.6f}")
    if not len(divesite):
        root.remove(divesite)

    # gas definitions
    gases: dict[str, Gas] = {}
    for d in dives:
        for g in d.gases or [Gas()]:
            gases.setdefault(_gas_id(g), g)
    gasdefs = _sub(root, "gasdefinitions")
    for gid, g in gases.items():
        mix = _sub(gasdefs, "mix", id=gid)
        _sub(mix, "name", g.name)
        _sub(mix, "o2", f"{g.o2 / 100:.3f}")
        _sub(mix, "n2", f"{max(0.0, 100 - g.o2 - g.he) / 100:.3f}")
        _sub(mix, "he", f"{g.he / 100:.3f}")

    # profiles
    profiledata = _sub(root, "profiledata")
    rg = _sub(profiledata, "repetitiongroup", id="rg_1")
    for n, d in enumerate(dives, start=1):
        dive = _sub(rg, "dive", id=f"dive_{n}")
        before = _sub(dive, "informationbeforedive")
        if d.site and d.site.name:
            _sub(before, "link", ref=sites[d.site.name])
        if d.computer:
            _sub(before, "link", ref=computers[d.computer.ref])
        if d.number is not None:
            _sub(before, "divenumber", d.number)
        _sub(before, "datetime", d.start.replace(microsecond=0).isoformat())
        if d.surface_interval_s:
            si = _sub(before, "surfaceintervalbeforedive")
            _sub(si, "passedtime", d.surface_interval_s)

        dive_gases = d.gases or [Gas()]
        if d.tanks:
            for t in d.tanks:
                td = _sub(dive, "tankdata")
                _sub(td, "link", ref=_gas_id(t.gas or dive_gases[0]))
                if t.volume_l is not None:
                    _sub(td, "tankvolume", f"{t.volume_l / 1000:.4f}")
                if t.start_bar is not None:
                    _sub(td, "tankpressurebegin", f"{bar_to_pa(t.start_bar):.0f}")
                if t.end_bar is not None:
                    _sub(td, "tankpressureend", f"{bar_to_pa(t.end_bar):.0f}")
        else:
            td = _sub(dive, "tankdata")
            _sub(td, "link", ref=_gas_id(dive_gases[0]))

        samples = _sub(dive, "samples")
        last_gas: int | None = None
        for s in d.samples:
            wp = _sub(samples, "waypoint")
            _sub(wp, "depth", f"{s.depth_m:.2f}")
            _sub(wp, "divetime", f"{s.t_s:.0f}")
            if s.temp_c is not None:
                _sub(wp, "temperature", f"{c_to_k(s.temp_c):.2f}")
            if s.pressure_bar is not None:
                _sub(wp, "tankpressure", f"{bar_to_pa(s.pressure_bar):.0f}")
            if s.ndl_min is not None and s.ndl_min < 500:
                _sub(wp, "nodecotime", f"{s.ndl_min * 60:.0f}")
            if s.deco_depth_m and s.deco_time_min:
                _sub(wp, "decostop", kind="mandatory", decodepth=f"{s.deco_depth_m:.1f}",
                     duration=f"{s.deco_time_min * 60:.0f}")
            gi = s.gas_index if s.gas_index is not None else 0
            if gi != last_gas and gi < len(dive_gases):
                _sub(wp, "switchmix", ref=_gas_id(dive_gases[gi]))
                last_gas = gi

        after = _sub(dive, "informationafterdive")
        _sub(after, "greatestdepth", f"{d.max_depth_m:.2f}")
        if d.avg_depth_m is not None:
            _sub(after, "averagedepth", f"{d.avg_depth_m:.2f}")
        _sub(after, "diveduration", d.duration_s)
        if d.water_temp_min_c is not None:
            _sub(after, "lowesttemperature", f"{c_to_k(d.water_temp_min_c):.2f}")
        if d.notes:
            notes = _sub(after, "notes")
            _sub(notes, "para", d.notes)

    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def uddf_filename(dive: Dive) -> str:
    serial = dive.computer.serial if dive.computer and dive.computer.serial else "dive"
    return f"{dive.start:%Y-%m-%d_%H%M}_{serial}.uddf"
