"""
Rules Evaluate Sandbox.

Lets Backend's POST /v1/rules/evaluate endpoint test rule configurations
without touching real inference data. Calls the decision engine directly
with caller-provided inputs and returns the same shape as a production
ScoringResponse, flagged with sandbox=True.

BLD Section 8.3.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .decision_engine import run_decision_engine
from shared.constants import VALID_SCORE_GRADES
from shared.schemas.feature_schema import ALL_FEATURE_NAMES

logger = logging.getLogger("payswitch-cs.rules_sandbox")

SANDBOX_MODEL_VERSION = "sandbox"


def evaluate_rules(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Sandbox decision engine run.

    Args:
        payload: {
            "probability_of_default": float,        # required
            "score_grade": "A"-"F",                   # required
            "data_engineer_decision_label": str,    # optional, default "APPROVE"
            "fraud_risk_flag": "LOW"|"MEDIUM"|"HIGH", # optional, default "LOW"
            "recommended_loan_amount_ghs": float,    # optional
            "features": {feature_name: float},       # optional, missing default to 0.5
            "metadata": {...},                       # optional
        }

    Returns:
        Dict in same shape as ScoringResponse.to_dict(), plus:
            "sandbox": True
            "request_id": "sandbox-<uuid>"

    Raises:
        ValueError: on missing/invalid required inputs.
    """
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")

    # Validate required inputs
    if "probability_of_default" not in payload:
        raise ValueError("'probability_of_default' is required")
    try:
        pd_value = float(payload["probability_of_default"])
    except (TypeError, ValueError):
        raise ValueError("'probability_of_default' must be a number")
    if not (0.0 <= pd_value <= 1.0):
        raise ValueError("'probability_of_default' must be between 0 and 1")

    score_grade = payload.get("score_grade")
    if not score_grade:
        raise ValueError("'score_grade' is required")
    if score_grade not in VALID_SCORE_GRADES:
        raise ValueError(f"Invalid score grade: '{score_grade}'. Must be one of {sorted(VALID_SCORE_GRADES)}")

    # Optional inputs with defaults
    de_decision_label = payload.get("data_engineer_decision_label", "APPROVE")
    fraud_risk_flag = payload.get("fraud_risk_flag", "LOW")
    if fraud_risk_flag not in ("LOW", "MEDIUM", "HIGH"):
        raise ValueError(f"Invalid fraud_risk_flag: '{fraud_risk_flag}'. Must be LOW, MEDIUM, or HIGH")

    recommended_loan_amount = payload.get("recommended_loan_amount_ghs")
    if recommended_loan_amount is not None:
        try:
            recommended_loan_amount = float(recommended_loan_amount)
        except (TypeError, ValueError):
            raise ValueError("'recommended_loan_amount_ghs' must be a number")

    # Build feature vector, default missing features to 0.5
    features_in = payload.get("features") or {}
    if not isinstance(features_in, dict):
        raise ValueError("'features' must be an object")
    features = {name: float(features_in.get(name, 0.5)) for name in ALL_FEATURE_NAMES}

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("'metadata' must be an object")

    # Run the decision engine
    try:
        result = run_decision_engine(
            probability_of_default=pd_value,
            score_grade=score_grade,
            data_engineer_decision_label=de_decision_label,
            fraud_risk_flag=fraud_risk_flag,
            features=features,
            recommended_loan_amount_ghs=recommended_loan_amount,
            metadata=metadata,
        )
    except ValueError:
        raise
    except Exception as exc:
        logger.exception("Sandbox decision engine failed")
        raise ValueError(f"Decision engine error: {exc}")

    # Build ScoringResponse-shaped dict
    request_id = f"sandbox-{uuid.uuid4()}"
    scoring_timestamp = datetime.now(timezone.utc).isoformat()

    response = {
        "request_id": request_id,
        "sandbox": True,
        "scoring_timestamp": scoring_timestamp,
        "decision": result.decision.value,
        "condition_applied": list(result.conditions),
        "credit_risk": {
            "probability_of_default": pd_value,
            "pd_confidence": 0.0,
            "risk_tier": result.risk_tier.value,
            "shap_contributions": [],
            "decision_reason_codes": [],
            "model_version": SANDBOX_MODEL_VERSION,
        },
        "fraud_detection": {
            "fraud_anomaly_score": 0.0,
            "fraud_risk_flag": fraud_risk_flag,
            "model_version": SANDBOX_MODEL_VERSION,
        },
        "loan_amount": None,
        "income_verification": None,
        "scoring_metadata": {
            "credit_score": metadata.get("credit_score", 0),
            "score_grade": score_grade,
            "data_quality_score": metadata.get("data_quality_score", 0.0),
            "bureau_hit_status": metadata.get("bureau_hit_status", ""),
            "product_source": metadata.get("product_source", ""),
            "applicant_age_at_application": metadata.get("applicant_age_at_application", 0),
            "credit_age_months_at_application": metadata.get("credit_age_months_at_application", 0),
        },
        "refer_reasons": list(result.refer_reasons),
    }

    # Populate loan_amount response if we have an amount
    if recommended_loan_amount is not None:
        loan_tier_value = result.recommended_loan_tier.value if result.recommended_loan_tier else ""
        response["loan_amount"] = {
            "recommended_amount_ghs": recommended_loan_amount,
            "recommended_loan_tier": loan_tier_value,
            "model_version": SANDBOX_MODEL_VERSION,
        }

    return response
