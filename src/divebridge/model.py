"""Canonical, format-independent dive model.

Every importer produces these objects, every exporter consumes them.
All quantities are metric: metres, degrees Celsius, bar, seconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Gas:
    o2: float = 21.0  # percent
    he: float = 0.0  # percent

    @property
    def is_air(self) -> bool:
        return abs(self.o2 - 21.0) < 0.5 and self.he == 0

    @property
    def name(self) -> str:
        if self.is_air:
            return "Air"
        if self.he:
            return f"TMX {self.o2:g}/{self.he:g}"
        return f"EAN{self.o2:g}"


@dataclass
class Tank:
    index: int
    volume_l: float | None = None
    working_pressure_bar: float | None = None
    start_bar: float | None = None
    end_bar: float | None = None
    gas: Gas | None = None


@dataclass
class Sample:
    t_s: float
    depth_m: float
    temp_c: float | None = None
    ndl_min: float | None = None
    deco_depth_m: float | None = None
    deco_time_min: float | None = None
    pressure_bar: float | None = None
    ppo2_bar: float | None = None
    gas_index: int | None = None
    speed_m_min: float | None = None
    alarms: tuple[str, ...] = ()


@dataclass
class DiveComputer:
    manufacturer: str
    model: str
    serial: str | None = None
    firmware: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.manufacturer} {self.model}".strip()

    @property
    def ref(self) -> str:
        """Stable identifier of this physical device."""
        return f"{self.display_name}_{self.serial or 'unknown'}"


@dataclass
class Site:
    name: str | None = None
    lat: float | None = None
    lon: float | None = None


@dataclass
class Source:
    format: str
    filename: str
    dive_id: str


@dataclass
class Dive:
    start: datetime  # naive local time of the dive computer
    duration_s: int
    max_depth_m: float
    source: Source
    number: int | None = None
    avg_depth_m: float | None = None
    water_temp_min_c: float | None = None
    water_temp_max_c: float | None = None
    surface_interval_s: int | None = None
    site: Site | None = None
    computer: DiveComputer | None = None
    gases: list[Gas] = field(default_factory=list)
    tanks: list[Tank] = field(default_factory=list)
    samples: list[Sample] = field(default_factory=list)
    notes: str | None = None
    deco: bool = False
    gf_low: int | None = None
    gf_high: int | None = None
    utc_offset_min: int | None = None
    extra: dict[str, object] = field(default_factory=dict)

    @property
    def duration_min(self) -> float:
        return round(self.duration_s / 60.0, 1)

    @property
    def primary_gas(self) -> Gas:
        return self.gases[0] if self.gases else Gas()

    @property
    def dive_ref(self) -> str:
        """Identifier of this dive on this computer (used for de-duplication)."""
        return self.start.replace(microsecond=0).isoformat()

    @property
    def start_pressure_bar(self) -> float | None:
        for t in self.tanks:
            if t.start_bar is not None:
                return t.start_bar
        for s in self.samples:
            if s.pressure_bar is not None:
                return s.pressure_bar
        return None

    @property
    def end_pressure_bar(self) -> float | None:
        for t in self.tanks:
            if t.end_bar is not None:
                return t.end_bar
        for s in reversed(self.samples):
            if s.pressure_bar is not None:
                return s.pressure_bar
        return None

    def summary(self) -> str:
        site = self.site.name if self.site and self.site.name else "?"
        return (
            f"#{self.number or '?'} {self.start:%Y-%m-%d %H:%M} {site}: "
            f"{self.duration_min:g} min, max {self.max_depth_m:.1f} m, "
            f"{len(self.samples)} samples"
        )
