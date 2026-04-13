"""Tests for orchestrator rules sandbox."""

import pytest

from orchestrator.modules.rules_sandbox import evaluate_rules


def _base_payload(**overrides):
    payload = {
        "probability_of_default": 0.05,
        "score_grade": "A",
        "data_engineer_decision_label": "APPROVE",
        "fraud_risk_flag": "LOW",
        "features": {},
        "metadata": {"credit_score": 780},
    }
    payload.update(overrides)
    return payload


# ── Happy path decisions per grade ─────────────────────────────────────────

class TestEvaluateRulesByGrade:
    def test_grade_a_approves(self):
        result = evaluate_rules(_base_payload(score_grade="A", probability_of_default=0.03))
        assert result["decision"] == "APPROVE"
        assert result["sandbox"] is True
        assert result["request_id"].startswith("sandbox-")

    def test_grade_b_approves(self):
        result = evaluate_rules(_base_payload(score_grade="B", probability_of_default=0.08))
        assert result["decision"] == "APPROVE"

    def test_grade_c_approves(self):
        result = evaluate_rules(_base_payload(score_grade="C", probability_of_default=0.12))
        assert result["decision"] == "APPROVE"

    def test_grade_d_conditional(self):
        result = evaluate_rules(_base_payload(
            score_grade="D",
            probability_of_default=0.18,
            data_engineer_decision_label="CONDITIONAL_APPROVE",
        ))
        assert result["decision"] == "CONDITIONAL_APPROVE"

    def test_grade_e_refers(self):
        result = evaluate_rules(_base_payload(
            score_grade="E",
            probability_of_default=0.30,
            data_engineer_decision_label="REFER",
        ))
        assert result["decision"] == "REFER"

    def test_grade_f_declines(self):
        result = evaluate_rules(_base_payload(
            score_grade="F",
            probability_of_default=0.45,
            data_engineer_decision_label="DECLINE",
        ))
        assert result["decision"] == "DECLINE"


# ── Fraud override ─────────────────────────────────────────────────────────

class TestFraudOverride:
    def test_fraud_high_forces_fraud_hold(self):
        result = evaluate_rules(_base_payload(score_grade="A", fraud_risk_flag="HIGH"))
        assert result["decision"] == "FRAUD_HOLD"


# ── Loan amount + tier ─────────────────────────────────────────────────────

class TestLoanAmount:
    def test_loan_amount_populated_when_provided(self):
        result = evaluate_rules(_base_payload(recommended_loan_amount_ghs=5000))
        assert result["loan_amount"] is not None
        assert result["loan_amount"]["recommended_amount_ghs"] == 5000
        assert result["loan_amount"]["model_version"] == "sandbox"

    def test_loan_amount_null_when_not_provided(self):
        result = evaluate_rules(_base_payload())
        assert result["loan_amount"] is None


# ── Validation errors ──────────────────────────────────────────────────────

class TestValidationErrors:
    def test_missing_probability_of_default(self):
        payload = _base_payload()
        del payload["probability_of_default"]
        with pytest.raises(ValueError, match="probability_of_default"):
            evaluate_rules(payload)

    def test_missing_score_grade(self):
        payload = _base_payload()
        del payload["score_grade"]
        with pytest.raises(ValueError, match="score_grade"):
            evaluate_rules(payload)

    def test_invalid_score_grade(self):
        with pytest.raises(ValueError, match="Invalid score grade"):
            evaluate_rules(_base_payload(score_grade="X"))

    def test_pd_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 1"):
            evaluate_rules(_base_payload(probability_of_default=1.5))

    def test_pd_not_a_number(self):
        with pytest.raises(ValueError, match="must be a number"):
            evaluate_rules(_base_payload(probability_of_default="high"))

    def test_invalid_fraud_risk_flag(self):
        with pytest.raises(ValueError, match="fraud_risk_flag"):
            evaluate_rules(_base_payload(fraud_risk_flag="EXTREME"))

    def test_non_dict_payload(self):
        with pytest.raises(ValueError, match="JSON object"):
            evaluate_rules("not a dict")

    def test_features_not_dict(self):
        payload = _base_payload()
        payload["features"] = [1, 2, 3]
        with pytest.raises(ValueError, match="'features'"):
            evaluate_rules(payload)


# ── Response shape ─────────────────────────────────────────────────────────

class TestResponseShape:
    def test_has_all_required_fields(self):
        result = evaluate_rules(_base_payload())
        required = {
            "request_id", "sandbox", "scoring_timestamp", "decision",
            "condition_applied", "credit_risk", "fraud_detection",
            "loan_amount", "income_verification", "scoring_metadata",
            "refer_reasons",
        }
        assert required.issubset(set(result.keys()))

    def test_model_versions_are_sandbox(self):
        result = evaluate_rules(_base_payload())
        assert result["credit_risk"]["model_version"] == "sandbox"
        assert result["fraud_detection"]["model_version"] == "sandbox"

    def test_request_id_is_unique(self):
        a = evaluate_rules(_base_payload())
        b = evaluate_rules(_base_payload())
        assert a["request_id"] != b["request_id"]

    def test_missing_features_default_to_05(self):
        # evaluate_rules should not raise when features dict is empty
        result = evaluate_rules(_base_payload(features={}))
        assert result["sandbox"] is True
