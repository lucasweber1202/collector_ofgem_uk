"""Idempotent, vintage-preserving persistence of raw predictor observations.

Predictor collectors store only published levels. The vintage rules are the
fleet's (GUIDELINES.md 3):

* first sight of ``(series_id, reference_date)`` -- INSERT with
  ``vintage_date`` = the collection date, never the reference date;
* unchanged value on a later run -- no-op, ``collected_at`` is not touched;
* changed value, latest stored vintage earlier than today -- INSERT a new
  vintage row;
* changed value, latest stored vintage IS today -- UPDATE that row in place.

The last rule is what keeps ``(series_id, reference_date, vintage_date)``
unique: a DATE vintage cannot hold two same-day revisions as separate rows, so
the latest collection of the day wins. Databricks does not enforce the primary
key, so the application is the only thing preventing duplicates.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import TextClause, bindparam, text
from sqlalchemy.engine import Connection, Engine

from scripts.config import SCHEMA_NAME, TIME_SERIES_TABLE

logger = logging.getLogger(__name__)
_TABLE = f"{SCHEMA_NAME}.{TIME_SERIES_TABLE}"
BATCH_SIZE = 500
SERIES_BATCH_SIZE = 50
ROUND_DECIMALS = 10
_COLUMNS = ("series_id", "reference_date", "vintage_date", "value", "collected_at")
_MERGE_DIALECTS = frozenset({"databricks"})


@dataclass(frozen=True)
class Observation:
    series_id: str
    reference_date: date
    value: float
    snapshot_id: str


@dataclass(frozen=True)
class WriteResult:
    new_observations: int
    new_vintages: int
    written_keys: list[tuple[str, date, date]]
    revised_keys: frozenset[tuple[str, date, date]]
    preexisting_series: frozenset[str]
    same_day_updates: int = 0
    same_day_keys: frozenset[tuple[str, date, date]] = frozenset()


_AGGREGATES_SQL = text(
    f"""SELECT series_id, MIN(reference_date) AS first_observation,
MAX(reference_date) AS last_observation, COUNT(DISTINCT reference_date) AS observation_count,
MAX(collected_at) AS last_collected_at FROM {_TABLE} GROUP BY series_id"""
)
_LATEST_SQL = text(
    f"""SELECT series_id, reference_date, vintage_date, value, collected_at
FROM (SELECT series_id, reference_date, vintage_date, value, collected_at,
ROW_NUMBER() OVER (PARTITION BY series_id, reference_date ORDER BY vintage_date DESC,
collected_at DESC) AS rn FROM {_TABLE} WHERE series_id IN :series_ids) ranked WHERE rn = 1"""
).bindparams(bindparam("series_ids", expanding=True))
_MAX_REFERENCE_SQL = text(
    f"SELECT series_id, MAX(reference_date) AS last_observation FROM {_TABLE} GROUP BY series_id"
)
_UPDATE_SQL = text(
    f"""UPDATE {_TABLE} SET value = :value, collected_at = :collected_at
