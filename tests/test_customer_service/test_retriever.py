"""Tests for customer service agent retriever."""

import importlib.util
import json as _json
import os
import sys
from unittest.mock import MagicMock

import pytest

# Load retriever by file path (avoid collision with other agent modules)
_agent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "customer-service-agent"))
_spec = importlib.util.spec_from_file_location(
    "cs_retriever_for_test",
    os.path.join(_agent_dir, "modules", "retriever.py"),
)
_retriever = importlib.util.module_from_spec(_spec)
sys.modules["cs_retriever_for_test"] = _retriever
_spec.loader.exec_module(_retriever)

retrieve_context = _retriever.retrieve_context


def _make_mock_blob_client(blob_contents: dict):
    """
    Build a BlobServiceClient mock where blob_contents maps blob path → bytes.
    Unknown paths raise BlobNotFound.
    """
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_client.get_container_client.return_value = mock_container

    def get_blob(path):
        mock_blob = MagicMock()
        if path in blob_contents:
            mock_blob.download_blob.return_value.readall.return_value = blob_contents[path]
        else:
            mock_blob.download_blob.side_effect = Exception("BlobNotFound")
        return mock_blob

    mock_container.get_blob_client.side_effect = get_blob
    return mock_client


# ── Champion snapshot always loaded ────────────────────────────────────────

class TestChampionSnapshot:
    def test_returns_snapshot_when_exists(self):
        client = _make_mock_blob_client({
            "champions/current.json": _json.dumps({"updated_at": "2026", "models": []}).encode("utf-8"),
        })
        ctx = retrieve_context(client, question="anything")
        assert ctx["champion_snapshot"] is not None

    def test_returns_none_when_missing(self):
        client = _make_mock_blob_client({})
        ctx = retrieve_context(client, question="anything")
        assert ctx["champion_snapshot"] is None


# ── Decision lookup ────────────────────────────────────────────────────────

class TestDecisionLookup:
    def test_loads_decision_when_id_provided(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()

        client = _make_mock_blob_client({
            f"decisions/{today}/REQ-001.json": _json.dumps(
                {"request_id": "REQ-001", "decision": "APPROVE"}
            ).encode("utf-8"),
        })

        ctx = retrieve_context(client, question="why", decision_id="REQ-001")
        assert ctx["decision"] is not None
        assert ctx["decision"]["decision"] == "APPROVE"

    def test_walks_back_to_find_older_decision(self):
        from datetime import datetime, timedelta, timezone
        two_days_ago = (datetime.now(timezone.utc).date() - timedelta(days=2)).isoformat()

        client = _make_mock_blob_client({
            f"decisions/{two_days_ago}/REQ-old.json": _json.dumps(
                {"request_id": "REQ-old", "decision": "DECLINE"}
            ).encode("utf-8"),
        })

        ctx = retrieve_context(client, question="why", decision_id="REQ-old")
        assert ctx["decision"] is not None

    def test_missing_decision_returns_none_for_that_field(self):
        client = _make_mock_blob_client({})
        ctx = retrieve_context(client, question="why", decision_id="REQ-ghost")
        assert ctx["decision"] is None

    def test_no_decision_id_no_load(self):
        """If user asks about decisions but doesn't provide an ID, add reference note."""
        client = _make_mock_blob_client({})
        ctx = retrieve_context(client, question="Why was the applicant declined?")
        assert ctx["decision"] is None
        assert ctx["reference_notes"] is not None
        assert "decision_id" in ctx["reference_notes"]


# ── Training lookup ────────────────────────────────────────────────────────

class TestTrainingLookup:
    def test_loads_training_when_id_provided(self):
        tid = "TRAIN-2026-001"
        client = _make_mock_blob_client({
            f"training/{tid}/context.json": _json.dumps({"training_upload_id": "abc"}).encode("utf-8"),
            f"training/{tid}/credit_risk.json": _json.dumps({"status": "SUCCESS", "auc": 0.85}).encode("utf-8"),
            f"training/{tid}/fraud_detection.json": _json.dumps({"status": "SUCCESS"}).encode("utf-8"),
        })

        ctx = retrieve_context(client, question="how was training", training_id=tid)
        assert ctx["training_result"] is not None
        assert "credit_risk" in ctx["training_result"]["models"]
        assert "fraud_detection" in ctx["training_result"]["models"]

    def test_missing_training_returns_none(self):
        client = _make_mock_blob_client({})
        ctx = retrieve_context(client, question="train", training_id="TRAIN-ghost")
        assert ctx["training_result"] is None


# ── Intent detection ───────────────────────────────────────────────────────

class TestIntentDetection:
    def test_drift_question_adds_reference_note(self):
        client = _make_mock_blob_client({})
        ctx = retrieve_context(client, question="Is there any feature drift?")
        assert ctx["reference_notes"] is not None
        assert "drift" in ctx["reference_notes"].lower() or "PSI" in ctx["reference_notes"]

    def test_approved_decision_question_detected(self):
        client = _make_mock_blob_client({})
        ctx = retrieve_context(client, question="Why was this applicant approved?")
        # Should have reference notes asking for decision_id
        assert ctx["reference_notes"] is not None
