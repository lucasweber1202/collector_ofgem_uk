"""Regression test for the historical-revision look-ahead bug."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from sqlalchemy.engine import Engine

from main import _availability_rows
from scripts.availability import get_series_as_of, upsert_availability
from scripts.time_series import Observation, upsert_time_series

SERIES = "TEST_PREDICTOR_SERIES"
REFERENCE = date(2026, 1, 5)
FIRST_COLLECTED = datetime(2026, 1, 6, 9, 0, tzinfo=UTC)
REVISION_COLLECTED = datetime(2026, 3, 10, 15, 0, tzinfo=UTC)
ORIGINAL_RELEASE = datetime(2026, 1, 6, 8, 30, tzinfo=UTC)


def _data(value: float) -> SimpleNamespace:
    observation = Observation(SERIES, REFERENCE, value, "snap")
    return SimpleNamespace(
        observations=[observation],
        releases=[ORIGINAL_RELEASE],
        min_lag_days=0,
        max_lag_days=31,
        inferred_lag_days=1,
    )


def test_revision_uses_first_seen_not_original_release(engine: Engine) -> None:
    with engine.begin() as conn:
        first = upsert_time_series(conn, _data(150.0).observations, FIRST_COLLECTED)
        rows = _availability_rows(_data(150.0), first, FIRST_COLLECTED)
        upsert_availability(conn, rows, FIRST_COLLECTED)
    with engine.begin() as conn:
        revision = upsert_time_series(conn, _data(151.5).observations, REVISION_COLLECTED)
        rows = _availability_rows(_data(151.5), revision, REVISION_COLLECTED)
        assert rows[0]["availability_basis"] == "first_seen"
        assert rows[0]["available_at"] == REVISION_COLLECTED
        assert rows[0]["release_date"] is None
        upsert_availability(conn, rows, REVISION_COLLECTED)

    before_revision = get_series_as_of(engine, SERIES, datetime(2026, 2, 1, tzinfo=UTC))
    assert [row["value"] for row in before_revision] == [150.0]
    after_revision = get_series_as_of(engine, SERIES, datetime(2026, 4, 1, tzinfo=UTC))
    assert [row["value"] for row in after_revision] == [151.5]
