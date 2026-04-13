"""
Champion Model Metadata Store.

Aggregates current champion model info for all 4 models into a single blob
that Backend reads to serve GET /v1/models/current.

Refreshed by training_result_collector after every training completion so
the blob always reflects the latest state.

Blob path: model-artifacts/champions/current.json
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from shared.constants import MODEL_REGISTRY_NAMES, ModelType

logger = logging.getLogger("payswitch-cs.champion_store")

CHAMPIONS_CONTAINER = "model-artifacts"
CHAMPIONS_BLOB_PATH = "champions/current.json"


def build_champion_snapshot(ml_client) -> dict[str, Any]:
    """
    Query Azure ML for latest version of each of the 4 registered models.

    Args:
        ml_client: azure.ai.ml.MLClient instance.

    Returns:
        Dict with 'updated_at' and 'models' list. Each model entry has either
        {model_type, registry_name, version, status, created_at, metrics, tags}
        on success, or {model_type, registry_name, status: "NOT_REGISTERED", error}
        if the model is not in the registry yet.
    """
    snapshot = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "models": [],
    }

    for model_type in ModelType:
        registry_name = MODEL_REGISTRY_NAMES[model_type]
        entry = _build_single_entry(ml_client, model_type, registry_name)
        snapshot["models"].append(entry)

    return snapshot


def _build_single_entry(ml_client, model_type: ModelType, registry_name: str) -> dict[str, Any]:
    """Fetch latest version of one model and return its snapshot entry."""
    try:
        versions = list(ml_client.models.list(name=registry_name))
        if not versions:
            return {
                "model_type": model_type.value,
                "registry_name": registry_name,
                "status": "NOT_REGISTERED",
                "error": "No versions found in Azure ML registry",
            }

        # Pick latest by integer version
        latest = max(versions, key=lambda m: int(m.version))

        # Parse metrics from properties (JSON-serialized by training agents)
        metrics = {}
        raw_metrics = latest.properties.get("metrics") if latest.properties else None
        if raw_metrics:
            try:
                metrics = json.loads(raw_metrics)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to parse metrics JSON for %s v%s", registry_name, latest.version)

        # created_at may be under creation_context.created_at or similar
        created_at = None
        if hasattr(latest, "creation_context") and latest.creation_context:
            created_at = getattr(latest.creation_context, "created_at", None)
            if created_at:
                created_at = str(created_at)

        return {
            "model_type": model_type.value,
            "registry_name": registry_name,
            "version": str(latest.version),
            "status": "CHAMPION",
            "created_at": created_at,
            "metrics": metrics,
            "tags": dict(latest.tags or {}),
        }

    except Exception as exc:
        logger.exception("Failed to fetch champion for %s", registry_name)
        return {
            "model_type": model_type.value,
            "registry_name": registry_name,
            "status": "NOT_REGISTERED",
            "error": f"{type(exc).__name__}: {exc}",
        }


def save_champion_snapshot(blob_service_client, snapshot: dict[str, Any]) -> str:
    """
    Save the champion snapshot to model-artifacts/champions/current.json.

    Uses overwrite=True — this blob is refreshed after every training run
    so the latest state always replaces the previous snapshot.

    Args:
        blob_service_client: azure.storage.blob.BlobServiceClient instance.
        snapshot: Dict produced by build_champion_snapshot().

    Returns:
        Blob path of the saved snapshot.
    """
    container = blob_service_client.get_container_client(CHAMPIONS_CONTAINER)
    body = json.dumps(snapshot, indent=2, default=str)
    container.get_blob_client(CHAMPIONS_BLOB_PATH).upload_blob(body, overwrite=True)
    logger.info("Champion snapshot saved: %s (%d models)", CHAMPIONS_BLOB_PATH, len(snapshot["models"]))
    return CHAMPIONS_BLOB_PATH


def load_champion_snapshot(blob_service_client) -> dict[str, Any] | None:
    """
    Load the current champion snapshot.

    Returns the parsed dict, or None if the blob doesn't exist yet
    (e.g., no training has completed).
    """
    try:
        container = blob_service_client.get_container_client(CHAMPIONS_CONTAINER)
        data = container.get_blob_client(CHAMPIONS_BLOB_PATH).download_blob().readall()
        return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except Exception as exc:
        if "BlobNotFound" in str(exc) or "ResourceNotFoundError" in type(exc).__name__:
            return None
        raise
