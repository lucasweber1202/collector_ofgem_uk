"""Template runtime settings. Rename SCHEMA_NAME when cloning the template."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = ROOT_DIR / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if value and key not in os.environ:
            os.environ[key] = value

SCHEMA_NAME = "collector_ofgem_uk"
CATALOG_NAME = "macrobond_inhouse"
METADATA_TABLE = "metadata"
TIME_SERIES_TABLE = "time_series"
AVAILABILITY_TABLE = "availability"
SNAPSHOTS_TABLE = "source_snapshots"
LOGS_TABLE = "logs"
COUNTRY_CURRENCY = "GBP"
PROD = os.getenv("PROD", "false").lower() in ("1", "true", "yes")
DATABASE_URL = os.getenv("COLLECTOR_DB_URL", "")
RAW_DIR = Path(os.getenv("COLLECTOR_RAW_DIR", str(ROOT_DIR / "_raw")))
if not RAW_DIR.is_absolute():
    RAW_DIR = ROOT_DIR / RAW_DIR
REQUEST_TIMEOUT = float(os.getenv("COLLECTOR_HTTP_TIMEOUT", "60"))
DOWNLOAD_DELAY = float(os.getenv("COLLECTOR_DOWNLOAD_DELAY", "1"))
MAX_RETRIES = int(os.getenv("COLLECTOR_MAX_RETRIES", "3"))
BACKOFF_FACTOR = float(os.getenv("COLLECTOR_BACKOFF_FACTOR", "2"))
RATE_LIMIT_BACKOFF = float(os.getenv("COLLECTOR_RATE_LIMIT_BACKOFF", "20"))
MAX_RETRY_DELAY = float(os.getenv("COLLECTOR_MAX_RETRY_DELAY", "120"))
MAX_DOWNLOAD_BYTES = int(os.getenv("COLLECTOR_MAX_DOWNLOAD_BYTES", str(128 * 1024 * 1024)))
USER_AGENT = os.getenv("COLLECTOR_USER_AGENT", "collector_ofgem_uk/0.1")
LOG_LEVEL = os.getenv("COLLECTOR_LOG_LEVEL", "INFO")
DBX_SERVER_HOSTNAME = os.getenv("DBX_SERVER_HOSTNAME", "")
DBX_HTTP_PATH = os.getenv("DBX_HTTP_PATH", "")
AKV_VAULT_URL = os.getenv("AKV_VAULT_URL", "")
AKV_SECRET_NAME = os.getenv("AKV_SECRET_NAME", "databricks-token")


def missing_environment(prod: bool = PROD) -> list[str]:
    if not prod:
        return [] if DATABASE_URL else ["COLLECTOR_DB_URL"]
    required = {"DBX_SERVER_HOSTNAME": DBX_SERVER_HOSTNAME, "DBX_HTTP_PATH": DBX_HTTP_PATH}
    return sorted(name for name, value in required.items() if not value)


def unresolved_credentials(prod: bool = PROD) -> list[str]:
    if prod and not os.getenv("DATABRICKS_TOKEN") and not AKV_VAULT_URL:
        return ["DATABRICKS_TOKEN", "AKV_VAULT_URL"]
    return []
