"""Конфигурация пайплайна: только переменные окружения, без захардкоженных секретов."""

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "sql"


@dataclass(frozen=True)
class Settings:
    database_url: str
    as_of: date
    seed: int = 42
    batch_size: int = 10_000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL",
                "postgresql+psycopg://postgres:postgres@localhost:5432/deals_bigdata",
            ),
            as_of=date.fromisoformat(os.environ.get("AS_OF", "2026-10-26")),
            seed=int(os.environ.get("SEED", "42")),
            batch_size=int(os.environ.get("BATCH_SIZE", "10000")),
        )


def get_settings() -> Settings:
    return Settings.from_env()
