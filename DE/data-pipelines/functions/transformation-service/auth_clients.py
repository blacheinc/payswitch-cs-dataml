"""Factory helpers for BlobServiceClient and ServiceBusClient from env (SAS or Azure AD)."""

from __future__ import annotations

import os
from typing import Iterable

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient
from azure.storage.blob import BlobServiceClient


def _first_env(env_vars: Iterable[str]) -> str:
    for name in env_vars:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def _normalize_service_bus_fqdn(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.rstrip("/")
    if "." not in value:
        value = f"{value}.servicebus.windows.net"
    return value


def _normalize_storage_account_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if value.startswith("https://"):
        return value.rstrip("/")
    return f"https://{value}.blob.core.windows.net"


def get_service_bus_client(
    *,
    connection_string_env_vars: Iterable[str],
    namespace_env_vars: Iterable[str],
) -> ServiceBusClient:
    conn = _first_env(connection_string_env_vars)
    if conn:
        return ServiceBusClient.from_connection_string(conn)

    fqdn = _normalize_service_bus_fqdn(_first_env(namespace_env_vars))
    if fqdn:
        return ServiceBusClient(
            fully_qualified_namespace=fqdn,
            credential=DefaultAzureCredential(),
        )
    raise ValueError(
        "Missing Service Bus configuration. Set a connection string or namespace/FQDN env var."
    )


def get_blob_service_client(
    *,
    connection_string_env_vars: Iterable[str],
    account_url_env_vars: Iterable[str],
) -> BlobServiceClient:
    conn = _first_env(connection_string_env_vars)
    if conn:
        return BlobServiceClient.from_connection_string(conn)

    account_url = _normalize_storage_account_url(_first_env(account_url_env_vars))
    if account_url:
        return BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
    raise ValueError(
        "Missing Blob Storage configuration. Set a connection string or account URL/name env var."
    )

