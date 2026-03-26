"""
Credit Risk Model validation.

Computes holdout metrics, generates validation artifacts,
and checks against minimum acceptable thresholds.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from shared.constants import (
    FEATURE_TO_REASON_CODE,
    MAX_REASON_CODES,
    MAX_SHAP_FEATURES,
)

logger = logging.getLogger("payswitch-cs.credit-risk.validator")

# Minimum acceptable thresholds (from PLAN_CREDIT_RISK.md Section 6.3)
METRIC_THRESHOLDS = {
    "auc": 0.78,
    "f1": 0.75,
    "precision": 0.70,
    "recall": 0.65,
    "log_loss_max": 0.50,
}


def evaluate_model(
    model: xgb.XGBClassifier,
    X_holdout: pd.DataFrame,
    y_holdout: pd.Series,
) -> dict[str, float]:
    """
    Evaluate model on holdout set and return metrics dict.
    """
    y_pred = model.predict(X_holdout)
    y_pred_proba = model.predict_proba(X_holdout)[:, 1]

    metrics = {
        "auc": float(roc_auc_score(y_holdout, y_pred_proba)),
        "f1": float(f1_score(y_holdout, y_pred)),
        "precision": float(precision_score(y_holdout, y_pred)),
        "recall": float(recall_score(y_holdout, y_pred)),
        "log_loss": float(log_loss(y_holdout, y_pred_proba)),
    }

    logger.info(
        "Holdout metrics: AUC=%.4f, F1=%.4f, Precision=%.4f, Recall=%.4f, LogLoss=%.4f",
        metrics["auc"], metrics["f1"], metrics["precision"],
        metrics["recall"], metrics["log_loss"],
    )

    return metrics


def check_thresholds(metrics: dict[str, float]) -> list[str]:
    """
    Check metrics against minimum acceptable thresholds.

    Returns list of warning messages for metrics below threshold.
    Empty list means all metrics pass.
    """
    warnings: list[str] = []

    if metrics["auc"] < METRIC_THRESHOLDS["auc"]:
        warnings.append(f"AUC {metrics['auc']:.4f} below minimum {METRIC_THRESHOLDS['auc']}")
    if metrics["f1"] < METRIC_THRESHOLDS["f1"]:
        warnings.append(f"F1 {metrics['f1']:.4f} below minimum {METRIC_THRESHOLDS['f1']}")
    if metrics["precision"] < METRIC_THRESHOLDS["precision"]:
        warnings.append(f"Precision {metrics['precision']:.4f} below minimum {METRIC_THRESHOLDS['precision']}")
    if metrics["recall"] < METRIC_THRESHOLDS["recall"]:
        warnings.append(f"Recall {metrics['recall']:.4f} below minimum {METRIC_THRESHOLDS['recall']}")
    if metrics["log_loss"] > METRIC_THRESHOLDS["log_loss_max"]:
        warnings.append(f"LogLoss {metrics['log_loss']:.4f} above maximum {METRIC_THRESHOLDS['log_loss_max']}")

    if warnings:
        for w in warnings:
            logger.warning("Threshold check FAILED: %s", w)
    else:
        logger.info("All metric thresholds passed")

    return warnings


def get_confusion_matrix(
    model: xgb.XGBClassifier,
    X_holdout: pd.DataFrame,
    y_holdout: pd.Series,
) -> np.ndarray:
    """Return confusion matrix for holdout set."""
    y_pred = model.predict(X_holdout)
    return confusion_matrix(y_holdout, y_pred)


def get_classification_report(
    model: xgb.XGBClassifier,
    X_holdout: pd.DataFrame,
    y_holdout: pd.Series,
) -> str:
    """Return classification report string for holdout set."""
    y_pred = model.predict(X_holdout)
    return classification_report(y_holdout, y_pred, target_names=["no_default", "default"])


def get_feature_importance(model: xgb.XGBClassifier, top_n: int = 15) -> list[dict[str, Any]]:
    """Return top N features by importance (gain)."""
    importance = model.get_booster().get_score(importance_type="gain")
    sorted_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"feature": name, "importance": float(score)} for name, score in sorted_features]


# ── SHAP Explanation (Inference Time) ───────────────────────────────────────

def compute_shap_explanation(
    model: xgb.XGBClassifier,
    X_single: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Compute SHAP values for a single prediction and derive reason codes.

    Args:
        model: Trained XGBoost model.
        X_single: Single-row DataFrame with all 30 features.

    Returns:
        Tuple of (shap_contributions, reason_codes).
        shap_contributions: Top 5 features by absolute SHAP value.
        reason_codes: Up to 5 unique reason codes from SHAP features.
    """
    # Use XGBoost's built-in SHAP (avoids SHAP library compatibility issues with XGBoost 3.x)
    booster = model.get_booster()
    import xgboost as xgb
    dmatrix = xgb.DMatrix(X_single, feature_names=list(X_single.columns))
    shap_values_raw = booster.predict(dmatrix, pred_contribs=True)

    # Last column is the bias term — exclude it
    shap_vals = shap_values_raw[0, :-1]

    feature_names = list(X_single.columns)

    # Pair features with their SHAP values
    feature_shap = [
        (feature_names[i], float(shap_vals[i]))
        for i in range(len(feature_names))
    ]

    # Sort by absolute SHAP value, take top 5
    feature_shap.sort(key=lambda x: abs(x[1]), reverse=True)
    top_features = feature_shap[:MAX_SHAP_FEATURES]

    # Build contributions list
    contributions = []
    for feat_name, shap_val in top_features:
        contributions.append({
            "feature": feat_name,
            "value": round(shap_val, 4),
            "direction": "positive" if shap_val > 0 else "negative",
        })

    # Map to reason codes (deduplicated, max 5)
    reason_codes: list[str] = []
    seen_codes: set[str] = set()
    for feat_name, _ in top_features:
        code = FEATURE_TO_REASON_CODE.get(feat_name)
        if code and code.value not in seen_codes:
            reason_codes.append(code.value)
            seen_codes.add(code.value)
        if len(reason_codes) >= MAX_REASON_CODES:
            break

    return contributions, reason_codes
