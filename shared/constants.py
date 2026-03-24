"""
Constants for the PaySwitch Credit Scoring Engine.

Risk tiers, decision hierarchy, reason codes, loan tiers,
Service Bus topics, and threshold configurations.
"""

from enum import Enum


# ── Risk Tiers (derived from Probability of Default) ────────────────────────

class RiskTier(str, Enum):
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


# PD boundaries: (lower_inclusive, upper_exclusive) → RiskTier
# Ordered from lowest risk to highest risk
PD_RISK_TIER_BOUNDARIES: list[tuple[float, float, RiskTier]] = [
    (0.00, 0.05, RiskTier.VERY_LOW),
    (0.05, 0.10, RiskTier.LOW),
    (0.10, 0.20, RiskTier.MEDIUM),
    (0.20, 0.35, RiskTier.HIGH),
    (0.35, float("inf"), RiskTier.VERY_HIGH),
]


# ── Decision Labels ─────────────────────────────────────────────────────────

class Decision(str, Enum):
    """Final scoring decisions, ordered from most conservative to least."""
    FRAUD_HOLD = "FRAUD_HOLD"
    DECLINE = "DECLINE"
    REFER = "REFER"
    CONDITIONAL_APPROVE = "CONDITIONAL_APPROVE"
    APPROVE = "APPROVE"


# Conflict resolution: lower index = more conservative = wins
DECISION_PRIORITY: dict[Decision, int] = {
    Decision.FRAUD_HOLD: 0,
    Decision.DECLINE: 1,
    Decision.REFER: 2,
    Decision.CONDITIONAL_APPROVE: 3,
    Decision.APPROVE: 4,
}


# ── Fraud Risk Flags ────────────────────────────────────────────────────────

class FraudRiskFlag(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ── Loan Tiers ──────────────────────────────────────────────────────────────

class LoanTier(str, Enum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    PREMIUM = "PREMIUM"


# Loan amount boundaries per tier (GHS)
LOAN_TIER_BOUNDARIES: list[tuple[float, float, LoanTier]] = [
    (500.0, 2500.0, LoanTier.MICRO),
    (2500.0, 10000.0, LoanTier.SMALL),
]

# Absolute caps for model output
LOAN_AMOUNT_MIN_GHS: float = 500.0
LOAN_AMOUNT_MAX_GHS: float = 10000.0


# ── Income Tiers ────────────────────────────────────────────────────────────

class IncomeTier(int, Enum):
    LOW = 0
    MID = 1
    UPPER_MID = 2
    HIGH = 3


INCOME_TIER_LABELS: dict[int, str] = {
    0: "LOW",
    1: "MID",
    2: "UPPER_MID",
    3: "HIGH",
}


# ── Score Grades ────────────────────────────────────────────────────────────

VALID_SCORE_GRADES: list[str] = ["A", "B", "C", "D", "E"]


# ── Reason Codes (R01-R10) ──────────────────────────────────────────────────

class ReasonCode(str, Enum):
    R01 = "R01"  # Delinquency history
    R02 = "R02"  # High credit utilisation
    R03 = "R03"  # Limited credit history
    R04 = "R04"  # High outstanding debt
    R05 = "R05"  # Multiple recent enquiries
    R06 = "R06"  # Active arrears present
    R07 = "R07"  # Low income indicators
    R08 = "R08"  # Adverse account records
    R09 = "R09"  # Limited account diversity
    R10 = "R10"  # High monthly obligations


REASON_CODE_DESCRIPTIONS: dict[ReasonCode, str] = {
    ReasonCode.R01: "Delinquency history",
    ReasonCode.R02: "High credit utilisation",
    ReasonCode.R03: "Limited credit history",
    ReasonCode.R04: "High outstanding debt",
    ReasonCode.R05: "Multiple recent enquiries",
    ReasonCode.R06: "Active arrears present",
    ReasonCode.R07: "Low income indicators",
    ReasonCode.R08: "Adverse account records",
    ReasonCode.R09: "Limited account diversity",
    ReasonCode.R10: "High monthly obligations",
}

# Maps SHAP feature names to their reason codes
FEATURE_TO_REASON_CODE: dict[str, ReasonCode] = {
    "highest_delinquency_rating": ReasonCode.R01,
    "months_on_time_24m": ReasonCode.R01,
    "worst_arrears_24m": ReasonCode.R01,
    "current_streak_on_time": ReasonCode.R01,
    "utilisation_ratio": ReasonCode.R02,
    "credit_age_months": ReasonCode.R03,
    "num_accounts_total": ReasonCode.R03,
    "total_outstanding_debt_ghs": ReasonCode.R04,
    "total_monthly_instalment_ghs": ReasonCode.R04,  # Also R10
    "num_enquiries_3m": ReasonCode.R05,
    "num_enquiries_12m": ReasonCode.R05,
    "has_active_arrears": ReasonCode.R06,
    "total_arrear_amount_ghs": ReasonCode.R06,
    "has_employer_detail": ReasonCode.R07,
    "num_dependants": ReasonCode.R07,
    "has_adverse_default": ReasonCode.R08,
    "has_written_off": ReasonCode.R08,
    "has_charged_off": ReasonCode.R08,
    "has_legal_handover": ReasonCode.R08,
    "has_judgement": ReasonCode.R08,
    "product_diversity_score": ReasonCode.R09,
    "num_closed_accounts_good": ReasonCode.R09,
}

MAX_REASON_CODES: int = 5
MAX_SHAP_FEATURES: int = 5


# ── Service Bus Topics ──────────────────────────────────────────────────────

class ServiceBusTopic(str, Enum):
    # Training topics
    TRAINING_DATA_READY = "training-data-ready"
    CREDIT_RISK_TRAIN = "credit-risk-train"
    FRAUD_DETECTION_TRAIN = "fraud-detection-train"
    LOAN_AMOUNT_TRAIN = "loan-amount-train"
    INCOME_VERIFICATION_TRAIN = "income-verification-train"
    MODEL_TRAINING_COMPLETE = "model-training-complete"
    ALL_TRAINING_COMPLETE = "all-training-complete"

    # Inference topics
    INFERENCE_REQUEST = "inference-request"
    CREDIT_RISK_PREDICT = "credit-risk-predict"
    FRAUD_DETECT_PREDICT = "fraud-detect-predict"
    LOAN_AMOUNT_PREDICT = "loan-amount-predict"
    INCOME_VERIFY_PREDICT = "income-verify-predict"
    PREDICTION_COMPLETE = "prediction-complete"
    SCORING_COMPLETE = "scoring-complete"


# ── Model Types ─────────────────────────────────────────────────────────────

class ModelType(str, Enum):
    CREDIT_RISK = "credit_risk"
    FRAUD_DETECTION = "fraud_detection"
    LOAN_AMOUNT = "loan_amount"
    INCOME_VERIFICATION = "income_verification"


# MLflow registry names per model
MODEL_REGISTRY_NAMES: dict[ModelType, str] = {
    ModelType.CREDIT_RISK: "credit-scoring-risk-xgboost",
    ModelType.FRAUD_DETECTION: "credit-scoring-fraud-iforest",
    ModelType.LOAN_AMOUNT: "credit-scoring-loan-amount",
    ModelType.INCOME_VERIFICATION: "credit-scoring-income",
}


# ── Timeouts ────────────────────────────────────────────────────────────────

MODEL_PREDICTION_TIMEOUT_SECONDS: int = 300  # 5 minutes
TRAINING_TIMEOUT_SECONDS: int = 3600  # 1 hour

TOTAL_MODEL_AGENTS: int = 4
