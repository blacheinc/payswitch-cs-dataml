"""Tests for shared constants."""

from shared.constants import (
    DECISION_PRIORITY,
    FEATURE_TO_REASON_CODE,
    PD_RISK_TIER_BOUNDARIES,
    Decision,
    FraudRiskFlag,
    LoanTier,
    ModelType,
    ReasonCode,
    RiskTier,
    ServiceBusTopic,
)


class TestDecisionPriority:
    def test_fraud_hold_is_most_conservative(self):
        assert DECISION_PRIORITY[Decision.FRAUD_HOLD] == 0

    def test_approve_is_least_conservative(self):
        assert DECISION_PRIORITY[Decision.APPROVE] == 4

    def test_ordering(self):
        ordered = sorted(Decision, key=lambda d: DECISION_PRIORITY[d])
        assert ordered == [
            Decision.FRAUD_HOLD,
            Decision.DECLINE,
            Decision.REFER,
            Decision.CONDITIONAL_APPROVE,
            Decision.APPROVE,
        ]


class TestPdBoundaries:
    def test_boundaries_cover_full_range(self):
        assert PD_RISK_TIER_BOUNDARIES[0][0] == 0.0
        assert PD_RISK_TIER_BOUNDARIES[-1][1] == float("inf")

    def test_boundaries_are_contiguous(self):
        for i in range(len(PD_RISK_TIER_BOUNDARIES) - 1):
            assert PD_RISK_TIER_BOUNDARIES[i][1] == PD_RISK_TIER_BOUNDARIES[i + 1][0]

    def test_six_risk_tiers(self):
        assert len(PD_RISK_TIER_BOUNDARIES) == 6


class TestServiceBusTopics:
    def test_total_topic_count(self):
        assert len(ServiceBusTopic) == 16  # 8 training + 7 inference + 1 monitoring

    def test_training_topics_exist(self):
        assert ServiceBusTopic.TRAINING_DATA_READY.value == "training-data-ready"
        assert ServiceBusTopic.MODEL_TRAINING_STARTED.value == "model-training-started"
        assert ServiceBusTopic.MODEL_TRAINING_COMPLETED.value == "model-training-completed"

    def test_inference_topics_exist(self):
        assert ServiceBusTopic.INFERENCE_REQUEST.value == "inference-request"
        assert ServiceBusTopic.SCORING_COMPLETE.value == "scoring-complete"


class TestReasonCodes:
    def test_ten_reason_codes(self):
        assert len(ReasonCode) == 10

    def test_feature_mapping_covers_key_features(self):
        assert FEATURE_TO_REASON_CODE["highest_delinquency_rating"] == ReasonCode.R01
        assert FEATURE_TO_REASON_CODE["utilisation_ratio"] == ReasonCode.R02
        assert FEATURE_TO_REASON_CODE["has_active_arrears"] == ReasonCode.R06
