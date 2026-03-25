"""Tests for orchestrator decision engine."""

import pytest

from orchestrator.modules.decision_engine import (
    DecisionResult,
    LOAN_TIER_CEILING_GHS,
    derive_conditions,
    lookup_section_4_2,
    resolve_decision_conflict,
    run_decision_engine,
)
from shared.constants import Decision, LoanTier, RiskTier
from shared.schemas.feature_schema import ALL_FEATURE_NAMES


def _make_features(overrides: dict | None = None) -> dict[str, float]:
    """Create a default feature vector with optional overrides."""
    features = {name: 0.5 for name in ALL_FEATURE_NAMES}
    if overrides:
        features.update(overrides)
    return features


# ── Section 4.2 Lookup (1:1 grade → decision + tier) ───────────────────────

class TestLookupSection42:
    def test_grade_a(self):
        decision, tier = lookup_section_4_2("A")
        assert decision == Decision.APPROVE
        assert tier == LoanTier.PREMIUM

    def test_grade_b(self):
        decision, tier = lookup_section_4_2("B")
        assert decision == Decision.APPROVE
        assert tier == LoanTier.LARGE

    def test_grade_c(self):
        decision, tier = lookup_section_4_2("C")
        assert decision == Decision.APPROVE
        assert tier == LoanTier.MEDIUM

    def test_grade_d(self):
        decision, tier = lookup_section_4_2("D")
        assert decision == Decision.CONDITIONAL_APPROVE
        assert tier == LoanTier.SMALL

    def test_grade_e(self):
        decision, tier = lookup_section_4_2("E")
        assert decision == Decision.REFER
        assert tier == LoanTier.MICRO

    def test_grade_f(self):
        decision, tier = lookup_section_4_2("F")
        assert decision == Decision.DECLINE
        assert tier is None

    def test_lowercase_grade_works(self):
        decision, tier = lookup_section_4_2("b")
        assert decision == Decision.APPROVE
        assert tier == LoanTier.LARGE

    def test_invalid_grade_raises(self):
        with pytest.raises(ValueError, match="Invalid score grade"):
            lookup_section_4_2("Z")


# ── Conflict Resolution ────────────────────────────────────────────────────

class TestResolveDecisionConflict:
    def test_de_decline_overrides_approve(self):
        result = resolve_decision_conflict(Decision.APPROVE, "DECLINE")
        assert result == Decision.DECLINE

    def test_derived_decline_overrides_de_approve(self):
        result = resolve_decision_conflict(Decision.DECLINE, "APPROVE")
        assert result == Decision.DECLINE

    def test_same_decision_returns_same(self):
        result = resolve_decision_conflict(Decision.CONDITIONAL_APPROVE, "CONDITIONAL_APPROVE")
        assert result == Decision.CONDITIONAL_APPROVE

    def test_unknown_de_label_uses_derived(self):
        result = resolve_decision_conflict(Decision.APPROVE, "UNKNOWN_LABEL")
        assert result == Decision.APPROVE

    def test_fraud_hold_overrides_everything(self):
        result = resolve_decision_conflict(Decision.APPROVE, "FRAUD_HOLD")
        assert result == Decision.FRAUD_HOLD


# ── Section 5.4 Conditions ─────────────────────────────────────────────────

class TestDeriveConditions:
    def test_no_conditions_for_clean_profile(self):
        features = _make_features({
            "has_active_arrears": 0.0,
            "has_employer_detail": 0.8,
            "num_active_accounts": 0.3,
            "utilisation_ratio": 0.3,
            "num_closed_accounts_good": 0.5,
            "total_monthly_instalment_ghs": 0.3,
        })
        metadata = {"credit_score": 650, "applicant_age_at_application": 35}
        conditions = derive_conditions(features, metadata=metadata)
        assert conditions == []

    def test_ca01_loan_exceeds_tier_ceiling(self):
        # MICRO ceiling is 5000, model recommends 8000 → CA-01 fires
        conditions = derive_conditions(
            _make_features(),
            recommended_loan_amount_ghs=8000.0,
            max_loan_tier=LoanTier.MICRO,
        )
        assert any("CA-01" in c for c in conditions)

    def test_ca01_not_triggered_when_within_ceiling(self):
        # SMALL ceiling is 25000, model recommends 3000 → no CA-01
        conditions = derive_conditions(
            _make_features(),
            recommended_loan_amount_ghs=3000.0,
            max_loan_tier=LoanTier.SMALL,
        )
        assert not any("CA-01" in c for c in conditions)

    def test_ca02_senior_applicant_reduced_tenor(self):
        metadata = {"credit_score": 650, "applicant_age_at_application": 70}
        conditions = derive_conditions(_make_features(), metadata=metadata)
        assert any("CA-02" in c for c in conditions)

    def test_ca02_elevated_debt_service(self):
        features = _make_features({"total_monthly_instalment_ghs": 0.85})
        metadata = {"credit_score": 650, "applicant_age_at_application": 35}
        conditions = derive_conditions(features, metadata=metadata)
        assert any("CA-02" in c for c in conditions)

    def test_ca03_guarantor_first_time_borrower_low_score(self):
        features = _make_features({"num_closed_accounts_good": 0.1})
        metadata = {"credit_score": 540}
        conditions = derive_conditions(features, metadata=metadata)
        assert any("CA-03" in c for c in conditions)

    def test_ca03_guarantor_active_arrears(self):
        features = _make_features({"has_active_arrears": 1.0})
        metadata = {"credit_score": 650}
        conditions = derive_conditions(features, metadata=metadata)
        assert any("CA-03" in c for c in conditions)

    def test_ca04_collateral_required(self):
        metadata = {"credit_score": 650}
        conditions = derive_conditions(
            _make_features(), metadata=metadata,
            recommended_loan_amount_ghs=150000.0,
        )
        assert any("CA-04" in c for c in conditions)

    def test_ca04_not_triggered_high_score(self):
        metadata = {"credit_score": 750}
        conditions = derive_conditions(
            _make_features(), metadata=metadata,
            recommended_loan_amount_ghs=150000.0,
        )
        assert not any("CA-04" in c for c in conditions)

    def test_ca05_income_verification_low_confidence(self):
        metadata = {"credit_score": 620, "income_confidence": 0.55}
        conditions = derive_conditions(_make_features(), metadata=metadata)
        assert any("CA-05" in c for c in conditions)

    def test_ca05_no_employer_details(self):
        features = _make_features({"has_employer_detail": 0.0})
        metadata = {"credit_score": 650}
        conditions = derive_conditions(features, metadata=metadata)
        assert any("CA-05" in c for c in conditions)

    def test_ca06_first_draw_limited(self):
        features = _make_features({
            "num_active_accounts": 0.7,
            "utilisation_ratio": 0.8,
        })
        conditions = derive_conditions(features)
        assert any("CA-06" in c for c in conditions)


