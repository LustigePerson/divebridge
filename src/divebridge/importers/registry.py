"""Registry of input formats. Add a new importer by appending an instance to IMPORTERS."""

from __future__ import annotations

import io
import zipfile
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


def is_zip_archive(filename: str, data: bytes) -> bool:
    """A ZIP that is not itself an importable format (xlsx is a ZIP too, hence the detect check)."""
    return data.startswith(b"PK") and detect(filename, data) is None and zipfile.is_zipfile(io.BytesIO(data))


MAX_ARCHIVE_MEMBERS = 500
MAX_MEMBER_BYTES = 50 * 1024 * 1024  # a DiveSync export is ~60 kB per dive


def expand_archive(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    """Files inside a ZIP (one upload for many exports, handy on phones). Size-capped."""
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if info.is_dir() or not name or name.startswith(("._", ".")) or "__MACOSX" in info.filename:
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                raise ImportError_(f"{filename}: {name} is too large ({info.file_size // 1_000_000} MB)")
            if len(out) >= MAX_ARCHIVE_MEMBERS:
                raise ImportError_(f"{filename}: more than {MAX_ARCHIVE_MEMBERS} files in archive")
            out.append((name, zf.read(info)))
    return out


def parse_file(filename: str, data: bytes, importer: Importer | None = None) -> list[Dive]:
    imp = importer or detect(filename, data)
    if imp is None:
        raise ImportError_(f"{filename}: no importer recognises this file")
    return imp.parse(filename, data)
