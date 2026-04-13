"""Tests for orchestrator audit store."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from orchestrator.modules.audit_store import (
    AUDIT_CONTAINER,
    _audit_path,
    load_decision_audit,
    persist_decision_audit,
    persist_error_audit,
)
from shared.schemas.response_schema import (
    CreditRiskResponse,
    FraudDetectionResponse,
    ScoringMetadata,
    ScoringResponse,
)


def _make_scoring_response(
    request_id: str = "REQ-test-001",
    timestamp: str = "2026-04-11T14:32:08.123456+00:00",
    decision: str = "APPROVE",
) -> ScoringResponse:
    """Build a minimal valid ScoringResponse for tests."""
    return ScoringResponse(
        request_id=request_id,
        scoring_timestamp=timestamp,
        decision=decision,
        condition_applied=[],
        credit_risk=CreditRiskResponse(
            probability_of_default=0.15,
            pd_confidence=0.85,
            risk_tier="LOW",
            shap_contributions=[],
            decision_reason_codes=[],
            model_version="7",
        ),
        fraud_detection=FraudDetectionResponse(
            fraud_anomaly_score=0.02,
            fraud_risk_flag="LOW",
            model_version="4",
        ),
        loan_amount=None,
        income_verification=None,
        scoring_metadata=ScoringMetadata(
            credit_score=720,
            score_grade="B",
            data_quality_score=0.95,
            bureau_hit_status="HIT",
            product_source="45+49",
            applicant_age_at_application=32,
            credit_age_months_at_application=60,
        ),
        refer_reasons=[],
    )


# ── _audit_path ────────────────────────────────────────────────────────────

class TestAuditPath:
    def test_success_path(self):
        path = _audit_path("2026-04-11T14:32:08.123456+00:00", "REQ-001")
        assert path == "decisions/2026-04-11/REQ-001.json"

    def test_error_path(self):
        path = _audit_path("2026-04-11T14:32:08.123456+00:00", "REQ-001", error=True)
        assert path == "decisions/2026-04-11/REQ-001.error.json"

    def test_different_date(self):
        path = _audit_path("2026-12-31T23:59:59+00:00", "REQ-xyz")
        assert path == "decisions/2026-12-31/REQ-xyz.json"


# ── persist_decision_audit ─────────────────────────────────────────────────

class TestPersistDecisionAudit:
    def test_uploads_to_correct_path(self):
        mock_blob_client = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob

        response = _make_scoring_response(request_id="REQ-abc", timestamp="2026-04-11T12:00:00+00:00")
        path = persist_decision_audit(mock_blob_client, response)

        assert path == "decisions/2026-04-11/REQ-abc.json"
        mock_blob_client.get_container_client.assert_called_once_with(AUDIT_CONTAINER)
        mock_container.get_blob_client.assert_called_once_with("decisions/2026-04-11/REQ-abc.json")
        mock_blob.upload_blob.assert_called_once()
        # Must pass overwrite=False for immutability
        _, kwargs = mock_blob.upload_blob.call_args
        assert kwargs.get("overwrite") is False

    def test_payload_is_json_serialized_scoring_response(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        response = _make_scoring_response(request_id="REQ-xyz", decision="DECLINE")
        persist_decision_audit(mock_blob_client, response)

        args, _ = mock_blob.upload_blob.call_args
        body = json.loads(args[0])
        assert body["request_id"] == "REQ-xyz"
        assert body["decision"] == "DECLINE"
        assert "credit_risk" in body

    def test_swallows_blob_already_exists(self):
        """Duplicate Service Bus delivery should not raise."""
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob.upload_blob.side_effect = Exception("BlobAlreadyExists: The blob already exists")
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        response = _make_scoring_response()
        # Should not raise
        path = persist_decision_audit(mock_blob_client, response)
        assert path.endswith(".json")

    def test_raises_on_unexpected_error(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob.upload_blob.side_effect = Exception("InternalServerError")
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        response = _make_scoring_response()
        with pytest.raises(Exception, match="InternalServerError"):
            persist_decision_audit(mock_blob_client, response)


# ── persist_error_audit ────────────────────────────────────────────────────

class TestPersistErrorAudit:
    def test_writes_to_error_path(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        path = persist_error_audit(
            mock_blob_client,
            request_id="REQ-fail-001",
            errors=["Invalid feature"],
            metadata={"credit_score": 0},
            scoring_timestamp="2026-04-11T14:00:00+00:00",
        )

        assert path == "decisions/2026-04-11/REQ-fail-001.error.json"
        mock_blob.upload_blob.assert_called_once()

    def test_payload_contains_errors(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        persist_error_audit(
            mock_blob_client,
            request_id="REQ-bad",
            errors=["Missing 'applicant_age'", "Score grade invalid"],
            metadata={"foo": "bar"},
            scoring_timestamp="2026-04-11T10:00:00+00:00",
        )

        args, _ = mock_blob.upload_blob.call_args
        body = json.loads(args[0])
        assert body["decision"] == "ERROR"
        assert body["errors"] == ["Missing 'applicant_age'", "Score grade invalid"]
        assert body["scoring_metadata"] == {"foo": "bar"}

    def test_defaults_timestamp_to_now_when_not_provided(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        path = persist_error_audit(
            mock_blob_client,
            request_id="REQ-nowts",
            errors=["x"],
            metadata={},
        )

        # Path should include today's date
        today = datetime.now(timezone.utc).date().isoformat()
        assert today in path


# ── load_decision_audit ────────────────────────────────────────────────────

class TestLoadDecisionAudit:
    def test_returns_decision_found_today(self):
        mock_blob_client = MagicMock()
        mock_container = MagicMock()
        mock_blob_client.get_container_client.return_value = mock_container

        mock_blob = MagicMock()
        mock_blob.download_blob.return_value.readall.return_value = b'{"request_id": "REQ-001", "decision": "APPROVE"}'
        mock_container.get_blob_client.return_value = mock_blob

        result = load_decision_audit(mock_blob_client, "REQ-001")
        assert result is not None
        assert result["decision"] == "APPROVE"

    def test_returns_none_when_not_found_in_window(self):
        mock_blob_client = MagicMock()
        mock_container = MagicMock()
        mock_blob_client.get_container_client.return_value = mock_container

        mock_blob = MagicMock()
        # Every download raises BlobNotFound
        mock_blob.download_blob.side_effect = Exception("BlobNotFound: The specified blob does not exist")
        mock_container.get_blob_client.return_value = mock_blob

        result = load_decision_audit(mock_blob_client, "REQ-missing", max_lookback_days=3)
        assert result is None
        # Should have tried 4 dates (today + 3 days back)
        assert mock_container.get_blob_client.call_count == 4

    def test_walks_back_multiple_days(self):
        """Finds a decision that's 2 days old."""
        mock_blob_client = MagicMock()
        mock_container = MagicMock()
        mock_blob_client.get_container_client.return_value = mock_container

        call_count = {"n": 0}

        def make_blob_client(path):
            mock_blob = MagicMock()
            call_count["n"] += 1
            if call_count["n"] < 3:
                # First 2 calls (today, yesterday) raise
                mock_blob.download_blob.side_effect = Exception("BlobNotFound")
            else:
                # Third call (2 days ago) succeeds
                mock_blob.download_blob.return_value.readall.return_value = b'{"request_id": "REQ-old"}'
            return mock_blob

        mock_container.get_blob_client.side_effect = make_blob_client

        result = load_decision_audit(mock_blob_client, "REQ-old")
        assert result is not None
        assert result["request_id"] == "REQ-old"
        assert call_count["n"] == 3

    def test_raises_on_unexpected_error(self):
        mock_blob_client = MagicMock()
        mock_container = MagicMock()
        mock_blob_client.get_container_client.return_value = mock_container

        mock_blob = MagicMock()
        mock_blob.download_blob.side_effect = Exception("AuthenticationFailed")
        mock_container.get_blob_client.return_value = mock_blob

        with pytest.raises(Exception, match="AuthenticationFailed"):
            load_decision_audit(mock_blob_client, "REQ-001")
