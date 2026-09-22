"""Build and idempotently upsert predictor metadata after observation writes."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import TextClause, text
from sqlalchemy.engine import Connection

from scripts.config import COUNTRY_CURRENCY, METADATA_TABLE, SCHEMA_NAME
from scripts.time_series import get_series_aggregates

logger = logging.getLogger(__name__)
_TABLE = f"{SCHEMA_NAME}.{METADATA_TABLE}"
BATCH_SIZE = 500
FREQUENCIES = frozenset(
    {
        "daily",
        "weekly",
        "biweekly",
        "monthly",
        "quarterly",
        "semiannual",
        "annual",
        "decennial",
        "quinquennial",
        "irregular",
    }
)
UNITS = frozenset(
    {
        "index",
        "percent",
        "ratio",
        "persons",
        "currency",
        "count",
        "tons",
        "hectares",
        "cubic_meters",
        "megawatt_hours",
        "other",
    }
)
ECO_GROUPS = frozenset(
    {
        "gdp",
        "activity",
        "industrial_production",
        "production",
        "retail_sales",
        "vehicles",
        "tourism",
        "mining",
        "savings",
        "leading_indicators",
        "consumer_prices",
        "producer_prices",
        "inflation",
        "inflation_expectations",
        "labor",
        "employment",
        "unemployment",
        "wages",
        "trade",
        "balance_of_payments",
        "exchange_rates",
        "external_accounts",
        "central_bank",
        "monetary_aggregates",
        "interest_rates",
        "financial_markets",
        "financial_intermediaries",
        "government_securities",
        "currency_in_circulation",
        "payment_systems",
        "petroleum_fund",
        "public_finance",
        "surveys",
        "consumer_confidence",
        "business_confidence",
        "other",
    }
)

_COMPARABLE_COLUMNS = (
    "name",
    "description",
    "country",
    "frequency",
    "unit",
    "first_observation",
    "last_observation",
    "observation_count",
    "eco_group",
    "source_url",
    "last_publish_date",
)
_COLUMNS = ("series_id", *_COMPARABLE_COLUMNS, "collected_at")
_UPDATE_COLUMNS = tuple(column for column in _COLUMNS if column != "series_id")
_MERGE_DIALECTS = frozenset({"databricks", "postgresql"})
_SELECT_SQL = text(f"SELECT {', '.join(_COLUMNS)} FROM {_TABLE}")


def _batch_parameters(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        f"{column}_{index}": row[column] for index, row in enumerate(rows) for column in _COLUMNS
    }


def _insert_statement(count: int) -> TextClause:
    values = ", ".join(
        "(" + ", ".join(f":{column}_{index}" for column in _COLUMNS) + ")" for index in range(count)
    )
    return text(f"INSERT INTO {_TABLE} ({', '.join(_COLUMNS)}) VALUES {values}")


def _merge_statement(count: int) -> TextClause:
    source = " UNION ALL ".join(
        "SELECT " + ", ".join(f":{column}_{index} AS {column}" for column in _COLUMNS)
        for index in range(count)
    )
    assignments = ", ".join(f"{column} = source.{column}" for column in _UPDATE_COLUMNS)
    return text(
        f"MERGE INTO {_TABLE} AS target USING ({source}) AS source ON target.series_id = source.series_id WHEN MATCHED THEN UPDATE SET {assignments}"
    )


_UPDATE_SQL = text(
    f"UPDATE {_TABLE} SET {', '.join(f'{column}=:{column}' for column in _UPDATE_COLUMNS)} WHERE series_id=:series_id"
)


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    assert isinstance(value, date)
    return value


def validate_catalog(catalog: dict[str, dict[str, Any]]) -> None:
    for series_id, fields in sorted(catalog.items()):
        for key in ("name", "source_url"):
            if not str(fields.get(key, "")).strip():
                raise ValueError(f"{series_id} metadata is missing required field {key!r}")
        if fields["frequency"] not in FREQUENCIES:
            raise ValueError(f"{series_id} has unknown frequency {fields['frequency']!r}")
        if fields["unit"] not in UNITS:
            raise ValueError(f"{series_id} has unknown unit {fields['unit']!r}")
        if fields["eco_group"] not in ECO_GROUPS:
            raise ValueError(f"{series_id} has unknown eco_group {fields['eco_group']!r}")
        if fields.get("country", COUNTRY_CURRENCY) != COUNTRY_CURRENCY:
            raise ValueError(f"{series_id} must carry country {COUNTRY_CURRENCY}")


def upsert_metadata(
    conn: Connection, catalog: dict[str, dict[str, Any]], collected_at: datetime
) -> tuple[int, int]:
    validate_catalog(catalog)
    aggregates = get_series_aggregates(conn)
    existing = {
        str(row["series_id"]): dict(row) for row in conn.execute(_SELECT_SQL).mappings().all()
    }
    desired: list[dict[str, Any]] = []
    for series_id, fields in sorted(catalog.items()):
        history = aggregates.get(series_id)
        if history is None:
            logger.warning("%s has no stored observations; skipping metadata", series_id)
            continue
        desired.append(
            {
                "series_id": series_id,
                "name": fields["name"],
                "description": fields.get("description"),
                "country": COUNTRY_CURRENCY,
                "frequency": fields["frequency"],
                "unit": fields["unit"],
                "first_observation": _as_date(history["first_observation"]),
                "last_observation": _as_date(history["last_observation"]),
                "observation_count": int(history["observation_count"]),
                "eco_group": fields["eco_group"],
                "source_url": fields["source_url"],
                "last_publish_date": fields.get("last_publish_date"),
                "collected_at": collected_at,
            }
        )
    inserts = [row for row in desired if row["series_id"] not in existing]
    updates: list[dict[str, Any]] = []
    for row in desired:
        current = existing.get(row["series_id"])
        if current is not None and any(
            _normalize(row[column]) != _normalize(current.get(column))
            for column in _COMPARABLE_COLUMNS
        ):
            updates.append(row)
    for start in range(0, len(inserts), BATCH_SIZE):
        batch = inserts[start : start + BATCH_SIZE]
        conn.execute(_insert_statement(len(batch)), _batch_parameters(batch))
    if updates:
        if conn.dialect.name in _MERGE_DIALECTS:
            for start in range(0, len(updates), BATCH_SIZE):
                batch = updates[start : start + BATCH_SIZE]
                conn.execute(_merge_statement(len(batch)), _batch_parameters(batch))
        else:
            conn.execute(_UPDATE_SQL, updates)
    return len(inserts), len(updates)


def _normalize(value: object) -> object:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return str(value)
