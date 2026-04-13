"""
Batch Scoring Storage.

Tracks progress and results for async batch scoring jobs.

Blob layout:
    model-artifacts/batch/{job_id}/
        manifest.json     # {job_id, total, requested_at, models_to_run}
        status.json       # {status, completed, failed, total, updated_at}
        results.jsonl     # one ScoringResponse per line (successful scorings)

Backend polls status.json or subscribes to batch-score-complete topic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("payswitch-cs.batch_store")

BATCH_CONTAINER = "model-artifacts"
BATCH_PREFIX = "batch"


def _path(job_id: str, filename: str) -> str:
    return f"{BATCH_PREFIX}/{job_id}/{filename}"


def init_batch_manifest(
    blob_service_client,
    job_id: str,
    total: int,
    models_to_run: list[str],
    requested_at: str,
) -> None:
    """
    Create the manifest and initial status blobs for a new batch job.

    Args:
        blob_service_client: BlobServiceClient instance.
        job_id: Unique batch job ID.
        total: Total number of applicants in the batch.
        models_to_run: Which models to run for each applicant.
        requested_at: ISO timestamp of when the batch was requested.
    """
    container = blob_service_client.get_container_client(BATCH_CONTAINER)

    manifest = {
        "job_id": job_id,
        "total": total,
        "requested_at": requested_at,
        "models_to_run": models_to_run,
    }
    container.get_blob_client(_path(job_id, "manifest.json")).upload_blob(
        json.dumps(manifest), overwrite=True,
    )

    status = {
        "status": "pending",
        "total": total,
        "completed": 0,
        "failed": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    container.get_blob_client(_path(job_id, "status.json")).upload_blob(
        json.dumps(status), overwrite=True,
    )

    # Initialize empty results file so append later doesn't fail
    container.get_blob_client(_path(job_id, "results.jsonl")).upload_blob(
        b"", overwrite=True,
    )

    logger.info("Batch manifest initialized: job=%s total=%d", job_id, total)


def append_batch_result(
    blob_service_client,
    job_id: str,
    result: dict[str, Any],
    is_error: bool = False,
) -> int:
    """
    Append one scoring result to the batch's results.jsonl and update status.

    Uses read-modify-write on the JSONL blob — acceptable for moderate batch
    sizes (up to ~1000 applicants). For larger batches, prefer append blobs.

    Args:
        blob_service_client: BlobServiceClient instance.
        job_id: Batch job ID.
        result: Full ScoringResponse dict (or error dict).
        is_error: Whether this result represents a failure.

    Returns:
        New completed count (total successful + failed results).
    """
    container = blob_service_client.get_container_client(BATCH_CONTAINER)

    # Append to results.jsonl
    results_blob = container.get_blob_client(_path(job_id, "results.jsonl"))
    try:
        existing = results_blob.download_blob().readall()
        if isinstance(existing, bytes):
            existing_text = existing.decode("utf-8")
        else:
            existing_text = existing
    except Exception:
        existing_text = ""

    new_line = json.dumps(result) + "\n"
    updated = existing_text + new_line
    results_blob.upload_blob(updated.encode("utf-8"), overwrite=True)

    # Update status
    status_blob = container.get_blob_client(_path(job_id, "status.json"))
    status = json.loads(status_blob.download_blob().readall())

    if is_error:
        status["failed"] = status.get("failed", 0) + 1
    else:
        status["completed"] = status.get("completed", 0) + 1

    total_processed = status["completed"] + status["failed"]
    if total_processed >= status["total"]:
        status["status"] = "complete"
    else:
        status["status"] = "in_progress"

    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    status_blob.upload_blob(json.dumps(status), overwrite=True)

    logger.info(
        "Batch progress: job=%s completed=%d failed=%d total=%d",
        job_id, status["completed"], status["failed"], status["total"],
    )

    return total_processed


def get_batch_status(blob_service_client, job_id: str) -> dict[str, Any] | None:
    """Read the current status of a batch job."""
    container = blob_service_client.get_container_client(BATCH_CONTAINER)
    try:
        data = container.get_blob_client(_path(job_id, "status.json")).download_blob().readall()
        return json.loads(data)
    except Exception as exc:
        if "BlobNotFound" in str(exc) or "ResourceNotFoundError" in type(exc).__name__:
            return None
        raise


def is_batch_complete(status: dict[str, Any]) -> bool:
    """Check if a batch status represents completion."""
    return status.get("status") == "complete"


def results_blob_path(job_id: str) -> str:
    """Return the blob path for a batch's results.jsonl file."""
    return _path(job_id, "results.jsonl")
