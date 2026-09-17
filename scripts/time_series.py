"""Idempotent, vintage-preserving persistence of raw predictor observations.

Predictor collectors store only published levels. Historical revisions receive a
new vintage. A same-day revision is rejected because the fleet key uses a DATE
vintage and cannot represent two distinct intraday information sets without
rewriting history; retrying on the next UTC day preserves point-in-time safety.
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


_AGGREGATES_SQL = text(f"""SELECT series_id, MIN(reference_date) AS first_observation,
MAX(reference_date) AS last_observation, COUNT(DISTINCT reference_date) AS observation_count,
MAX(collected_at) AS last_collected_at FROM {_TABLE} GROUP BY series_id""")
_LATEST_SQL = text(f"""SELECT series_id, reference_date, vintage_date, value, collected_at
FROM (SELECT series_id, reference_date, vintage_date, value, collected_at,
ROW_NUMBER() OVER (PARTITION BY series_id, reference_date ORDER BY vintage_date DESC,
collected_at DESC) AS rn FROM {_TABLE} WHERE series_id IN :series_ids) ranked WHERE rn = 1""").bindparams(
    bindparam("series_ids", expanding=True)
)
_MAX_REFERENCE_SQL = text(
    f"SELECT series_id, MAX(reference_date) AS last_observation FROM {_TABLE} GROUP BY series_id"
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


def _batch_parameters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        f"{column}_{index}": row[column] for index, row in enumerate(rows) for column in _COLUMNS
    }


def _write_inserts(conn: Connection, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        conn.execute(_insert_statement(len(batch)), _batch_parameters(batch))


def upsert_time_series(
    conn: Connection, observations: list[Observation], collected_at: datetime
) -> WriteResult:
    """Insert new observations and later-day revisions without rewriting history."""
    today = collected_at.date()
    incoming = [o for o in observations if o.value is not None and math.isfinite(o.value)]
    if not incoming:
        return WriteResult(0, 0, [], frozenset(), frozenset())
    by_series: dict[str, list[Observation]] = {}
    for observation in incoming:
        by_series.setdefault(observation.series_id, []).append(observation)
    inserts: list[dict[str, Any]] = []
    written_keys: list[tuple[str, date, date]] = []
    revised_keys: set[tuple[str, date, date]] = set()
    preexisting: set[str] = set()
    new_observations = 0
    new_vintages = 0
    series_ids = sorted(by_series)
    for start in range(0, len(series_ids), SERIES_BATCH_SIZE):
        batch_ids = series_ids[start : start + SERIES_BATCH_SIZE]
        existing = _latest(conn, batch_ids)
        preexisting.update(series_id for series_id, _ in existing)
        for series_id in batch_ids:
            for observation in by_series[series_id]:
                key = (series_id, observation.reference_date)
                current = existing.get(key)
                row = {
                    "series_id": series_id,
                    "reference_date": observation.reference_date,
                    "vintage_date": today,
                    "value": float(observation.value),
                    "collected_at": collected_at,
                }
                if current is None:
                    inserts.append(row)
                    written_keys.append((series_id, observation.reference_date, today))
                    new_observations += 1
                    continue
                if round(float(current["value"]), ROUND_DECIMALS) == round(
                    float(observation.value), ROUND_DECIMALS
                ):
                    continue
                previous_vintage = _as_date(current["vintage_date"])
                if previous_vintage == today:
                    raise RuntimeError(
                        f"Point-in-time unsafe same-day revision for {series_id} {observation.reference_date}: existing={current['value']} incoming={observation.value}. The schema uses DATE vintage_date; retry after the UTC date changes rather than overwriting history."
                    )
                revision_key = (series_id, observation.reference_date, today)
                inserts.append(row)
                written_keys.append(revision_key)
                revised_keys.add(revision_key)
                new_vintages += 1
    _write_inserts(conn, inserts)
    logger.info("Time-series upsert: new=%d new_vintages=%d", new_observations, new_vintages)
    return WriteResult(
        new_observations,
        new_vintages,
        written_keys,
        frozenset(revised_keys),
        frozenset(preexisting),
    )
