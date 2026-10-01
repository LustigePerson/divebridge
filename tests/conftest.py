from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = Path(__file__).resolve().parent / "data" / "cressi" / "SKIFF_000002_10_15_2025_025607.xlsx"


@pytest.fixture(scope="session")
def sample_bytes() -> bytes:
    return SAMPLE.read_bytes()


@pytest.fixture(scope="session")
def sample_dives(sample_bytes):
    from divebridge.importers import parse_file

    return parse_file(SAMPLE.name, sample_bytes)
