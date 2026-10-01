"""SSI logbook variable definitions (id -> name) from `what=get_divelog_vars`.

The MySSI app loads these lists itself; a copy from 2026-10-01 ships with the package as fallback
so the UI and tests work offline. Discovered by probing the API, not documented anywhere.
"""

from __future__ import annotations

import json
import time
from importlib import resources
from pathlib import Path

from .client import SsiClient

CACHE_TTL_S = 30 * 24 * 3600

# groups that make sense for a recreational scuba dive, in UI order
GROUPS: dict[str, str] = {
    "divetype": "Dive type",
    "watertype": "Water",
    "water_body": "Body of water",
    "entry": "Entry",
    "tanktype": "Tank",
    "weather": "Weather",
    "surface": "Surface",
    "current": "Current",
    "specialdive": "Special dive (multiple)",
}
MULTI_GROUPS = {"specialdive"}

# ids with special handling
WATERTYPE_SALT = 5
WATERTYPE_FRESH = 4
DIVETYPE_FUN = 24
TANKTYPE_STEEL = 19

VarTable = dict[str, dict[int, str]]


def _parse(doc: dict) -> VarTable:
    out: VarTable = {}
    for group, items in doc.get("logbook_vars", {}).items():
        if isinstance(items, dict):
            out[group] = {int(k): str(v) for k, v in items.items() if str(k).isdigit()}
    return out


def bundled_vars() -> VarTable:
    with resources.files(__package__).joinpath("divelog_vars.json").open("r", encoding="utf-8") as f:
        return _parse(json.load(f))


def pretty(name: str) -> str:
    return name.replace("dive_log_var_", "").replace("_", " ")


class VarIndex:
    def __init__(self, data_dir: Path | None = None, client: SsiClient | None = None):
        self.data_dir = data_dir
        self.client = client
        self._table: VarTable | None = None

    @property
    def cache_file(self) -> Path | None:
        return self.data_dir / "ssi-divelog-vars.json" if self.data_dir else None

    def refresh(self) -> VarTable:
        if self.client is None:
            raise RuntimeError("no SSI client")
        doc = self.client.get_divelog_vars()
        if self.cache_file:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(doc))
        self._table = _parse(doc)
        return self._table

    def table(self) -> VarTable:
        if self._table is not None:
            return self._table
        f = self.cache_file
        if f and f.exists():
            try:
                self._table = _parse(json.loads(f.read_text()))
                if time.time() - f.stat().st_mtime > CACHE_TTL_S and self.client is not None:
                    try:
                        self.refresh()
                    except Exception:  # noqa: BLE001 – stale cache is fine
                        pass
                return self._table
            except (OSError, ValueError):
                pass
        if self.client is not None:
            try:
                return self.refresh()
            except Exception:  # noqa: BLE001
                pass
        self._table = bundled_vars()
        return self._table

    def name(self, group: str, id_: int | None) -> str | None:
        if id_ is None:
            return None
        return self.table().get(group, {}).get(id_)

    def options(self, group: str) -> list[tuple[int, str]]:
        return sorted(((i, pretty(n)) for i, n in self.table().get(group, {}).items()), key=lambda x: x[1])
