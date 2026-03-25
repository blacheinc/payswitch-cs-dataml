"""
Decision engine for the PaySwitch Credit Scoring Orchestrator.

Implements:
- Section 4.2: Score grade → base decision + loan tier eligibility
- Section 5.4: Conditional approval conditions based on risk factors
- Conflict resolution: more conservative decision wins
- Fraud override: HIGH fraud flag → FRAUD_HOLD regardless of credit score
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from shared.constants import (
    DECISION_PRIORITY,
    Decision,
    FraudRiskFlag,
    LoanTier,
    RiskTier,
    VALID_SCORE_GRADES,
)
from .risk_mapping import pd_to_risk_tier

logger = logging.getLogger("payswitch-cs.decision_engine")


# ── Section 4.2: Score Grade → Decision + Loan Tier ────────────────────────

# Each score grade maps to exactly one decision and one max loan tier.
# The risk tier and PD range are implicit in the grade (grade encodes score range).
# Source: Section 4.2 of Credit Scoring Engine Model Parameters document.

SECTION_4_2_MAPPING: dict[str, tuple[Decision, Optional[LoanTier]]] = {
    "A": (Decision.APPROVE, LoanTier.PREMIUM),              # 750-850, VERY_LOW, PD <5%
    "B": (Decision.APPROVE, LoanTier.LARGE),                 # 700-749, LOW, PD 5-10%
    "C": (Decision.APPROVE, LoanTier.MEDIUM),                # 650-699, LOW_MEDIUM, PD 10-15%
    "D": (Decision.CONDITIONAL_APPROVE, LoanTier.SMALL),     # 600-649, MEDIUM, PD 15-20%
    "E": (Decision.REFER, LoanTier.MICRO),                   # 520-599, HIGH, PD 20-40%
    "F": (Decision.DECLINE, None),                            # 300-519, VERY_HIGH, PD >40%
}


def lookup_section_4_2(
    score_grade: str,
) -> tuple[Decision, Optional[LoanTier]]:
    """
    Look up the base decision and max loan tier from Section 4.2 mapping.

    Args:
        score_grade: Credit score grade (A-F).

    Returns:
        Tuple of (base_decision, max_loan_tier). max_loan_tier is None
        for DECLINE (Grade F).

    Raises:
        ValueError: If score_grade is not A-F.
    """
    grade = score_grade.upper()
    if grade not in VALID_SCORE_GRADES:
        raise ValueError(f"Invalid score grade: {score_grade!r}. Must be one of {VALID_SCORE_GRADES}")

    return SECTION_4_2_MAPPING[grade]


# ── Conflict Resolution ────────────────────────────────────────────────────

def resolve_decision_conflict(
    derived_decision: Decision,
    data_engineer_decision_label: str,
) -> Decision:
    """
    Apply conflict resolution: the more conservative decision wins.

    Compares the Section 4.2 derived decision against the Data Engineer's
    decision_label. Returns whichever is more conservative per the
    priority ordering: FRAUD_HOLD > DECLINE > REFER > CONDITIONAL_APPROVE > APPROVE.

    Args:
        derived_decision: Decision from Section 4.2 mapping.
        data_engineer_decision_label: Raw decision label from Data Engineer metadata.

    Returns:
        The more conservative of the two decisions.
    """
    try:
        de_decision = Decision(data_engineer_decision_label)
    except ValueError:
        logger.warning(
            "Unknown Data Engineer decision_label %r, using derived decision only",
            data_engineer_decision_label,
        )
        return derived_decision

    # Lower priority number = more conservative = wins
    if DECISION_PRIORITY[de_decision] < DECISION_PRIORITY[derived_decision]:
        return de_decision
    return derived_decision


# ── Section 5.4: Conditional Approval Conditions Library ───────────────────

# Standard condition codes from Section 5.4 of the PDF.
# Each condition has a code, description, and trigger logic.

CONDITION_CA01 = "CA-01"  # Loan amount capped at GHS [X]
CONDITION_CA02 = "CA-02"  # Maximum tenor reduced to [N] months
CONDITION_CA03 = "CA-03"  # Guarantor required
CONDITION_CA04 = "CA-04"  # Collateral documentation required
CONDITION_CA05 = "CA-05"  # Income verification documents required within 5 business days
CONDITION_CA06 = "CA-06"  # First draw limited to 50% of approved amount


def derive_conditions(
    features: dict[str, float],
    metadata: Optional[dict[str, Any]] = None,
    recommended_loan_amount_ghs: Optional[float] = None,
    max_loan_tier: Optional[LoanTier] = None,
) -> list[str]:
    """
    Determine conditions to attach to a CONDITIONAL_APPROVE decision.

    Based on Section 5.4 of the Credit Scoring Engine Model Parameters.
    Returns condition codes with descriptions per the standard library.

    Args:
        features: Imputed feature vector (all 30 features, no nulls).
        metadata: Scoring metadata from Data Engineer (credit_score, income_confidence, etc.).
        recommended_loan_amount_ghs: Raw amount from Loan Amount model.
        max_loan_tier: Maximum eligible tier from Section 4.2.

    Returns:
        List of condition code + description strings.
    """
    if metadata is None:
        metadata = {}

    conditions: list[str] = []
    credit_score = metadata.get("credit_score", 0)
    income_confidence = metadata.get("income_confidence")

    # CA-01: Loan amount capped — recommended exceeds score-tier ceiling
    if recommended_loan_amount_ghs is not None and max_loan_tier is not None:
        tier_ceiling = LOAN_TIER_CEILING_GHS.get(max_loan_tier, float("inf"))
        if recommended_loan_amount_ghs > tier_ceiling:
            conditions.append(
                f"{CONDITION_CA01}: Loan amount capped at GHS {tier_ceiling:,.2f}"
            )

    # CA-02: Maximum tenor reduced — applicant age > 65 or elevated debt-service ratio
    applicant_age = metadata.get("applicant_age_at_application", 0)
    if applicant_age > 65:
        conditions.append(
            f"{CONDITION_CA02}: Maximum tenor reduced due to applicant age ({applicant_age})"
        )
    elif features.get("total_monthly_instalment_ghs", 0) > 0.7:
        conditions.append(
            f"{CONDITION_CA02}: Maximum tenor reduced due to elevated debt-service ratio"
        )

    # CA-03: Guarantor required — score 520-560 with first-time borrower flag
    is_first_time = features.get("num_closed_accounts_good", 0) < 0.15
    if 520 <= credit_score <= 560 and is_first_time:
        conditions.append(f"{CONDITION_CA03}: Guarantor required")
    # Also apply if active arrears present (extended from feature signals)
    elif features.get("has_active_arrears", 0) > 0.5:
        conditions.append(
            f"{CONDITION_CA03}: Guarantor required due to active arrears"
        )

    # CA-04: Collateral documentation required — loan > GHS 100,000 and score < 700
    if (
        recommended_loan_amount_ghs is not None
        and recommended_loan_amount_ghs > 100000
        and credit_score < 700
    ):
        conditions.append(f"{CONDITION_CA04}: Collateral documentation required")

    # CA-05: Income verification documents required within 5 business days
    # Triggered when income_confidence < 0.65 but score >= 600
    if income_confidence is not None and income_confidence < 0.65 and credit_score >= 600:
        conditions.append(
            f"{CONDITION_CA05}: Income verification documents required within 5 business days"
        )
    # Also apply if no employer details on file
    elif features.get("has_employer_detail", 0) < 0.5:
        conditions.append(
            f"{CONDITION_CA05}: Income verification documents required — no employer details on file"
        )

    # CA-06: First draw limited to 50% — multiple active loans near capacity
    if (
        features.get("num_active_accounts", 0) > 0.6
        and features.get("utilisation_ratio", 0) > 0.7
    ):
        conditions.append(
            f"{CONDITION_CA06}: First draw limited to 50% of approved amount"
        )

    return conditions


# ── Loan Tier Ceiling (for CA-01 condition check) ───────────────────────────

# Max GHS amount per loan tier (Section 4.1 boundaries).
# Used ONLY to check whether CA-01 condition should fire —
# NOT to modify the model's recommended_loan_amount.
LOAN_TIER_CEILING_GHS: dict[LoanTier, float] = {
    LoanTier.MICRO: 5000.0,
    LoanTier.SMALL: 25000.0,
    LoanTier.MEDIUM: 100000.0,
    LoanTier.LARGE: 250000.0,
    LoanTier.PREMIUM: float("inf"),
}


# ── Main Decision Engine ───────────────────────────────────────────────────

@dataclass
class DecisionResult:
    """Complete output from the decision engine."""
    decision: Decision
    risk_tier: RiskTier
    conditions: list[str] = field(default_factory=list)
    recommended_loan_tier: Optional[LoanTier] = None


def run_decision_engine(
    probability_of_default: float,
    score_grade: str,
    data_engineer_decision_label: str,
    fraud_risk_flag: str,
    features: dict[str, float],
    recommended_loan_amount_ghs: Optional[float] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> DecisionResult:
    """
    Run the full decision engine pipeline.

    Steps:
    1. Check fraud override (HIGH → FRAUD_HOLD)
    2. Derive risk tier from PD
    3. Look up Section 4.2 (score grade → decision + loan tier)
    4. Conflict resolution with Data Engineer's decision
    5. Derive conditions if CONDITIONAL_APPROVE
    6. Cap loan amount by tier ceiling

    Args:
        probability_of_default: PD from Credit Risk model (0-1).
        score_grade: Credit score grade from Data Engineer (A-F).
        data_engineer_decision_label: Decision label from Data Engineer.
        fraud_risk_flag: Fraud flag from Fraud Detection model.
        features: Imputed feature vector.
        recommended_loan_amount_ghs: Raw amount from Loan Amount model (None if Phase 2 didn't run).

    Returns:
        DecisionResult with final decision and all derived values.
    """
    # Step 1: Derive risk tier from PD (for metadata)
    risk_tier = pd_to_risk_tier(probability_of_default)

    # Step 2: Section 4.2 lookup — grade determines loan tier (always returned)
    derived_decision, loan_tier = lookup_section_4_2(score_grade)

    # Step 3: Fraud override — FRAUD_HOLD overrides decision,
    # but loan tier is still determined by grade
    if fraud_risk_flag == FraudRiskFlag.HIGH.value:
        logger.info("FRAUD_HOLD override — fraud_risk_flag is HIGH")
        return DecisionResult(
            decision=Decision.FRAUD_HOLD,
            risk_tier=risk_tier,
            recommended_loan_tier=loan_tier,
        )

    # Step 4: Conflict resolution (more conservative wins)
    final_decision = resolve_decision_conflict(derived_decision, data_engineer_decision_label)

    # Step 5: Conditions (only for CONDITIONAL_APPROVE)
    conditions: list[str] = []
    if final_decision == Decision.CONDITIONAL_APPROVE:
        conditions = derive_conditions(
            features=features,
            metadata=metadata,
            recommended_loan_amount_ghs=recommended_loan_amount_ghs,
            max_loan_tier=loan_tier,
        )

    return DecisionResult(
        decision=final_decision,
        risk_tier=risk_tier,
        conditions=conditions,
        recommended_loan_tier=loan_tier,
    )
