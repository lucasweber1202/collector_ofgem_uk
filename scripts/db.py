"""Build the local PostgreSQL or production Databricks SQLAlchemy engine."""

from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url

from scripts.config import CATALOG_NAME, DATABASE_URL, PROD, SCHEMA_NAME

logger = logging.getLogger(__name__)


def build_engine() -> Engine:
    if PROD:
        from scripts.databricks_engine import get_orm_engine

        return get_orm_engine(CATALOG_NAME, SCHEMA_NAME)
    if not DATABASE_URL:
        raise RuntimeError("COLLECTOR_DB_URL is required when PROD is false")
    url = make_url(DATABASE_URL)
    logger.info("Connecting to %s", url.render_as_string(hide_password=True))
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)
