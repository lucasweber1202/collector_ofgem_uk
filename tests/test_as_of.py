"""The point-in-time contract: get_series_as_of must never look ahead."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.engine import Engine

from scripts.availability import (
    AVAILABILITY_BASES,
    POINT_IN_TIME_BASES,
    get_series_as_of,
    upsert_availability,
)
from scripts.time_series import Observation, upsert_time_series

SERIES = "DESNZ_ROADFUEL_ULSP_PUMPPRICE"
RUN_AT = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)


def _store(
    engine: Engine,
    reference_date: date,
    value: float,
    available_at: datetime,
    basis: str = "official_timestamp",
    collected_at: datetime = RUN_AT,
) -> None:
    """Write one observation and its availability row exactly as the pipeline does."""
    with engine.begin() as conn:
        result = upsert_time_series(
            conn, [Observation(SERIES, reference_date, value, "snap")], collected_at
        )
        upsert_availability(
            conn,
            [
                {
                    "series_id": series_id,
                    "reference_date": reference,
                    "vintage_date": vintage,
                    "release_date": available_at.date(),
                    "available_at": available_at,
                    "availability_basis": basis,
                    "source_snapshot_id": "snap",
                }
                for series_id, reference, vintage in result.written_keys
            ],
            collected_at,
        )


def test_observation_is_invisible_before_it_was_published(engine: Engine) -> None:
    """An as-of instant before the release must not see the observation at all."""
    reference = date(2026, 3, 2)
    released = datetime(2026, 3, 3, 8, 30, tzinfo=UTC)
    _store(engine, reference, 150.0, released)

    assert get_series_as_of(engine, SERIES, released - timedelta(seconds=1)) == []
    visible = get_series_as_of(engine, SERIES, released)
    assert [row["reference_date"] for row in visible] == [reference]
    assert visible[0]["value"] == 150.0


def test_no_returned_row_ever_exceeds_the_as_of_instant(engine: Engine) -> None:
    """The core invariant, asserted over a multi-period panel."""
    releases = {
        date(2026, 2, 2): datetime(2026, 2, 3, 8, 30, tzinfo=UTC),
        date(2026, 2, 9): datetime(2026, 2, 10, 8, 30, tzinfo=UTC),
        date(2026, 2, 16): datetime(2026, 2, 17, 8, 30, tzinfo=UTC),
    }
    for index, (reference, released) in enumerate(sorted(releases.items())):
        _store(engine, reference, 100.0 + index, released)

    for as_of in (
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 2, 3, 8, 29, tzinfo=UTC),
        datetime(2026, 2, 10, 8, 30, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    ):
        rows = get_series_as_of(engine, SERIES, as_of)
        assert all(row["available_at"] <= as_of for row in rows)
        expected = {reference for reference, released in releases.items() if released <= as_of}
        assert {row["reference_date"] for row in rows} == expected


def test_a_later_revision_does_not_leak_into_an_earlier_as_of(engine: Engine) -> None:
    """The vintage current at ``as_of`` wins, not the newest one in the table."""
    reference = date(2026, 2, 2)
    first_release = datetime(2026, 2, 3, 8, 30, tzinfo=UTC)
    revision_release = datetime(2026, 2, 17, 8, 30, tzinfo=UTC)
    _store(engine, reference, 150.0, first_release, collected_at=first_release)
    _store(engine, reference, 151.5, revision_release, collected_at=revision_release)

    before = get_series_as_of(engine, SERIES, datetime(2026, 2, 10, tzinfo=UTC))
    assert [row["value"] for row in before] == [150.0], "revision leaked backwards in time"
    after = get_series_as_of(engine, SERIES, datetime(2026, 3, 1, tzinfo=UTC))
    assert [row["value"] for row in after] == [151.5]


@pytest.mark.parametrize("basis", ["inferred", "unknown"])
def test_reconstructed_availability_is_excluded_by_default(engine: Engine, basis: str) -> None:
    """`inferred` and `unknown` are not point-in-time and must not answer silently."""
    reference = date(2026, 2, 2)
    _store(engine, reference, 150.0, datetime(2026, 2, 3, tzinfo=UTC), basis=basis)

    assert get_series_as_of(engine, SERIES, datetime(2026, 3, 1, tzinfo=UTC)) == []
    opted_in = get_series_as_of(
        engine, SERIES, datetime(2026, 3, 1, tzinfo=UTC), bases=AVAILABILITY_BASES
    )
    assert [row["availability_basis"] for row in opted_in] == [basis]


def test_default_bases_are_evidence_backed_only() -> None:
    """Guard the default set itself, not only the query that uses it."""
    assert "inferred" not in POINT_IN_TIME_BASES
    assert "unknown" not in POINT_IN_TIME_BASES
    assert POINT_IN_TIME_BASES <= AVAILABILITY_BASES


def test_unknown_basis_is_rejected(engine: Engine) -> None:
    """A basis outside the vocabulary must fail rather than be stored."""
    with pytest.raises(ValueError, match="Unknown availability bases"):
        get_series_as_of(engine, SERIES, RUN_AT, bases=frozenset({"vibes"}))
