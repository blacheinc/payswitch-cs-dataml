import io
import json
import os
from typing import Any, Dict
from datetime import datetime, timezone

import pandas as pd
from auth_clients import get_blob_service_client


def _normalize_path(path: str) -> str:
    normalized = (path or "").strip()
    if normalized.startswith("silver/"):
        normalized = normalized[len("silver/") :]
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized


def _silver_container_name() -> str:
    return os.getenv("SILVER_CONTAINER_NAME", "silver")


def load_silver_parquet(container_relative_path: str) -> pd.DataFrame:
    blob_name = _normalize_path(container_relative_path)
    if not blob_name:
        raise ValueError("anonymized_silver_path is empty")

    blob_service = get_blob_service_client(
        connection_string_env_vars=(
            "SILVER_STORAGE_CONNECTION_STRING",
            "GOLD_STORAGE_CONNECTION_STRING",
        ),
        account_url_env_vars=(
            "SILVER_STORAGE_ACCOUNT_URL",
            "GOLD_STORAGE_ACCOUNT_URL",
            "AZURE_STORAGE_ACCOUNT_URL",
        ),
    )
    blob_client = blob_service.get_blob_client(
        container=_silver_container_name(), blob=blob_name
    )
    payload = blob_client.download_blob().readall()
    return pd.read_parquet(io.BytesIO(payload))


def load_silver_json(container_relative_path: str) -> Dict[str, Any]:
    blob_name = _normalize_path(container_relative_path)
    if not blob_name:
        raise ValueError("analysis_context_path is empty")

    blob_service = get_blob_service_client(
        connection_string_env_vars=(
            "SILVER_STORAGE_CONNECTION_STRING",
            "GOLD_STORAGE_CONNECTION_STRING",
        ),
        account_url_env_vars=(
            "SILVER_STORAGE_ACCOUNT_URL",
            "GOLD_STORAGE_ACCOUNT_URL",
            "AZURE_STORAGE_ACCOUNT_URL",
        ),
    )
    blob_client = blob_service.get_blob_client(
        container=_silver_container_name(), blob=blob_name
    )
    payload = blob_client.download_blob().readall()
    return json.loads(payload.decode("utf-8"))


def write_inference_reference_parquet(
    row: Dict[str, Any], data_source_id: str, request_id: str
) -> str:
    """
    Legacy DE path (silver container): one anonymized flat row per inference.

    Superseded for ML handoff by ``write_inference_ml_context_json`` under container
    ``model-artifacts`` / ``inference/{request_id}/context.json`` per Payswitch storage layout.
    Kept for reference or ad-hoc debugging; not called from the inference pipeline by default.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blob_name = f"inference/{data_source_id}/{date_str}/{request_id}/{request_id}.parquet"
    df = pd.DataFrame([row])
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    blob_service = get_blob_service_client(
        connection_string_env_vars=(
            "SILVER_STORAGE_CONNECTION_STRING",
            "GOLD_STORAGE_CONNECTION_STRING",
        ),
        account_url_env_vars=(
            "SILVER_STORAGE_ACCOUNT_URL",
            "GOLD_STORAGE_ACCOUNT_URL",
            "AZURE_STORAGE_ACCOUNT_URL",
        ),
    )
    blob_client = blob_service.get_blob_client(container=_silver_container_name(), blob=blob_name)
    blob_client.upload_blob(buf.getvalue(), overwrite=True)
    return blob_name


def write_inference_ml_context_json(handoff_body: Dict[str, Any]) -> str:
    """
    Optional utility: write inference handoff JSON to blob (container default
    ``model-artifacts``, path ``inference/{request_id}/context.json``).

    The live inference HTTP pipeline does **not** call this; ML consumes the same
    payload from Service Bus only. Use for ad-hoc scripts or debugging.
    """
    request_id = str((handoff_body or {}).get("request_id") or "").strip()
    if not request_id:
        raise ValueError("handoff_body.request_id is required")
    container = os.getenv("ML_INFERENCE_ARTIFACTS_CONTAINER", "model-artifacts").strip()
    blob_name = f"inference/{request_id}/context.json"
    raw = json.dumps(handoff_body, default=str).encode("utf-8")
    blob_service = get_blob_service_client(
        connection_string_env_vars=(
            "SILVER_STORAGE_CONNECTION_STRING",
            "GOLD_STORAGE_CONNECTION_STRING",
        ),
        account_url_env_vars=(
            "SILVER_STORAGE_ACCOUNT_URL",
            "GOLD_STORAGE_ACCOUNT_URL",
            "AZURE_STORAGE_ACCOUNT_URL",
        ),
    )
    blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
    blob_client.upload_blob(raw, overwrite=True)
    return f"{container}/{blob_name}"

