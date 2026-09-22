"""Detect and migrate databases created by a pre-canonical DDL.

``CREATE TABLE IF NOT EXISTS`` is not a migration. A database created before
the standardized ``metadata`` shape was enforced still carries its extra
columns, and because those columns are ``NOT NULL`` with no default, the
canonical INSERT -- which no longer supplies them -- fails outright. The old
database does not "mostly work"; it stops working, and it must not be allowed
to look healthy either.

So every run introspects the live ``metadata`` table and compares it with the
canonical column set:

* no drift                       -- silent no-op, costs one catalog read;
* drift, safely removable        -- archive first if the data is not already
                                    preserved elsewhere, then drop the column;
* drift, not safely removable    -- refuse to run and print the exact runbook.

Nothing is ever deleted before its contents are preserved, and no path here
guesses: when the platform cannot drop a column without risk, this module
fails loudly instead of degrading quietly.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from scripts.config import METADATA_TABLE, SCHEMA_NAME

logger = logging.getLogger(__name__)

# The canonical metadata columns (GUIDELINES.md 3). Anything else found on a
# live table is drift from a pre-canonical DDL.
CANONICAL_METADATA_COLUMNS: tuple[str, ...] = (
    "series_id",
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
    "collected_at",
)

# Dialects where dropping a column is a safe, supported, in-place operation.
# Databricks is deliberately absent: DROP COLUMN there requires Delta column
# mapping to be enabled on the table, and silently rewriting a production
# table is exactly the destructive act this module refuses to take on its own.
SAFE_DROP_DIALECTS = frozenset({"postgresql", "sqlite"})

# Legacy columns whose contents are already preserved in a sidecar, so dropping
# them from `metadata` loses nothing. `source_id` is the fleet case: it is the
# source_registry key and every row of it also lives in `source_snapshots`.
ALREADY_ARCHIVED: frozenset[str] = frozenset({"source_id"})


def live_columns(conn: Connection, table: str, schema: str = SCHEMA_NAME) -> list[str]:
    """Column names of a live table, or [] when the table does not exist yet."""
    inspector = inspect(conn)
    try:
        if not inspector.has_table(table, schema=schema):
            return []
        return [column["name"] for column in inspector.get_columns(table, schema=schema)]
    except SQLAlchemyError:  # pragma: no cover - dialect without full reflection
        logger.warning(
            "Could not introspect %s.%s; skipping legacy-schema detection", schema, table
        )
        return []


def detect_legacy_metadata_columns(conn: Connection) -> list[str]:
    """Columns present on the live metadata table that the template forbids."""
    present = live_columns(conn, METADATA_TABLE)
    if not present:
        return []
    return [column for column in present if column not in CANONICAL_METADATA_COLUMNS]


def _archive_before_drop(conn: Connection, columns: list[str], archive: dict[str, str]) -> None:
    """Copy legacy column data into its sidecar and verify the row counts match.

    ``archive`` maps a legacy metadata column to the sidecar table that should
    own it. The copy is keyed on ``series_id``, and a count mismatch aborts the
    migration before anything is dropped.
    """
    targets = {archive[column] for column in columns if column in archive}
    for target in sorted(targets):
        owned = sorted(column for column in columns if archive.get(column) == target)
        target_columns = set(live_columns(conn, target))
        missing = [column for column in owned if column not in target_columns]
        if missing:
            raise RuntimeError(
                f"Cannot archive {missing} into {SCHEMA_NAME}.{target}: "
                "the sidecar does not declare those columns. Run init_db first."
            )
        column_list = ", ".join(owned)
        source_count = conn.execute(
            text(f"SELECT COUNT(*) FROM {SCHEMA_NAME}.{METADATA_TABLE}")
        ).scalar_one()
        conn.execute(
            text(
                f"UPDATE {SCHEMA_NAME}.{target} AS sidecar SET "
                + ", ".join(
                    f"{column} = (SELECT m.{column} FROM {SCHEMA_NAME}.{METADATA_TABLE} m "
                    f"WHERE m.series_id = sidecar.series_id)"
                    for column in owned
                )
                + f" WHERE EXISTS (SELECT 1 FROM {SCHEMA_NAME}.{METADATA_TABLE} m "
                "WHERE m.series_id = sidecar.series_id)"
            )
        )
        copied = conn.execute(
            text(
                f"SELECT COUNT(*) FROM {SCHEMA_NAME}.{target} sidecar "
                f"WHERE EXISTS (SELECT 1 FROM {SCHEMA_NAME}.{METADATA_TABLE} m "
                "WHERE m.series_id = sidecar.series_id)"
            )
        ).scalar_one()
        logger.info(
            "Archived %s from metadata into %s (%d/%d series matched)",
            column_list,
            target,
            copied,
            source_count,
        )
        if copied < source_count:
            raise RuntimeError(
                f"Refusing to drop {owned}: only {copied} of {source_count} metadata "
                f"series have a matching {target} row. Reconcile the sidecar first."
            )


def _runbook(columns: list[str]) -> str:
    statements = "\n".join(
        f"  ALTER TABLE {SCHEMA_NAME}.{METADATA_TABLE} DROP COLUMN {column};" for column in columns
    )
    return (
        f"Legacy schema detected on {SCHEMA_NAME}.{METADATA_TABLE}. "
        "Safe automatic migration is not possible on this platform.\n"
        f"Non-canonical columns still present: {', '.join(columns)}\n"
        "These columns are NOT NULL and the canonical INSERT no longer supplies "
        "them, so this collector cannot write until the table is migrated.\n\n"
        "Runbook -- preserve the data, then remove the columns:\n"
        f"  1. Confirm every value is preserved in its sidecar "
        f"(source_snapshots / vendor_provenance) for all series_id.\n"
        "  2. On Delta, enable column mapping before dropping:\n"
        f"     ALTER TABLE {SCHEMA_NAME}.{METADATA_TABLE} SET TBLPROPERTIES ("
        "'delta.columnMapping.mode' = 'name', 'delta.minReaderVersion' = '2', "
        "'delta.minWriterVersion' = '5');\n"
        "  3. Then:\n"
        f"{statements}\n"
        "  Alternatively, create a canonical replacement table, copy the "
        "canonical columns, verify counts, and swap by rename."
    )


def migrate_legacy_metadata(conn: Connection, archive: dict[str, str] | None = None) -> list[str]:
    """Bring a pre-canonical ``metadata`` table up to the standardized shape.

    Returns the columns removed (empty when the schema was already canonical).
    Raises with an operational runbook when the drift cannot be repaired safely.
    """
    legacy = detect_legacy_metadata_columns(conn)
    if not legacy:
        return []

    logger.warning(
        "Legacy metadata columns detected on %s.%s: %s",
        SCHEMA_NAME,
        METADATA_TABLE,
        ", ".join(legacy),
    )

    if conn.dialect.name not in SAFE_DROP_DIALECTS:
        raise RuntimeError(_runbook(legacy))

    archive = archive or {}
    needs_archive = [
        column for column in legacy if column not in ALREADY_ARCHIVED and column in archive
    ]
    unhandled = [
        column for column in legacy if column not in ALREADY_ARCHIVED and column not in archive
    ]
    if unhandled:
        raise RuntimeError(
            _runbook(legacy) + f"\n\nNo archive target is declared for: {', '.join(unhandled)}. "
            "Dropping them would lose data, so this run refuses to continue."
        )

    if needs_archive:
        _archive_before_drop(conn, needs_archive, archive)

    for column in legacy:
        conn.execute(text(f"ALTER TABLE {SCHEMA_NAME}.{METADATA_TABLE} DROP COLUMN {column}"))
        logger.info("Dropped legacy metadata column %s", column)

    remaining = detect_legacy_metadata_columns(conn)
    if remaining:
        raise RuntimeError(
            f"Migration incomplete: {', '.join(remaining)} still present on "
            f"{SCHEMA_NAME}.{METADATA_TABLE}"
        )
    logger.info("Legacy metadata migration complete: removed %s", ", ".join(legacy))
    return legacy
