"""Persist one bounded run-log record on success or failure."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts.config import LOGS_TABLE, SCHEMA_NAME

logger = logging.getLogger(__name__)
_TABLE = f"{SCHEMA_NAME}.{LOGS_TABLE}"
_MAX_TEXT = 65535


_INSERT_SQL = text(
    f"INSERT INTO {_TABLE} (started_at, finished_at, status, log_text, traceback) "
    "VALUES (:started_at, :finished_at, :status, :log_text, :traceback)"
)


def _truncate(value: str | None) -> str | None:
    """Bound text columns while making truncation visible."""
    if value is None or len(value) <= _MAX_TEXT:
        return value
    suffix = "\n[..., truncated ...]"
    return value[: _MAX_TEXT - len(suffix)] + suffix


def insert_run_log(
    engine: Engine,
    started_at: datetime,
    finished_at: datetime,
    status: str,
    log_text: str,
    traceback_text: str | None,
) -> None:
    """Insert a run row; logging failures never mask the pipeline result."""
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_SQL,
                {
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "status": status,
                    "log_text": _truncate(log_text) or "",
                    "traceback": _truncate(traceback_text),
                },
            )
    except Exception:
        logger.exception("Could not write run log")
