"""Runtime configuration read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    ingest_root: Path

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./rdp.db"),
            data_dir=Path(os.getenv("DATA_DIR", "./data")),
            ingest_root=Path(os.getenv("INGEST_ROOT", "./bags")),
        )
