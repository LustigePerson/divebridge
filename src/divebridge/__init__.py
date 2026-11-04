"""divebridge – bring dive computer exports into SSI (MySSI) and UDDF."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("divebridge")  # single source: pyproject.toml (config.yaml carries the add-on version)
except PackageNotFoundError:  # running from a checkout without an installed package
    __version__ = "0.0.0+unknown"


def main() -> None:  # entry point for `divebridge` script
    from .cli import main as _main

    _main()
