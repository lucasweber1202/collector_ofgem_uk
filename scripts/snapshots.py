"""Record which raw source file every stored observation actually came from.

Both v0.1 sources replace their published file in place: DESNZ rewrites the
current CSV every week and DEFRA rewrites its machine-readable CSV every
release. Nothing in either URL distinguishes yesterday's file from today's, so
the bytes are hashed and the hash is the snapshot identity. A source that
silently rewrites its own history therefore shows up as a new snapshot row next
to the old one, instead of overwriting the evidence.

Raw files are written to a gitignored local directory. This is deliberately not
a cloud-storage integration: the table records a path and a digest, and moving
the bytes elsewhere later changes `raw_path` only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from scripts.config import RAW_DIR, SCHEMA_NAME, SNAPSHOTS_TABLE

logger = logging.getLogger(__name__)
_TABLE = f"{SCHEMA_NAME}.{SNAPSHOTS_TABLE}"

_COLUMNS = (
    "snapshot_id",
    "source_id",
    "source_url",
    "fetched_at",
    "source_published_date",
    "http_etag",
    "http_last_modified",
    "sha256",
    "byte_size",
    "raw_path",
)

_EXISTS_SQL = text(f"SELECT snapshot_id FROM {_TABLE} WHERE snapshot_id = :snapshot_id")
_INSERT_SQL = text(
    f"INSERT INTO {_TABLE} ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join(f':{column}' for column in _COLUMNS)})"
)


@dataclass(frozen=True)
class Snapshot:
    """One downloaded raw file, identified by the SHA256 of its bytes."""

    snapshot_id: str
    source_id: str
    source_url: str
    fetched_at: datetime
    source_published_date: date | None
    http_etag: str | None
    http_last_modified: str | None
    sha256: str
    byte_size: int
    raw_path: str

    def as_row(self) -> dict[str, Any]:
        """Return the database row for this snapshot."""
        return {column: getattr(self, column) for column in _COLUMNS}


def write_raw_file(source_id: str, filename: str, body: bytes, digest: str) -> Path:
    """Persist raw bytes under ``RAW_DIR/<source_id>/<digest>-<filename>``.

    The digest is part of the name so two editions of the same published file
    never collide on disk, and an already-written snapshot is not rewritten.
    """
    directory = RAW_DIR / source_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest[:16]}-{filename}"
    if not path.exists():
        path.write_bytes(body)
    return path


def build_snapshot(
    source_id: str,
    source_url: str,
    filename: str,
    body: bytes,
    digest: str,
    etag: str | None,
    last_modified: str | None,
    fetched_at: datetime,
    source_published_date: date | None,
) -> Snapshot:
    """Write the raw file to disk and describe it as a snapshot record."""
    path = write_raw_file(source_id, filename, body, digest)
    return Snapshot(
        snapshot_id=digest,
        source_id=source_id,
        source_url=source_url,
        fetched_at=fetched_at,
        source_published_date=source_published_date,
        http_etag=etag,
        http_last_modified=last_modified,
        sha256=digest,
        byte_size=len(body),
        raw_path=str(path),
    )


def upsert_snapshots(conn: Connection, snapshots: list[Snapshot]) -> int:
    """Insert snapshots not already recorded and return how many were new.

    A snapshot row is immutable: the identity is the content digest, so an
    already-present row describes exactly these bytes and is never rewritten.
    This is what makes a rerun against an unchanged source a no-op here too.
    """
    inserted = 0
    for snapshot in snapshots:
        if conn.execute(_EXISTS_SQL, {"snapshot_id": snapshot.snapshot_id}).first() is not None:
            logger.info("Snapshot %s already recorded; no rewrite", snapshot.snapshot_id[:12])
            continue
        conn.execute(_INSERT_SQL, snapshot.as_row())
        inserted += 1
        logger.info(
            "Recorded snapshot %s for %s (%d bytes)",
            snapshot.snapshot_id[:12],
            snapshot.source_id,
            snapshot.byte_size,
        )
    return inserted
