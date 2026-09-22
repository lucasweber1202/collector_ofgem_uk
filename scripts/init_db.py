"""Create the predictor schema and its five standardized tables."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.config import (
    AVAILABILITY_TABLE,
    LOGS_TABLE,
    METADATA_TABLE,
    SCHEMA_NAME,
    SNAPSHOTS_TABLE,
    TIME_SERIES_TABLE,
)
from scripts.db import build_engine
from scripts.legacy_schema import migrate_legacy_metadata

# PostgreSQL and Databricks SQL share no spelling for a 64-bit float. Spark's
# parser lists DOUBLE as the only alias for DoubleType, so Databricks rejects
# DOUBLE PRECISION; PostgreSQL has no DOUBLE and rejects it in turn. FLOAT is
# not a way out: PostgreSQL resolves a bare FLOAT to 8-byte float8 while
# Databricks resolves it to 4-byte FloatType, which would silently halve stored
# precision instead of failing loudly.
DOUBLE_TYPES = {"postgresql": "DOUBLE PRECISION"}
DEFAULT_DOUBLE_TYPE = "DOUBLE"

CREATE_SCHEMA = f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}"

# Legacy metadata columns that must be copied into a sidecar before they
# are dropped, as {column: sidecar table}. `source_id` needs no entry:
# every row of it is already stored in source_snapshots.
LEGACY_METADATA_ARCHIVE: dict[str, str] = {}

CREATE_METADATA_TABLE = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{METADATA_TABLE} (
    series_id VARCHAR(200) NOT NULL,
    name VARCHAR(500) NOT NULL,
    description VARCHAR(2000),
    country VARCHAR(3) NOT NULL,
    frequency VARCHAR(20),
    unit VARCHAR(50),
    first_observation DATE,
    last_observation DATE,
    observation_count INTEGER NOT NULL,
    eco_group VARCHAR(250),
    source_url VARCHAR(1000) NOT NULL,
    last_publish_date DATE,
    collected_at TIMESTAMP NOT NULL,
    CONSTRAINT pk_metadata PRIMARY KEY (series_id)
)
"""

# Fleet-standard shape: append-only, one row per stored vintage of an
# observation. Raw published levels only; no derived transformation is stored.
CREATE_TIME_SERIES_TABLE = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{TIME_SERIES_TABLE} (
    series_id VARCHAR(200) NOT NULL,
    reference_date DATE NOT NULL,
    vintage_date DATE NOT NULL,
    value {{double}} NOT NULL,
    collected_at TIMESTAMP NOT NULL,
    CONSTRAINT pk_time_series PRIMARY KEY (series_id, reference_date, vintage_date)
)
"""

# Point-in-time companion, keyed one-to-one with a time_series row. It answers
# "when did this stored vintage actually become knowable", which vintage_date
# alone cannot: a historical backfill stamps vintage_date with the collection
# day for the whole history. `availability_basis` records how strong the
# evidence for `available_at` is and is never allowed to be blank.
CREATE_AVAILABILITY_TABLE = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{AVAILABILITY_TABLE} (
    series_id VARCHAR(200) NOT NULL,
    reference_date DATE NOT NULL,
    vintage_date DATE NOT NULL,
    release_date DATE,
    available_at TIMESTAMP NOT NULL,
    availability_basis VARCHAR(30) NOT NULL,
    source_snapshot_id VARCHAR(64) NOT NULL,
    collected_at TIMESTAMP NOT NULL,
    CONSTRAINT pk_availability PRIMARY KEY (series_id, reference_date, vintage_date)
)
"""

# One row per distinct raw file actually parsed. `snapshot_id` is the SHA256 of
# the bytes, so re-downloading an unchanged file is a no-op and a silently
# replaced historical file appears as a new row rather than overwriting the old.
CREATE_SNAPSHOTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{SNAPSHOTS_TABLE} (
    snapshot_id VARCHAR(64) NOT NULL,
    source_id VARCHAR(100) NOT NULL,
    source_url VARCHAR(1000) NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    source_published_date DATE,
    http_etag VARCHAR(200),
    http_last_modified VARCHAR(100),
    sha256 VARCHAR(64) NOT NULL,
    byte_size BIGINT NOT NULL,
    raw_path VARCHAR(1000) NOT NULL,
    CONSTRAINT pk_source_snapshots PRIMARY KEY (snapshot_id)
)
"""

CREATE_LOGS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{LOGS_TABLE} (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL,
    log_text VARCHAR(65535) NOT NULL,
    traceback VARCHAR(65535),
    CONSTRAINT pk_logs PRIMARY KEY (id)
)
"""


def double_type(dialect: str) -> str:
    """Return the 64-bit float spelling this SQL dialect accepts."""
    return DOUBLE_TYPES.get(dialect, DEFAULT_DOUBLE_TYPE)


def init_db(engine: Engine) -> None:
    """Create all database objects idempotently."""
    double = double_type(engine.dialect.name)
    with engine.begin() as conn:
        for statement in (
            CREATE_SCHEMA,
            CREATE_METADATA_TABLE,
            CREATE_TIME_SERIES_TABLE.format(double=double),
            CREATE_AVAILABILITY_TABLE,
            CREATE_SNAPSHOTS_TABLE,
            CREATE_LOGS_TABLE,
        ):
            conn.execute(text(statement))
        # CREATE TABLE IF NOT EXISTS leaves a pre-canonical table untouched,
        # so the live shape is checked against the standardized columns.
        migrate_legacy_metadata(conn, LEGACY_METADATA_ARCHIVE)


if __name__ == "__main__":
    init_db(build_engine())
