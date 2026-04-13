"""Tests for orchestrator champion store."""

import json
from unittest.mock import MagicMock

import pytest

from orchestrator.modules.champion_store import (
    CHAMPIONS_BLOB_PATH,
    CHAMPIONS_CONTAINER,
    _build_single_entry,
    build_champion_snapshot,
    load_champion_snapshot,
    save_champion_snapshot,
)
from shared.constants import MODEL_REGISTRY_NAMES, ModelType


def _make_model_version(
    version: str = "7",
    metrics: dict = None,
    tags: dict = None,
    created_at: str = "2026-04-01T15:32:56Z",
):
    """Build a mock Azure ML Model object with version + properties."""
    m = MagicMock()
    m.version = version
    m.properties = {"metrics": json.dumps(metrics or {"auc": 0.85})}
    m.tags = tags or {"model_version": "1.0.0"}
    m.creation_context = MagicMock()
    m.creation_context.created_at = created_at
    return m


# ── _build_single_entry ────────────────────────────────────────────────────

class TestBuildSingleEntry:
    def test_returns_champion_entry_when_model_exists(self):
        ml_client = MagicMock()
        ml_client.models.list.return_value = [
            _make_model_version(version="3"),
            _make_model_version(version="5"),
            _make_model_version(version="7"),
        ]

        entry = _build_single_entry(
            ml_client, ModelType.CREDIT_RISK, "credit-scoring-risk-xgboost",
        )

        assert entry["model_type"] == "credit_risk"
        assert entry["registry_name"] == "credit-scoring-risk-xgboost"
        assert entry["version"] == "7"  # highest version wins
        assert entry["status"] == "CHAMPION"
        assert entry["metrics"]["auc"] == 0.85

    def test_returns_not_registered_when_no_versions(self):
        ml_client = MagicMock()
        ml_client.models.list.return_value = []

        entry = _build_single_entry(
            ml_client, ModelType.FRAUD_DETECTION, "credit-scoring-fraud-iforest",
        )

        assert entry["status"] == "NOT_REGISTERED"
        assert entry["model_type"] == "fraud_detection"
        assert "error" in entry

    def test_returns_not_registered_on_exception(self):
        ml_client = MagicMock()
        ml_client.models.list.side_effect = Exception("Forbidden")

        entry = _build_single_entry(
            ml_client, ModelType.LOAN_AMOUNT, "credit-scoring-loan-amount",
        )

        assert entry["status"] == "NOT_REGISTERED"
        assert "Forbidden" in entry["error"]

    def test_parses_metrics_from_properties(self):
        ml_client = MagicMock()
        ml_client.models.list.return_value = [
            _make_model_version(metrics={"weighted_f1": 0.78, "auc_ovr": 0.88}),
        ]

        entry = _build_single_entry(
            ml_client, ModelType.INCOME_VERIFICATION, "credit-scoring-income",
        )

        assert entry["metrics"]["weighted_f1"] == 0.78
        assert entry["metrics"]["auc_ovr"] == 0.88

    def test_handles_missing_properties_metrics(self):
        ml_client = MagicMock()
        mv = _make_model_version()
        mv.properties = {}  # no metrics key
        ml_client.models.list.return_value = [mv]

        entry = _build_single_entry(
            ml_client, ModelType.CREDIT_RISK, "credit-scoring-risk-xgboost",
        )

        assert entry["metrics"] == {}

    def test_handles_malformed_metrics_json(self):
        ml_client = MagicMock()
        mv = _make_model_version()
        mv.properties = {"metrics": "not-valid-json"}
        ml_client.models.list.return_value = [mv]

        entry = _build_single_entry(
            ml_client, ModelType.CREDIT_RISK, "credit-scoring-risk-xgboost",
        )

        # Should not raise; metrics should be empty
        assert entry["metrics"] == {}
        assert entry["status"] == "CHAMPION"


# ── build_champion_snapshot ────────────────────────────────────────────────