# ── Full Decision Engine ───────────────────────────────────────────────────

class TestRunDecisionEngine:
    def test_fraud_hold_overrides(self):
        result = run_decision_engine(
            probability_of_default=0.03,
            score_grade="A",
            data_engineer_decision_label="APPROVE",
            fraud_risk_flag="HIGH",
            features=_make_features(),
        )
        assert result.decision == Decision.FRAUD_HOLD
        assert result.conditions == []
        # Loan tier still determined by grade, even on FRAUD_HOLD
        assert result.recommended_loan_tier == LoanTier.PREMIUM

    def test_grade_a_approve_premium(self):
        result = run_decision_engine(
            probability_of_default=0.03,
            score_grade="A",
            data_engineer_decision_label="APPROVE",
            fraud_risk_flag="LOW",
            features=_make_features(),
        )
        assert result.decision == Decision.APPROVE
        assert result.risk_tier == RiskTier.VERY_LOW
        assert result.recommended_loan_tier == LoanTier.PREMIUM

    def test_grade_d_conditional_with_conditions(self):
        features = _make_features({"has_active_arrears": 1.0})
        metadata = {"credit_score": 620, "applicant_age_at_application": 35}
        result = run_decision_engine(
            probability_of_default=0.17,
            score_grade="D",
            data_engineer_decision_label="APPROVE",
            fraud_risk_flag="LOW",
            features=features,
            metadata=metadata,
        )
        assert result.decision == Decision.CONDITIONAL_APPROVE
        assert result.recommended_loan_tier == LoanTier.SMALL
        assert len(result.conditions) > 0
        assert any("CA-03" in c for c in result.conditions)

    def test_grade_f_decline(self):
        result = run_decision_engine(
            probability_of_default=0.45,
            score_grade="F",
            data_engineer_decision_label="APPROVE",
            fraud_risk_flag="LOW",
            features=_make_features(),
        )
        assert result.decision == Decision.DECLINE
        assert result.recommended_loan_tier is None

    def test_de_decline_overrides_derived_approve(self):
        result = run_decision_engine(
            probability_of_default=0.03,
            score_grade="A",
            data_engineer_decision_label="DECLINE",
            fraud_risk_flag="LOW",
            features=_make_features(),
        )
        assert result.decision == Decision.DECLINE
        # Loan tier still determined by grade A, even though decision is DECLINE
        assert result.recommended_loan_tier == LoanTier.PREMIUM

    def test_grade_a_with_loan_amount(self):
        # Grade A → APPROVE + PREMIUM. Model amount is independent.
        result = run_decision_engine(
            probability_of_default=0.03,
            score_grade="A",
            data_engineer_decision_label="APPROVE",
            fraud_risk_flag="LOW",
            features=_make_features(),
            recommended_loan_amount_ghs=8000.0,
        )
        assert result.decision == Decision.APPROVE
        assert result.recommended_loan_tier == LoanTier.PREMIUM

    def test_grade_e_refer_still_returns_micro_tier(self):
        # Grade E → REFER + MICRO. Tier is always from grade.
        result = run_decision_engine(
            probability_of_default=0.25,
            score_grade="E",
            data_engineer_decision_label="APPROVE",
            fraud_risk_flag="LOW",
            features=_make_features(),
        )
        assert result.decision == Decision.REFER
        assert result.recommended_loan_tier == LoanTier.MICRO

    def test_grade_d_conditional_preserves_tier(self):
        result = run_decision_engine(
            probability_of_default=0.17,
            score_grade="D",
            data_engineer_decision_label="CONDITIONAL_APPROVE",
            fraud_risk_flag="LOW",
            features=_make_features(),
            recommended_loan_amount_ghs=8000.0,
        )
        assert result.decision == Decision.CONDITIONAL_APPROVE
        assert result.recommended_loan_tier == LoanTier.SMALL
