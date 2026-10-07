"""divebridge – bring dive computer exports into SSI (MySSI) and UDDF."""

__version__ = "0.1.14"


def main() -> None:  # entry point for `divebridge` script
    from .cli import main as _main

    _main()
