"""Tests for orchestrator batch store."""

import json
from unittest.mock import MagicMock

import pytest

from orchestrator.modules.batch_store import (
    BATCH_CONTAINER,
    append_batch_result,
    get_batch_status,
    init_batch_manifest,
    is_batch_complete,
    results_blob_path,
)


def _make_blob_client_with_state(initial_status: dict = None, initial_results: bytes = b""):
    """
    Build a MagicMock blob service client that simulates blob state.
    Returns (mock_blob_client, state_dict) where state_dict holds the mock state.
    """
    state = {
        "status.json": json.dumps(initial_status or {}).encode("utf-8"),
        "results.jsonl": initial_results,
        "manifest.json": b"{}",
    }

    def get_blob_client_factory(path):
        mock_blob = MagicMock()
        # Extract filename from path (e.g. batch/job-123/status.json -> status.json)
        filename = path.split("/")[-1]

        def download_side_effect():
            download = MagicMock()
            download.readall.return_value = state.get(filename, b"")
            return download

        def upload_side_effect(data, overwrite=False):
            if isinstance(data, str):
                state[filename] = data.encode("utf-8")
            else:
                state[filename] = data

        mock_blob.download_blob.side_effect = download_side_effect
        mock_blob.upload_blob.side_effect = upload_side_effect
        return mock_blob

    mock_container = MagicMock()
    mock_container.get_blob_client.side_effect = get_blob_client_factory

    mock_blob_client = MagicMock()
    mock_blob_client.get_container_client.return_value = mock_container

    return mock_blob_client, state


# ── init_batch_manifest ────────────────────────────────────────────────────

class TestInitBatchManifest:
    def test_creates_all_three_blobs(self):
        mock_client, state = _make_blob_client_with_state()

        init_batch_manifest(
            mock_client,
            job_id="job-001",
            total=10,
            models_to_run=["all"],
            requested_at="2026-04-11T00:00:00Z",
        )

        manifest = json.loads(state["manifest.json"])
        assert manifest["job_id"] == "job-001"
        assert manifest["total"] == 10
        assert manifest["models_to_run"] == ["all"]

        status = json.loads(state["status.json"])
        assert status["status"] == "pending"
        assert status["total"] == 10
        assert status["completed"] == 0
        assert status["failed"] == 0

        # results.jsonl should be empty
        assert state["results.jsonl"] == b""

    def test_uses_correct_container(self):
        mock_client, _ = _make_blob_client_with_state()

        init_batch_manifest(
            mock_client,
            job_id="job-x",
            total=1,
            models_to_run=["credit_risk"],
            requested_at="2026-04-11T00:00:00Z",
        )

        mock_client.get_container_client.assert_called_with(BATCH_CONTAINER)


# ── append_batch_result ────────────────────────────────────────────────────

class TestAppendBatchResult:
    def test_appends_to_results_and_increments_completed(self):
        initial_status = {
            "status": "pending",
            "total": 3,
            "completed": 0,
            "failed": 0,
            "updated_at": "2026-04-11T00:00:00Z",
        }
        mock_client, state = _make_blob_client_with_state(initial_status=initial_status)

        processed = append_batch_result(mock_client, "job-001", {"request_id": "REQ-1", "decision": "APPROVE"})

        assert processed == 1
        lines = state["results.jsonl"].decode("utf-8").strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["request_id"] == "REQ-1"

        status = json.loads(state["status.json"])
        assert status["completed"] == 1
        assert status["failed"] == 0
        assert status["status"] == "in_progress"

    def test_marks_complete_when_last_result(self):
        initial_status = {"status": "in_progress", "total": 2, "completed": 1, "failed": 0, "updated_at": ""}
        mock_client, state = _make_blob_client_with_state(
            initial_status=initial_status,
            initial_results=(json.dumps({"request_id": "REQ-0"}) + "\n").encode("utf-8"),
        )

        processed = append_batch_result(mock_client, "job-001", {"request_id": "REQ-1"})

        assert processed == 2
        status = json.loads(state["status.json"])
        assert status["status"] == "complete"
        assert status["completed"] == 2

    def test_appends_multiple_results(self):
        initial_status = {"status": "pending", "total": 5, "completed": 0, "failed": 0, "updated_at": ""}
        mock_client, state = _make_blob_client_with_state(initial_status=initial_status)

        append_batch_result(mock_client, "job-001", {"request_id": "REQ-1"})
        append_batch_result(mock_client, "job-001", {"request_id": "REQ-2"})
        append_batch_result(mock_client, "job-001", {"request_id": "REQ-3"})

        lines = state["results.jsonl"].decode("utf-8").strip().split("\n")
        assert len(lines) == 3
        ids = [json.loads(ln)["request_id"] for ln in lines]
        assert ids == ["REQ-1", "REQ-2", "REQ-3"]

        status = json.loads(state["status.json"])
        assert status["completed"] == 3
        assert status["status"] == "in_progress"

    def test_increments_failed_when_error(self):
        initial_status = {"status": "pending", "total": 2, "completed": 0, "failed": 0, "updated_at": ""}
        mock_client, state = _make_blob_client_with_state(initial_status=initial_status)

        append_batch_result(mock_client, "job-001", {"request_id": "REQ-err", "decision": "ERROR"}, is_error=True)

        status = json.loads(state["status.json"])
        assert status["failed"] == 1
        assert status["completed"] == 0


# ── get_batch_status ───────────────────────────────────────────────────────

class TestGetBatchStatus:
    def test_returns_status_when_exists(self):
        initial_status = {"status": "in_progress", "total": 5, "completed": 2, "failed": 1, "updated_at": ""}
        mock_client, _ = _make_blob_client_with_state(initial_status=initial_status)

        result = get_batch_status(mock_client, "job-001")

        assert result is not None
        assert result["status"] == "in_progress"
        assert result["completed"] == 2

    def test_returns_none_when_not_found(self):
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_blob.download_blob.side_effect = Exception("BlobNotFound")
        mock_container.get_blob_client.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.get_container_client.return_value = mock_container

        result = get_batch_status(mock_client, "job-missing")
        assert result is None


# ── Helpers ────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_is_batch_complete_true(self):
        assert is_batch_complete({"status": "complete"}) is True

    def test_is_batch_complete_false_for_in_progress(self):
        assert is_batch_complete({"status": "in_progress"}) is False

    def test_is_batch_complete_false_for_pending(self):
        assert is_batch_complete({"status": "pending"}) is False

    def test_results_blob_path(self):
        assert results_blob_path("job-001") == "batch/job-001/results.jsonl"
