"""
Final response schema for the PaySwitch Credit Scoring Engine.

Defines the structure of the scoring-complete message
published by the Orchestrator to Backend.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class CreditRiskResponse:
    probability_of_default: float
    pd_confidence: float
    risk_tier: str
    shap_contributions: list[dict[str, Any]]
    decision_reason_codes: list[str]
    model_version: str


@dataclass
class FraudDetectionResponse:
    fraud_anomaly_score: float
    fraud_risk_flag: str
    model_version: str


@dataclass
class LoanAmountResponse:
    recommended_amount_ghs: float
    recommended_loan_tier: str
    model_version: str


@dataclass
class IncomeVerificationResponse:
    income_tier: int
    income_tier_label: str
    income_confidence: float
    model_version: str


@dataclass
class ScoringMetadata:
    credit_score: int
    score_grade: str
    data_quality_score: float
    bureau_hit_status: str
    product_source: str
    applicant_age_at_application: int
    credit_age_months_at_application: int


@dataclass
class ScoringResponse:
    """Complete scoring response: Orchestrator → Backend via scoring-complete topic."""
    request_id: str
    scoring_timestamp: str
    decision: str
    condition_applied: list[str]
    credit_risk: CreditRiskResponse
    fraud_detection: FraudDetectionResponse
    loan_amount: Optional[LoanAmountResponse]
    income_verification: Optional[IncomeVerificationResponse]
    scoring_metadata: ScoringMetadata
    refer_reasons: list[str] = field(default_factory=list)  # Soft-stop reasons if REFER

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # Convert None sub-objects to null in output
        if self.loan_amount is None:
            result["loan_amount"] = None
        if self.income_verification is None:
            result["income_verification"] = None
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)
