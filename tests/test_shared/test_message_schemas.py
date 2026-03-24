"""Tests for shared message schemas."""

import json

from shared.schemas.message_schemas import (
    CreditRiskPredictionResult,
    FraudDetectionPredictionResult,
    InferenceRequestMessage,
    TrainModelMessage,
    TrainingDataReadyMessage,
    parse_prediction_result,
)


class TestTrainingDataReadyMessage:
    def test_round_trip(self):
        msg = TrainingDataReadyMessage(
            training_id="TRN-001",
            dataset_path="curated/training/dataset.parquet",
            dataset_version="v1.0",
            record_count=50000,
            product_distribution={"product_45": 35000, "product_49": 10000},
            published_at="2026-03-24T10:00:00Z",
        )
        raw = msg.to_json()
        restored = TrainingDataReadyMessage.from_json(raw)
        assert restored.training_id == "TRN-001"
        assert restored.record_count == 50000


class TestInferenceRequestMessage:
    def test_features_preserved(self):
        msg = InferenceRequestMessage(
            request_id="REQ-001",
            features={"highest_delinquency_rating": 0.8, "months_on_time_24m": None},
            metadata={"credit_score": 720},
        )
        raw = msg.to_json()
        data = json.loads(raw)
        assert data["features"]["highest_delinquency_rating"] == 0.8
        assert data["features"]["months_on_time_24m"] is None


class TestParsePredictionResult:
    def test_credit_risk_result(self):
        raw = json.dumps({
            "request_id": "REQ-001",
            "model_type": "credit_risk",
            "probability_of_default": 0.12,
            "pd_confidence": 0.88,
            "shap_contributions": [],
            "decision_reason_codes": ["R01"],
            "model_version": "1.0.0",
        })
        result = parse_prediction_result(raw)
        assert isinstance(result, CreditRiskPredictionResult)
        assert result.probability_of_default == 0.12

    def test_fraud_detection_result(self):
        raw = json.dumps({
            "request_id": "REQ-001",
            "model_type": "fraud_detection",
            "fraud_anomaly_score": 0.03,
            "fraud_risk_flag": "LOW",
            "model_version": "1.0.0",
        })
        result = parse_prediction_result(raw)
        assert isinstance(result, FraudDetectionPredictionResult)
        assert result.fraud_risk_flag == "LOW"

    def test_unknown_model_type_raises(self):
        raw = json.dumps({"model_type": "unknown"})
        try:
            parse_prediction_result(raw)
            assert False, "Should have raised"
        except ValueError:
            pass
