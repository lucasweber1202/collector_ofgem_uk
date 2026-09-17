"""Shared fixtures: an isolated SQLite stand-in carrying the shipped DDL."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from scripts import init_db
from scripts.config import SCHEMA_NAME

# sqlite3 removed its implicit datetime adapters in Python 3.12, and the
# collector stores timezone-aware instants in `availability.available_at`.
# Registering the pair here keeps the test database round-tripping the same
# values PostgreSQL and Databricks store, rather than silently stringifying.
sqlite3.register_adapter(datetime, lambda value: value.isoformat())
sqlite3.register_adapter(date, lambda value: value.isoformat())
sqlite3.register_converter(
    "TIMESTAMP", lambda raw: datetime.fromisoformat(raw.decode()).astimezone(UTC)
)
sqlite3.register_converter("DATE", lambda raw: date.fromisoformat(raw.decode()[:10]))


def build_sqlite_engine(tmp_path: Path) -> Engine:
    """Create the shipped tables in an attached SQLite database.

    SQLite has no CREATE SCHEMA, so the schema is attached under its production
    name and every other DDL statement is the one the collector ships.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'main.db'}",
        connect_args={"detect_types": sqlite3.PARSE_DECLTYPES},
    )
    schema_path = tmp_path / "predictors.db"

    @event.listens_for(engine, "connect")
    def _attach(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        dbapi_connection.execute(f"ATTACH DATABASE '{schema_path}' AS {SCHEMA_NAME}")

    logs = init_db.CREATE_LOGS_TABLE.replace(
        "id BIGINT GENERATED ALWAYS AS IDENTITY", "id INTEGER PRIMARY KEY AUTOINCREMENT"
    ).replace(",\n    CONSTRAINT pk_logs PRIMARY KEY (id)", "")
    with engine.begin() as conn:
        for statement in (
            init_db.CREATE_METADATA_TABLE,
            init_db.CREATE_TIME_SERIES_TABLE.format(double="DOUBLE"),
            init_db.CREATE_AVAILABILITY_TABLE,
            init_db.CREATE_SNAPSHOTS_TABLE,
            logs,
        ):
            conn.execute(text(statement))
    return engine


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Yield a disposable database carrying the shipped DDL."""
    created = build_sqlite_engine(tmp_path)
    try:
        yield created
    finally:
        created.dispose()
