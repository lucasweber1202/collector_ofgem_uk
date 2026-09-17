"""Fleet invariants: idempotency and PIT-safe revisions."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.config import SCHEMA_NAME, TIME_SERIES_TABLE
from scripts.time_series import Observation, upsert_time_series

SERIES = "TEST_PREDICTOR_SERIES"
DAY_ONE = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
DAY_TWO = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)


def _obs(value: float) -> list[Observation]:
    return [Observation(SERIES, date(2026, 2, 23), value, "snap")]


def test_identical_rerun_is_noop(engine: Engine) -> None:
    with engine.begin() as conn:
        first = upsert_time_series(conn, _obs(150.0), DAY_ONE)
    assert (first.new_observations, first.new_vintages) == (1, 0)
    with engine.begin() as conn:
        second = upsert_time_series(conn, _obs(150.0), DAY_TWO)
    assert (second.new_observations, second.new_vintages) == (0, 0)
    assert second.written_keys == []


def test_later_day_revision_adds_vintage(engine: Engine) -> None:
    with engine.begin() as conn:
        upsert_time_series(conn, _obs(150.0), DAY_ONE)
    with engine.begin() as conn:
        revision = upsert_time_series(conn, _obs(151.5), DAY_TWO)
    assert revision.new_vintages == 1
    assert len(revision.revised_keys) == 1
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT vintage_date, value FROM {SCHEMA_NAME}.{TIME_SERIES_TABLE} ORDER BY vintage_date"
            )
        ).all()
    assert rows == [(date(2026, 3, 2), 150.0), (date(2026, 3, 3), 151.5)]


def test_same_day_revision_fails_closed(engine: Engine) -> None:
    with engine.begin() as conn:
        upsert_time_series(conn, _obs(150.0), DAY_ONE)
    with pytest.raises(RuntimeError, match="same-day revision"), engine.begin() as conn:
        upsert_time_series(conn, _obs(150.4), DAY_ONE.replace(hour=17))
    with engine.connect() as conn:
        value = conn.execute(
            text(f"SELECT value FROM {SCHEMA_NAME}.{TIME_SERIES_TABLE}")
        ).scalar_one()
    assert value == 150.0
