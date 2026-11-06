"""Shared pytest fixtures (minimal version; test DB isolation lands in Task 10)."""

import os

import pytest
from sqlalchemy import create_engine, text


def make_engine():
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5433/deals_bigdata",
    )
    return create_engine(url)


@pytest.fixture(scope="session")
def engine():
    eng = make_engine()
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    return eng


@pytest.fixture(scope="session")
def migrated(engine):
    from etl.migrate import run_migrations

    with engine.connect() as conn:
        applied = run_migrations(conn)
        conn.commit()
    return applied


@pytest.fixture()
def conn(engine, migrated):
    with engine.connect() as connection:
        yield connection
        connection.rollback()
