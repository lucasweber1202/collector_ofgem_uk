"""Databricks engine factory with context, environment, and Key Vault auth."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from scripts.config import AKV_SECRET_NAME, AKV_VAULT_URL, DBX_HTTP_PATH, DBX_SERVER_HOSTNAME


def _get_token_from_databricks_context() -> str | None:
    """Try to obtain a token from a Databricks notebook or job context."""
    try:
        from pyspark.dbutils import DBUtils  # type: ignore[import-not-found]
        from pyspark.sql import SparkSession  # type: ignore[import-not-found]

        spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
        token_opt = (
            DBUtils(spark).notebook.entry_point.getDbutils().notebook().getContext().apiToken()
        )
        if token_opt.isDefined():
            token = token_opt.get()
            return str(token) if token else None
    except Exception:  # noqa: BLE001 -- Databricks context APIs vary by runtime.
        return None
    return None


def _get_databricks_token() -> str:
    """Resolve a Databricks token without exposing it in logs."""
    token = _get_token_from_databricks_context() or os.getenv("DATABRICKS_TOKEN")
    if token:
        return token
    if not AKV_VAULT_URL:
        raise RuntimeError("No Databricks context token, DATABRICKS_TOKEN, or AKV_VAULT_URL")
    import azure.identity
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(AKV_VAULT_URL, azure.identity.DefaultAzureCredential())
    token = client.get_secret(AKV_SECRET_NAME).value
    if not isinstance(token, str) or not token:
        raise RuntimeError("Azure Key Vault returned an empty Databricks token")
    return token


def get_orm_engine(catalog: str, schema: str) -> Engine:
    """Return a SQLAlchemy engine connected to Databricks."""
    if not DBX_SERVER_HOSTNAME or not DBX_HTTP_PATH:
        raise RuntimeError("DBX_SERVER_HOSTNAME and DBX_HTTP_PATH are required in PROD")
    token = _get_databricks_token()
    return create_engine(
        f"databricks://token:{token}@{DBX_SERVER_HOSTNAME}"
        f"?http_path={DBX_HTTP_PATH}&catalog={catalog}&schema={schema}"
    )
