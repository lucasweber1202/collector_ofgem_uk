"""Run one standalone UK inflation predictor collector.

Every repository owns one publisher/source family. Source-specific extraction
lives in scripts.extract; persistence, PIT semantics and logging stay identical
across the predictor fleet.
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine

from scripts.availability import attribute_release, upsert_availability
from scripts.config import LOG_LEVEL, missing_environment, unresolved_credentials
from scripts.db import build_engine
from scripts.extract import collect
from scripts.init_db import init_db
from scripts.metadata import upsert_metadata
from scripts.run_logs import insert_run_log
from scripts.snapshots import upsert_snapshots
from scripts.time_series import WriteResult, upsert_time_series

logger = logging.getLogger("main")
TRANSACTIONAL_DIALECTS = frozenset({"postgresql", "sqlite"})


def _setup_logging(level: str) -> io.StringIO:
    buffer = io.StringIO()
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler(stream=sys.stdout)
    stream_handler.setFormatter(formatter)
    buffer_handler = logging.StreamHandler(stream=buffer)
    buffer_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.ERROR)
    root.addHandler(stream_handler)
    root.addHandler(buffer_handler)
    logging.getLogger("main").setLevel(level.upper())
    logging.getLogger("scripts").setLevel(level.upper())
    return buffer


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect one UK inflation predictor source.")
    parser.add_argument("--log-level", default=LOG_LEVEL)
    return parser.parse_args(argv)


def _availability_rows(
    data: Any, result: WriteResult, collected_at: datetime
) -> list[dict[str, Any]]:
    """Build immutable PIT rows for the vintages written in this run.

    A later revision of an already stored reference period must never reuse the
    original release timestamp. Without explicit revision-release evidence, the
    safe availability instant is when this collector first saw the revised value.
    """
    snapshot_by_key = {
        (observation.series_id, observation.reference_date): observation.snapshot_id
        for observation in data.observations
    }
    rows: list[dict[str, Any]] = []
    for series_id, reference_date, vintage_date in result.written_keys:
        key = (series_id, reference_date, vintage_date)
        if key in result.revised_keys:
            available_at, basis, release_date = collected_at, "first_seen", None
        elif (
            hasattr(data, "availability_by_key")
            and (series_id, reference_date) in data.availability_by_key
        ):
            available_at, basis, release_date = data.availability_by_key[
                (series_id, reference_date)
            ]
        else:
            available_at, basis, release_date = attribute_release(
                reference_date,
                data.releases,
                data.min_lag_days,
                data.max_lag_days,
                data.inferred_lag_days,
            )
            if (
                basis not in {"official_timestamp", "official_date", "archived_release"}
                and series_id in result.preexisting_series
            ):
                available_at, basis, release_date = collected_at, "first_seen", None
        rows.append(
            {
                "series_id": series_id,
                "reference_date": reference_date,
                "vintage_date": vintage_date,
                "release_date": release_date,
                "available_at": available_at,
                "availability_basis": basis,
                "source_snapshot_id": snapshot_by_key[(series_id, reference_date)],
            }
        )
    return rows


def collect_source(engine: Engine) -> None:
    data = collect()
    collected_at = datetime.now(UTC)
    if engine.dialect.name not in TRANSACTIONAL_DIALECTS:
        logger.warning(
            "%s commits statements independently; interrupted Databricks runs are repaired "
            "idempotently by the next run",
            engine.dialect.name,
        )
    with engine.begin() as conn:
        snapshots_written = upsert_snapshots(conn, data.snapshots)
        result = upsert_time_series(conn, data.observations, collected_at)
        availability_rows = _availability_rows(data, result, collected_at)
        availability_written = upsert_availability(conn, availability_rows, collected_at)
        metadata_inserted, metadata_updated = upsert_metadata(conn, data.catalog, collected_at)
    logger.info(
        "result: new_observations=%d new_vintages=%d availability=%d snapshots=%d "
        "metadata_inserted=%d metadata_updated=%d",
        result.new_observations,
        result.new_vintages,
        availability_written,
        snapshots_written,
        metadata_inserted,
        metadata_updated,
    )


def main() -> int:
    missing = missing_environment()
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    for name in unresolved_credentials():
        logger.warning("%s is unset; it must resolve from the runtime context", name)
    engine = build_engine()
    try:
        init_db(engine)
        collect_source(engine)
    finally:
        engine.dispose()
    return 0


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_buffer = _setup_logging(args.log_level)
    started_at = datetime.now(UTC)
    status = "success"
    traceback_text: str | None = None
    return_code = 0
    try:
        return_code = main()
    except Exception:
        status = "error"
        traceback_text = traceback.format_exc()
        logger.exception("Pipeline failed")
        return_code = 1
    finally:
        finished_at = datetime.now(UTC)
        log_engine = None
        try:
            log_engine = build_engine()
            init_db(log_engine)
            insert_run_log(
                log_engine,
                started_at,
                finished_at,
                status,
                log_buffer.getvalue(),
                traceback_text,
            )
        except Exception:
            logger.exception("Could not persist run log")
            return_code = 1
        finally:
            if log_engine is not None:
                log_engine.dispose()
    return return_code


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
