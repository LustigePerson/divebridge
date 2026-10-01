"""Runtime configuration: environment variables (set by run.sh from the add-on options) with defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path
    output_dir: Path  # where UDDF files are written (HA: /share/divebridge)
    ssi_email: str | None
    ssi_password: str | None
    ingress_only: bool  # accept only requests from the HA ingress proxy
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("DIVEBRIDGE_DATA_DIR", ".data")).expanduser()
        output_dir = Path(os.environ.get("DIVEBRIDGE_OUTPUT_DIR", str(data_dir / "uddf"))).expanduser()
        return cls(
            data_dir=data_dir,
            output_dir=output_dir,
            ssi_email=os.environ.get("SSI_EMAIL") or None,
            ssi_password=os.environ.get("SSI_PASSWORD") or None,
            ingress_only=os.environ.get("DIVEBRIDGE_INGRESS_ONLY", "0") in ("1", "true", "yes"),
            port=int(os.environ.get("DIVEBRIDGE_PORT", "8099")),
        )
