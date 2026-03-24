"""
Service Bus message contracts for the PaySwitch Credit Scoring Engine.

Defines typed dataclasses for all messages exchanged between
the Orchestrator and model agents via Azure Service Bus.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional


# ── Base ────────────────────────────────────────────────────────────────────

@dataclass
class BaseMessage:
    """Base class for all Service Bus messages."""

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    @classmethod
    def from_json(cls, raw: str | bytes) -> "BaseMessage":
        data = json.loads(raw)
        return cls(**data)


# ═══════════════════════════════════════════════════════════════════════════
#  TRAINING MESSAGES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TrainingDataReadyMessage(BaseMessage):
    """Data Engineer → Orchestrator: new training dataset is ready."""
    training_id: str
    dataset_path: str
    dataset_version: str
    record_count: int
    product_distribution: dict[str, int] = field(default_factory=dict)
    published_at: str = ""


@dataclass
class TrainModelMessage(BaseMessage):
    """Orchestrator → Model Agent: start training with this dataset."""
    training_id: str
    dataset_path: str
    imputation_params_path: str = ""


@dataclass
class ModelTrainingCompleteMessage(BaseMessage):
    """Model Agent → Orchestrator: training finished for one model."""
    training_id: str
    model_type: str
    status: str  # "SUCCESS" or "FAILED"
    model_version: str = ""
    registry_name: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    training_duration_seconds: float = 0.0
    dataset_records_used: int = 0
    class_distribution: dict[str, int] = field(default_factory=dict)
    features_selected: int = 0
    error_message: str = ""


@dataclass
class AllTrainingCompleteMessage(BaseMessage):
    """Orchestrator → Backend: all models have finished training."""
    training_id: str
    status: str  # "COMPLETE" or "PARTIAL"
    models_trained: dict[str, Any] = field(default_factory=dict)
    training_duration_seconds: float = 0.0
    dataset_info: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
#  INFERENCE MESSAGES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class InferenceRequestMessage(BaseMessage):
    """Data Engineer → Orchestrator: score this applicant."""
    request_id: str
    features: dict[str, Optional[float]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PredictMessage(BaseMessage):
    """Orchestrator → Model Agent: run inference on these features."""
    request_id: str
    features: dict[str, float] = field(default_factory=dict)


@dataclass
class CreditRiskPredictionResult(BaseMessage):
    """Credit Risk Agent → Orchestrator: PD + SHAP results."""
    request_id: str
    model_type: str = "credit_risk"
    probability_of_default: float = 0.0
    pd_confidence: float = 0.0
    shap_contributions: list[dict[str, Any]] = field(default_factory=list)
    decision_reason_codes: list[str] = field(default_factory=list)
    model_version: str = ""


@dataclass
class FraudDetectionPredictionResult(BaseMessage):
    """Fraud Detection Agent → Orchestrator: anomaly score + flag."""
    request_id: str
    model_type: str = "fraud_detection"
    fraud_anomaly_score: float = 0.0
    fraud_risk_flag: str = "LOW"
    model_version: str = ""


@dataclass
class LoanAmountPredictionResult(BaseMessage):
    """Loan Amount Agent → Orchestrator: recommended GHS amount."""
    request_id: str
    model_type: str = "loan_amount"
    recommended_loan_amount: float = 0.0
    model_version: str = ""


@dataclass
class IncomeVerificationPredictionResult(BaseMessage):
    """Income Verification Agent → Orchestrator: income tier."""
    request_id: str
    model_type: str = "income_verification"
    income_tier: int = 0
    income_tier_label: str = ""
    income_confidence: float = 0.0
    model_version: str = ""


# ═══════════════════════════════════════════════════════════════════════════
#  RESULT ROUTING
# ═══════════════════════════════════════════════════════════════════════════

# Maps model_type string to the appropriate result dataclass
PREDICTION_RESULT_CLASSES: dict[str, type] = {
    "credit_risk": CreditRiskPredictionResult,
    "fraud_detection": FraudDetectionPredictionResult,
    "loan_amount": LoanAmountPredictionResult,
    "income_verification": IncomeVerificationPredictionResult,
}


def parse_prediction_result(raw: str | bytes) -> BaseMessage:
    """Parse a prediction-complete message into the correct typed result."""
    data = json.loads(raw)
    model_type = data.get("model_type", "")
    cls = PREDICTION_RESULT_CLASSES.get(model_type)
    if cls is None:
        raise ValueError(f"Unknown model_type in prediction result: {model_type!r}")
    return cls(**data)
