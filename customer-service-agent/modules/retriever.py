"""
Context retriever for the Customer Service Agent.

Fetches relevant blobs from the model-artifacts container based on what the
user is asking about. Supports:
- Decision records (by decision_id, walks back up to N days)
- Training results (by training_id, per-model JSON files)
- Champion snapshot (always included — lightweight context)

Question-intent detection is simple keyword matching for now. Future:
embedding-based semantic search across the audit trail.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("payswitch-cs.customer_service.retriever")

ARTIFACTS_CONTAINER = "model-artifacts"
DEFAULT_LOOKBACK_DAYS = 30


DECISION_KEYWORDS = ("decision", "declined", "approved", "refer", "fraud_hold", "approve", "decline", "score")
TRAINING_KEYWORDS = ("train", "model", "auc", "retrain", "version", "champion", "challenger", "metrics")
DRIFT_KEYWORDS = ("drift", "psi", "distribution", "shift")


def retrieve_context(
    blob_service_client,
    question: str,
    decision_id: Optional[str] = None,
    training_id: Optional[str] = None,
    max_lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """
    Fetch all relevant context for answering a user question.

    Args:
        blob_service_client: azure.storage.blob.BlobServiceClient instance.
        question: The natural-language question.
        decision_id: Optional — if supplied, load that specific decision.
        training_id: Optional — if supplied, load that specific training run.
        max_lookback_days: How far back to search for decision blobs.

    Returns:
        Dict with keys: decision, training_result, champion_snapshot, reference_notes.
        Any individual field may be None if not found or not relevant.
    """
    container = blob_service_client.get_container_client(ARTIFACTS_CONTAINER)
    question_lower = (question or "").lower()
    context: dict[str, Any] = {
        "decision": None,
        "training_result": None,
        "champion_snapshot": None,
        "reference_notes": None,
    }

    # Always include champion snapshot — it's small and useful baseline context
    context["champion_snapshot"] = _load_champion_snapshot(container)

    # Decision lookup (explicit decision_id OR question mentions decisions)
    wants_decision = decision_id or any(kw in question_lower for kw in DECISION_KEYWORDS)
    if decision_id and wants_decision:
        context["decision"] = _load_decision(container, decision_id, max_lookback_days)
    elif wants_decision and not decision_id:
        context["reference_notes"] = (
            "User asked about a decision but did not provide a decision_id. "
            "Ask them for the specific request_id to look up."
        )

    # Training lookup (explicit training_id OR question mentions training)
    wants_training = training_id or any(kw in question_lower for kw in TRAINING_KEYWORDS)
    if training_id and wants_training:
        context["training_result"] = _load_training_results(container, training_id)
    elif wants_training and not training_id:
        notes = context.get("reference_notes") or ""
        notes += " User asked about training but did not provide a training_id. The champion snapshot shows the latest versions."
        context["reference_notes"] = notes.strip()

    # Drift questions — add a stub note for now
    if any(kw in question_lower for kw in DRIFT_KEYWORDS):
        notes = context.get("reference_notes") or ""
        notes += " Drift monitoring runs weekly; PSI > 0.20 on any Group A feature triggers retraining."
        context["reference_notes"] = notes.strip()

    return context


def _load_champion_snapshot(container) -> Optional[dict]:
    """Load champions/current.json if it exists."""
    try:
        data = container.get_blob_client("champions/current.json").download_blob().readall()
        return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except Exception as exc:
        if "BlobNotFound" in str(exc) or "ResourceNotFoundError" in type(exc).__name__:
            logger.info("champions/current.json not found — no training has run yet")
            return None
        logger.warning("Failed to load champion snapshot: %s", exc)
        return None


def _load_decision(container, decision_id: str, max_lookback_days: int) -> Optional[dict]:
    """Walk back from today checking decisions/{date}/{decision_id}.json."""
    today = datetime.now(timezone.utc).date()
    for days_back in range(max_lookback_days + 1):
        date = today - timedelta(days=days_back)
        path = f"decisions/{date.isoformat()}/{decision_id}.json"
        try:
            data = container.get_blob_client(path).download_blob().readall()
            return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        except Exception as exc:
            if "BlobNotFound" in str(exc) or "ResourceNotFoundError" in type(exc).__name__:
                continue
            logger.warning("Unexpected error loading %s: %s", path, exc)
            continue

    logger.info("Decision %s not found within %d days", decision_id, max_lookback_days)
    return None


def _load_training_results(container, training_id: str) -> Optional[dict]:
    """Load all per-model training result blobs for a training_id."""
    results: dict[str, Any] = {"training_id": training_id, "models": {}}

    # Load context
    try:
        ctx_data = container.get_blob_client(f"training/{training_id}/context.json").download_blob().readall()
        results["context"] = json.loads(ctx_data.decode("utf-8") if isinstance(ctx_data, bytes) else ctx_data)
    except Exception:
        pass

    # Load per-model results
    for model_type in ("credit_risk", "fraud_detection", "loan_amount", "income_verification"):
        try:
            data = container.get_blob_client(f"training/{training_id}/{model_type}.json").download_blob().readall()
            results["models"][model_type] = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        except Exception:
            continue  # Model may not have been trained in this run

    if not results["models"] and not results.get("context"):
        logger.info("No training data found for %s", training_id)
        return None

    return results