WHERE series_id = :series_id AND reference_date = :reference_date
AND vintage_date = :vintage_date"""
)


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    assert isinstance(value, date)
    return value


def get_last_observations(engine: Engine) -> dict[str, date]:
    with engine.connect() as conn:
        rows = conn.execute(_MAX_REFERENCE_SQL).mappings().all()
    return {str(row["series_id"]): _as_date(row["last_observation"]) for row in rows}


def get_series_aggregates(conn: Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute(_AGGREGATES_SQL).mappings().all()
    return {str(row["series_id"]): dict(row) for row in rows}


def _latest(conn: Connection, series_ids: list[str]) -> dict[tuple[str, date], dict[str, Any]]:
    rows = conn.execute(_LATEST_SQL, {"series_ids": series_ids}).mappings().all()
    return {(str(row["series_id"]), _as_date(row["reference_date"])): dict(row) for row in rows}


def _insert_statement(count: int) -> TextClause:
    values = ", ".join(
        "(" + ", ".join(f":{column}_{index}" for column in _COLUMNS) + ")" for index in range(count)
    )
    return text(f"INSERT INTO {_TABLE} ({', '.join(_COLUMNS)}) VALUES {values}")


def _merge_statement(count: int) -> TextClause:
    """Batched same-day UPDATE for engines that support MERGE.

    Databricks rejects column aliases on a VALUES clause inside MERGE
    (COLUMN_ALIASES_NOT_ALLOWED), so the source is a UNION ALL of SELECT
    literals, matching the metadata helper.
    """
    source = " UNION ALL ".join(
        "SELECT " + ", ".join(f":{column}_{index} AS {column}" for column in _COLUMNS)
        for index in range(count)
    )
    return text(
        f"MERGE INTO {_TABLE} AS target USING ({source}) AS source "
        "ON target.series_id = source.series_id "
        "AND target.reference_date = source.reference_date "
        "AND target.vintage_date = source.vintage_date "
        "WHEN MATCHED THEN UPDATE SET target.value = source.value, "
        "target.collected_at = source.collected_at"
    )


def _batch_parameters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        f"{column}_{index}": row[column] for index, row in enumerate(rows) for column in _COLUMNS
    }


def _write_inserts(conn: Connection, rows: list[dict[str, Any]]) -> None:
    """Multi-row VALUES inserts with per-batch progress logging."""
    if not rows:
        return
    total = len(rows)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info(
        "Inserting %d observation rows in %d batches of %d", total, total_batches, BATCH_SIZE
    )
    written = 0
    for index, start in enumerate(range(0, total, BATCH_SIZE), start=1):
        batch = rows[start : start + BATCH_SIZE]
        conn.execute(_insert_statement(len(batch)), _batch_parameters(batch))
        written += len(batch)
        logger.info("Inserted batch %d/%d (%d/%d rows)", index, total_batches, written, total)


def _write_same_day_updates(conn: Connection, rows: list[dict[str, Any]]) -> None:
    """Overwrite today's vintage in place, batched, with progress logging."""
    if not rows:
        return
    total = len(rows)
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info(
        "Updating %d same-day observation rows in %d batches of %d",
        total,
        total_batches,
        BATCH_SIZE,
    )
    written = 0
    use_merge = conn.dialect.name in _MERGE_DIALECTS
    for index, start in enumerate(range(0, total, BATCH_SIZE), start=1):
        batch = rows[start : start + BATCH_SIZE]
        if use_merge:
            conn.execute(_merge_statement(len(batch)), _batch_parameters(batch))
        else:
            conn.execute(_UPDATE_SQL, batch)
        written += len(batch)
        logger.info("Updated batch %d/%d (%d/%d rows)", index, total_batches, written, total)


def upsert_time_series(
    conn: Connection, observations: list[Observation], collected_at: datetime
) -> WriteResult:
    """Apply the fleet vintage rules to this run's observations."""
    today = collected_at.date()
    # Pair each observation with its validated value: a null or non-finite
    # reading never reaches the table, and the pairing keeps that guarantee
    # visible to the type checker instead of re-asserting it later.
    incoming: list[tuple[Observation, float]] = [
        (o, float(o.value)) for o in observations if o.value is not None and math.isfinite(o.value)
    ]
    if not incoming:
        return WriteResult(0, 0, [], frozenset(), frozenset())
    by_series: dict[str, list[tuple[Observation, float]]] = {}
    for observation, value in incoming:
        by_series.setdefault(observation.series_id, []).append((observation, value))

    inserts: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    written_keys: list[tuple[str, date, date]] = []
    revised_keys: set[tuple[str, date, date]] = set()
    same_day_keys: set[tuple[str, date, date]] = set()
    preexisting: set[str] = set()
    new_observations = 0
    new_vintages = 0

    series_ids = sorted(by_series)
    for start in range(0, len(series_ids), SERIES_BATCH_SIZE):
        batch_ids = series_ids[start : start + SERIES_BATCH_SIZE]
        existing = _latest(conn, batch_ids)
        preexisting.update(series_id for series_id, _ in existing)
        for series_id in batch_ids:
            for observation, value in by_series[series_id]:
                key = (series_id, observation.reference_date)
                current = existing.get(key)
                row = {
                    "series_id": series_id,
                    "reference_date": observation.reference_date,
                    "vintage_date": today,
                    "value": value,
                    "collected_at": collected_at,
                }
                if current is None:
                    inserts.append(row)
                    written_keys.append((series_id, observation.reference_date, today))
                    new_observations += 1
                    continue
                unchanged = round(float(current["value"]), ROUND_DECIMALS) == round(
                    value, ROUND_DECIMALS
                )
                if unchanged:
                    continue
                previous_vintage = _as_date(current["vintage_date"])
                revision_key = (series_id, observation.reference_date, today)
                if previous_vintage == today:
                    # A DATE vintage cannot hold two same-day revisions as
                    # separate rows, so the latest collection of the day wins
                    # and replaces today's row in place.
                    updates.append(row)
                    written_keys.append(revision_key)
                    same_day_keys.add(revision_key)
                    continue
                inserts.append(row)
                written_keys.append(revision_key)
                revised_keys.add(revision_key)
                new_vintages += 1

    _write_inserts(conn, inserts)
    _write_same_day_updates(conn, updates)
    logger.info(
        "Time-series upsert: new=%d new_vintages=%d same_day_updates=%d",
        new_observations,
        new_vintages,
        len(updates),
    )
    return WriteResult(
        new_observations,
        new_vintages,
        written_keys,
        frozenset(revised_keys),
        frozenset(preexisting),
        len(updates),
        frozenset(same_day_keys),
    )
