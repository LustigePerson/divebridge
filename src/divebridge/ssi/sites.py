"""SSI dive site database: download, cache and search (name / nearest)."""

from __future__ import annotations

import difflib
import io
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..units import haversine_m
from .client import SsiClient

CACHE_TTL_S = 7 * 24 * 3600
NEAREST_MAX_M = 5_000


@dataclass
class SiteMatch:
    id: int
    name: str
    country: str
    region: str
    lat: float | None
    lon: float | None
    score: float = 0.0

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.region:
            parts.append(self.region)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)


class SiteIndex:
    def __init__(self, data_dir: Path, client: SsiClient | None = None):
        self.data_dir = data_dir
        self.client = client
        self._sites: list[dict[str, Any]] | None = None

    @property
    def json_file(self) -> Path:
        return self.data_dir / "ssi-sites.json"

    def ensure(self, force: bool = False) -> None:
        f = self.json_file
        fresh = f.exists() and (time.time() - f.stat().st_mtime) < CACHE_TTL_S
        if fresh and not force:
            return
        client = self.client or SsiClient(data_dir=self.data_dir)
        raw = client.download_sites_zip()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            name = next((n for n in zf.namelist() if n.endswith(".json")), None)
            if name is None:
                raise RuntimeError("no JSON inside APP_CACHE_SITES.zip")
            data = zf.read(name)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        self._sites = None

    def _load(self) -> list[dict[str, Any]]:
        if self._sites is None:
            self.ensure()
            doc = json.loads(self.json_file.read_text(encoding="utf-8"))
            self._sites = [s for s in doc.get("divesites", [])
                           if isinstance(s.get("odin_dive_sites_name"), str) and not s.get("odin_dive_sites_deleted")]
        return self._sites

    @staticmethod
    def _match(s: dict[str, Any], score: float = 0.0) -> SiteMatch:
        return SiteMatch(
            id=int(s["odin_dive_sites_id"]),
            name=s["odin_dive_sites_name"],
            country=str(s.get("odin_dive_sites_meta_country") or ""),
            region=str(s.get("odin_dive_sites_meta_region") or ""),
            lat=s.get("odin_dive_sites_lat") or None,
            lon=s.get("odin_dive_sites_lon") or None,
            score=score,
        )

    def __len__(self) -> int:
        return len(self._load())

    def get(self, site_id: int) -> SiteMatch | None:
        for s in self._load():
            if int(s["odin_dive_sites_id"]) == site_id:
                return self._match(s)
        return None

    def search(self, query: str, limit: int = 20) -> list[SiteMatch]:
        q = query.strip().lower()
        if len(q) < 2:
            return []
        results: list[SiteMatch] = []
        for s in self._load():
            name = s["odin_dive_sites_name"].lower()
            if q in name:
                score = 1.0 if name == q else (0.9 if name.startswith(q) else 0.5 + difflib.SequenceMatcher(None, q, name).ratio() / 4)
                results.append(self._match(s, score))
        results.sort(key=lambda m: (-m.score, m.name))
        return results[:limit]

    def nearest(self, lat: float, lon: float, max_m: float = NEAREST_MAX_M) -> SiteMatch | None:
        best, best_d = None, float("inf")
        for s in self._load():
            la, lo = s.get("odin_dive_sites_lat"), s.get("odin_dive_sites_lon")
            if not la or not lo:
                continue
            d = haversine_m(lat, lon, la, lo)
            if d < best_d:
                best, best_d = s, d
        return self._match(best, 1.0) if best is not None and best_d <= max_m else None
