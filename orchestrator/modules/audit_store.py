"""
Decision Audit Trail Storage.

Persists immutable audit records of every scoring decision per BLD Section 9.3:
- Decision ID, timestamp, model versions, feature vector snapshot
- Final decision code, reason codes + SHAP, DQS
- Retention: 8+ years via blob lifecycle policy

Layout:
    model-artifacts/decisions/{YYYY-MM-DD}/{request_id}.json         # success audits
    model-artifacts/decisions/{YYYY-MM-DD}/{request_id}.error.json   # error audits

Backend reads these blobs directly with SAS/RBAC to serve
GET /v1/decisions/{decisionId} and GET /v1/explainability/{decisionId}.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("payswitch-cs.audit_store")

AUDIT_CONTAINER = "model-artifacts"
DECISIONS_PREFIX = "decisions"
DEFAULT_LOOKBACK_DAYS = 30


def _audit_path(scoring_timestamp: str, request_id: str, error: bool = False) -> str:
    """Compute date-partitioned blob path from a scoring timestamp."""
    # scoring_timestamp is ISO 8601: "2026-04-11T14:32:08.123456+00:00"
    date_str = scoring_timestamp[:10]
    suffix = ".error.json" if error else ".json"
    return f"{DECISIONS_PREFIX}/{date_str}/{request_id}{suffix}"


def persist_decision_audit(blob_service_client, scoring_response) -> str:
    """
    Persist a successful scoring response to the audit trail.

    Uses overwrite=False — Service Bus redelivery can trigger this again
    for the same request_id, and we want audit records to be immutable.
    On duplicate, logs a warning and returns the path without raising.

    Args:
        blob_service_client: azure.storage.blob.BlobServiceClient instance.
        scoring_response: shared.schemas.response_schema.ScoringResponse instance.

    Returns:
        Blob path of the persisted audit record.
    """
    path = _audit_path(scoring_response.scoring_timestamp, scoring_response.request_id)
    body = scoring_response.to_json()

    container = blob_service_client.get_container_client(AUDIT_CONTAINER)
    try:
        container.get_blob_client(path).upload_blob(body, overwrite=False)
        logger.info("Audit persisted: %s (%d bytes)", path, len(body))
    except Exception as exc:
        if "BlobAlreadyExists" in str(exc) or "ResourceExistsError" in type(exc).__name__:
            logger.warning(
                "Audit record already exists for %s — duplicate delivery, skipping overwrite",
                scoring_response.request_id,
            )
        else:
            raise

    return path


def persist_error_audit(
    blob_service_client,
    request_id: str,
    errors: list[str],
    metadata: dict[str, Any],
    scoring_timestamp: Optional[str] = None,
) -> str:
    """
    Persist an error audit record for failed scoring.

    Args:
        blob_service_client: azure.storage.blob.BlobServiceClient instance.
        request_id: The request ID that failed.
        errors: List of error messages.
        metadata: The scoring metadata from the failed request.
        scoring_timestamp: Optional timestamp override (defaults to now).

    Returns:
        Blob path of the persisted error record.
    """
    ts = scoring_timestamp or datetime.now(timezone.utc).isoformat()
    path = _audit_path(ts, request_id, error=True)

    body = json.dumps({
        "request_id": request_id,
        "scoring_timestamp": ts,
        "decision": "ERROR",
        "errors": errors,
        "scoring_metadata": metadata,
    })

    container = blob_service_client.get_container_client(AUDIT_CONTAINER)
    try:
        container.get_blob_client(path).upload_blob(body, overwrite=False)
        logger.info("Error audit persisted: %s", path)
    except Exception as exc:
        if "BlobAlreadyExists" in str(exc) or "ResourceExistsError" in type(exc).__name__:
            logger.warning("Error audit already exists for %s — skipping", request_id)
        else:
            raise

    return path


def load_decision_audit(
    blob_service_client,
    request_id: str,
    max_lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> Optional[dict]:
    """
    Retrieve an audit record by walking back from today.

    Tries each date from today to `today - max_lookback_days`.
    Returns the parsed JSON on first hit, or None if not found.

    Future enhancement: accept an optional date parameter to skip the walk
    when the caller already knows the date.

    Args:
        blob_service_client: azure.storage.blob.BlobServiceClient instance.
        request_id: The decision ID to look up.
        max_lookback_days: How far back to search (default 30).

    Returns:
        Parsed decision record dict, or None if not found.
    """
    container = blob_service_client.get_container_client(AUDIT_CONTAINER)
    today = datetime.now(timezone.utc).date()

    for days_back in range(max_lookback_days + 1):
        date = today - timedelta(days=days_back)
        date_str = date.isoformat()
        path = f"{DECISIONS_PREFIX}/{date_str}/{request_id}.json"
        try:
            data = container.get_blob_client(path).download_blob().readall()
            logger.info("Audit loaded: %s", path)
            return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        except Exception as exc:
            # Not found in this date — keep walking back
            if "BlobNotFound" in str(exc) or "ResourceNotFoundError" in type(exc).__name__:
                continue
            # Unexpected error — re-raise
            raise

    logger.info("Audit not found for %s within %d days", request_id, max_lookback_days)
    return None
