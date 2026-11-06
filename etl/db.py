"""Подключение к PostgreSQL через SQLAlchemy."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from etl.config import Settings


def connect(settings: Settings) -> Connection:
    engine = create_engine(settings.database_url)
    return engine.connect()
