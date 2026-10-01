"""Registry of input formats. Add a new importer by appending an instance to IMPORTERS."""

from __future__ import annotations

from pathlib import Path

from ..model import Dive
from .base import Importer, ImportError_
from .cressi_divesync import CressiDiveSyncImporter

IMPORTERS: list[Importer] = [
    CressiDiveSyncImporter(),
]


def detect(filename: str, data: bytes) -> Importer | None:
    ext = Path(filename).suffix.lower()
    # extension match first, then content sniffing
    candidates = [i for i in IMPORTERS if ext in i.extensions] + [
        i for i in IMPORTERS if ext not in i.extensions
    ]
    for imp in candidates:
        try:
            if imp.can_handle(filename, data):
                return imp
        except Exception:  # noqa: BLE001 – sniffing must never crash
            continue
    return None


def parse_file(filename: str, data: bytes, importer: Importer | None = None) -> list[Dive]:
    imp = importer or detect(filename, data)
    if imp is None:
        raise ImportError_(f"{filename}: no importer recognises this file")
    return imp.parse(filename, data)