class TestBuildChampionSnapshot:
    def test_returns_entry_for_each_model_type(self):
        ml_client = MagicMock()
        ml_client.models.list.return_value = [_make_model_version()]

        snapshot = build_champion_snapshot(ml_client)

        assert "updated_at" in snapshot
        assert len(snapshot["models"]) == len(ModelType)
        model_types = [m["model_type"] for m in snapshot["models"]]
        assert set(model_types) == {mt.value for mt in ModelType}

    def test_mixed_registered_and_not_registered(self):
        """Some models registered, others not — snapshot includes both."""
        ml_client = MagicMock()

        # First 2 model types return versions, last 2 return empty
        call_count = {"n": 0}
        def list_side_effect(name):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return [_make_model_version()]
            return []

        ml_client.models.list.side_effect = list_side_effect

        snapshot = build_champion_snapshot(ml_client)

        statuses = [m["status"] for m in snapshot["models"]]
        assert statuses.count("CHAMPION") == 2
        assert statuses.count("NOT_REGISTERED") == 2

    def test_updated_at_is_iso_timestamp(self):
        ml_client = MagicMock()
        ml_client.models.list.return_value = []

        snapshot = build_champion_snapshot(ml_client)

        # Should be parseable ISO 8601
        from datetime import datetime
        datetime.fromisoformat(snapshot["updated_at"])


# ── save_champion_snapshot ─────────────────────────────────────────────────

class TestSaveChampionSnapshot:
    def test_writes_to_correct_blob_path(self):
        mock_blob_client = MagicMock()
        mock_container = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value = mock_container
        mock_container.get_blob_client.return_value = mock_blob

        snapshot = {"updated_at": "2026-04-11T00:00:00Z", "models": []}
        path = save_champion_snapshot(mock_blob_client, snapshot)

        assert path == CHAMPIONS_BLOB_PATH
        mock_blob_client.get_container_client.assert_called_once_with(CHAMPIONS_CONTAINER)
        mock_container.get_blob_client.assert_called_once_with(CHAMPIONS_BLOB_PATH)

    def test_uses_overwrite_true(self):
        """Champion snapshot is NOT immutable — it's refreshed after every training."""
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        save_champion_snapshot(mock_blob_client, {"updated_at": "x", "models": []})

        _, kwargs = mock_blob.upload_blob.call_args
        assert kwargs.get("overwrite") is True

    def test_serializes_snapshot_as_json(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        snapshot = {
            "updated_at": "2026-04-11T00:00:00Z",
            "models": [{"model_type": "credit_risk", "version": "7"}],
        }
        save_champion_snapshot(mock_blob_client, snapshot)

        args, _ = mock_blob.upload_blob.call_args
        parsed = json.loads(args[0])
        assert parsed["models"][0]["model_type"] == "credit_risk"
        assert parsed["models"][0]["version"] == "7"


# ── load_champion_snapshot ─────────────────────────────────────────────────

class TestLoadChampionSnapshot:
    def test_returns_parsed_snapshot(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob.download_blob.return_value.readall.return_value = b'{"updated_at": "2026-04-11", "models": [{"v": 1}]}'
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        result = load_champion_snapshot(mock_blob_client)

        assert result is not None
        assert result["updated_at"] == "2026-04-11"
        assert result["models"] == [{"v": 1}]

    def test_returns_none_when_not_found(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob.download_blob.side_effect = Exception("BlobNotFound")
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        result = load_champion_snapshot(mock_blob_client)

        assert result is None

    def test_raises_on_unexpected_error(self):
        mock_blob_client = MagicMock()
        mock_blob = MagicMock()
        mock_blob.download_blob.side_effect = Exception("AuthenticationFailed")
        mock_blob_client.get_container_client.return_value.get_blob_client.return_value = mock_blob

        with pytest.raises(Exception, match="AuthenticationFailed"):
            load_champion_snapshot(mock_blob_client)
