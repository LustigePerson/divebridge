"""Importer protocol. A new input format = one module implementing this + a registry entry."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..model import Dive


class ImportError_(Exception):
    """Raised when a file cannot be parsed by the selected importer."""


@runtime_checkable
class Importer(Protocol):
    name: str  # short id, e.g. "cressi_divesync"
    description: str  # human readable
    extensions: tuple[str, ...]  # lower-case, with dot

    def can_handle(self, filename: str, data: bytes) -> bool: ...

    def parse(self, filename: str, data: bytes) -> list[Dive]: ...
