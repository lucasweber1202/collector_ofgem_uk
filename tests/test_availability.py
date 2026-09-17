"""Release attribution and the immutability of a written availability row."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.availability import (
    AVAILABILITY_BASES,
    attribute_release,
    upsert_availability,
)
from scripts.config import AVAILABILITY_TABLE, SCHEMA_NAME

RELEASES = [
    datetime(2026, 2, 3, 8, 30, tzinfo=UTC),
    datetime(2026, 2, 10, 8, 30, tzinfo=UTC),
    datetime(2026, 2, 24, 8, 30, tzinfo=UTC),
]
RUN_AT = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def test_earliest_release_after_the_period_is_chosen() -> None:
    """Attribution takes the first qualifying release, not the last."""
    available_at, basis, release_date = attribute_release(date(2026, 2, 2), RELEASES, 1, 31, 1)
    assert basis == "official_timestamp"
    assert available_at == RELEASES[0]
    assert release_date == date(2026, 2, 3)


def test_a_missing_release_falls_forward_rather_than_backward() -> None:
    """A gap in the change history delays availability; it never advances it.

    The week of 2026-02-16 has no release of its own here, so the next surviving
    release is used. That is late, which understates the information set, which
    is the safe direction.
    """
    available_at, basis, _ = attribute_release(date(2026, 2, 16), RELEASES, 1, 31, 1)
    assert basis == "official_timestamp"
    assert available_at == RELEASES[2]
    assert available_at.date() > date(2026, 2, 16)


def test_min_lag_zero_lets_a_release_carry_its_own_reference_day() -> None:
    """DEFRA publishes a reference day on that same day; DESNZ never does."""
    same_day = [datetime(2026, 2, 2, 8, 30, tzinfo=UTC)]
    _, defra_basis, _ = attribute_release(date(2026, 2, 2), same_day, 0, 31, 3)
    assert defra_basis == "official_timestamp"
    _, desnz_basis, _ = attribute_release(date(2026, 2, 2), same_day, 1, 31, 1)
    assert desnz_basis == "inferred"


def test_period_before_the_change_history_is_inferred_not_attributed() -> None:
    """A period outside the attribution window must not borrow a distant release."""
    available_at, basis, release_date = attribute_release(date(2010, 5, 3), RELEASES, 1, 31, 1)
    assert basis == "inferred"
    assert release_date is None
    assert available_at.date() == date(2010, 5, 4)
    # Never midnight: an inferred instant must not claim pre-publication timing.
    assert available_at.hour == 12


def test_a_source_without_a_documented_rule_is_unknown_and_never_visible() -> None:
    """`unknown` sorts to the far future so no as-of filter admits it."""
    available_at, basis, release_date = attribute_release(date(2010, 5, 3), RELEASES, 1, 31, None)
    assert basis == "unknown"
    assert release_date is None
    assert available_at.year == datetime.max.year  # noqa: DTZ901


def test_future_reference_date_is_rejected() -> None:
    """A reference period in the future means the source or the clock is wrong."""
    with pytest.raises(ValueError, match="in the future"):
        attribute_release(date(2400, 1, 1), RELEASES, 1, 31, 1)


def test_every_emitted_basis_is_in_the_vocabulary() -> None:
    """Attribution can only ever emit a declared basis."""
    for inferred_lag in (1, None):
        for reference in (date(2026, 2, 2), date(2010, 5, 3)):
            _, basis, _ = attribute_release(reference, RELEASES, 1, 31, inferred_lag)
            assert basis in AVAILABILITY_BASES


def _row(basis: str = "official_timestamp", available_at: datetime = RELEASES[0]) -> dict:
    return {
        "series_id": "SERIES_A_B_C",
        "reference_date": date(2026, 2, 2),
        "vintage_date": date(2026, 2, 3),
        "release_date": available_at.date(),
        "available_at": available_at,
        "availability_basis": basis,
        "source_snapshot_id": "snap",
    }


def test_an_existing_availability_row_is_never_rewritten(engine: Engine) -> None:
    """History of what was knowable must not be revised by a later run."""
    with engine.begin() as conn:
        assert upsert_availability(conn, [_row()], RUN_AT) == 1
    with engine.begin() as conn:
        rewritten = upsert_availability(conn, [_row("inferred", RELEASES[2])], RUN_AT)
    assert rewritten == 0
    with engine.connect() as conn:
        stored = conn.execute(
            text(f"SELECT availability_basis, available_at FROM {SCHEMA_NAME}.{AVAILABILITY_TABLE}")
        ).all()
    assert len(stored) == 1
    assert stored[0][0] == "official_timestamp"


def test_an_unknown_basis_is_refused_before_any_write(engine: Engine) -> None:
    """The vocabulary is enforced at the write boundary, not only at read time."""
    with (
        engine.begin() as conn,
        pytest.raises(ValueError, match="Unknown availability_basis"),
    ):
        upsert_availability(conn, [_row("probably_tuesday")], RUN_AT)
