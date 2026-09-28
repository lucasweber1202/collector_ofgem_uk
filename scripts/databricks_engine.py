"""Databricks engine factory.

Inlines the corporate get_orm_engine logic so we don't need the full
kinea_database package (which pulls databricks-connect<14 → numpy<2,
incompatible with Python 3.14).

Requirements: azure-identity, azure-keyvault-secrets, databricks-sqlalchemy.
"""

from __future__ import annotations

import os

import azure.identity
from azure.keyvault.secrets import SecretClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from scripts.config import (
    AKV_SECRET_NAME,
    AKV_VAULT_URL,
    DBX_HTTP_PATH,
    DBX_SERVER_HOSTNAME,
)


def _get_token_from_databricks_context() -> str | None:
    """Try to obtain the current Databricks API token from notebook/job context.

    Works when running inside Databricks notebook/job environments where
    dbutils notebook context exposes apiToken.
    """
    try:
        from pyspark.dbutils import DBUtils  # type: ignore
        from pyspark.sql import SparkSession

        spark = SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
        dbutils = DBUtils(spark)

        ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
        token_opt = ctx.apiToken()

        # Java/Scala Optional-like object
        if token_opt.isDefined():
            token = token_opt.get()
            if token:
                return str(token)
    except Exception:
        pass

    # Fallback para outros runtimes/layouts do Databricks
    try:
        token = (
            dbutils.notebook.entry_point.getDbutils()  # type: ignore[name-defined]
            .notebook()
            .getContext()
            .apiToken()
            .get()
        )
        if token:
            return str(token)
    except Exception:
        pass

    return None


def _get_databricks_token() -> str:
    """Resolve Databricks token in priority order:
    1) Databricks notebook/job context
    2) Environment variable DATABRICKS_TOKEN
    3) Azure Key Vault
    """
    token = _get_token_from_databricks_context()
    if token:
        return token

    token = os.getenv("DATABRICKS_TOKEN")
    if token:
        return token

    if not AKV_VAULT_URL:
        raise RuntimeError(
            "Could not resolve Databricks token from Databricks context, "
            "DATABRICKS_TOKEN env var, or Azure Key Vault "
            "(AKV_VAULT_URL is empty)."
        )

    azure_credential = azure.identity.DefaultAzureCredential()
    secret_client = SecretClient(
        vault_url=AKV_VAULT_URL,
        credential=azure_credential,
    )
    secret = secret_client.get_secret(AKV_SECRET_NAME)
    token = secret.value

    if not isinstance(token, str) or not token:
        raise RuntimeError("Azure Key Vault returned an empty Databricks token.")

    return token


def get_orm_engine(catalog: str, schema: str) -> Engine:
    """Return a SQLAlchemy engine connected to Databricks."""
    if not DBX_SERVER_HOSTNAME or not DBX_HTTP_PATH:
        raise RuntimeError(
            "DBX_SERVER_HOSTNAME and DBX_HTTP_PATH must be set in .env or "
            "environment when PROD=True."
        )

    token = _get_databricks_token()

    engine: Engine = create_engine(
        f"databricks://token:{token}@{DBX_SERVER_HOSTNAME}?"
        f"http_path={DBX_HTTP_PATH}&catalog={catalog}&schema={schema}",
    )
    return engine
