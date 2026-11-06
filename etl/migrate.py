"""Мигратор DWH: применяет sql/dwh/*.sql по возрастанию имени, идемпотентно.

Каждый файл выполняется в своей транзакции и записывается в
public.schema_migrations; повторный запуск — no-op.
"""

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

from etl.config import SQL_DIR

MIGRATIONS_TABLE = "schema_migrations"


def _migrations_dir() -> Path:
    return SQL_DIR / "dwh"


def run_migrations(conn: Connection) -> list[str]:
    if conn.in_transaction():
        conn.commit()
    conn.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS public.{MIGRATIONS_TABLE} ("
            "migration text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
    )
    applied = {row[0] for row in conn.execute(text(f"SELECT migration FROM public.{MIGRATIONS_TABLE}"))}
    conn.commit()
    newly_applied: list[str] = []
    for path in sorted(_migrations_dir().glob("*.sql")):
        name = path.name
        if name in applied:
            continue
        with conn.begin():
            conn.execute(text(path.read_text(encoding="utf-8")))
            conn.execute(
                text(f"INSERT INTO public.{MIGRATIONS_TABLE} (migration) VALUES (:m)"), {"m": name}
            )
        newly_applied.append(name)
    return newly_applied
