"""
Drift Detection Module for the PaySwitch Credit Scoring Engine.

BLD Section 5.3 and 10.1:
- PSI > 0.20 on any Group A feature → trigger retraining
- PSI 0.10-0.20 → minor drift (log warning)
- PSI < 0.10 → no drift

Computes Population Stability Index (PSI) between training feature
distributions and recent inference feature distributions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pandas as pd

from shared.schemas.feature_schema import ALL_FEATURE_NAMES, FEATURE_BY_NAME

logger = logging.getLogger("payswitch-cs.drift-detector")

# PSI thresholds (from BLD Section 10.1)
PSI_NO_DRIFT = 0.10
PSI_MINOR_DRIFT = 0.20  # Warning threshold
PSI_SIGNIFICANT_DRIFT = 0.20  # Retraining trigger

# Group A features are highest priority (35% weight — payment history)
GROUP_A_FEATURES = [
    f.name for f in FEATURE_BY_NAME.values()
    if hasattr(f, "group") and f.group == "A"
] if hasattr(list(FEATURE_BY_NAME.values())[0], "group") else [
    "highest_delinquency_rating", "months_on_time_24m", "worst_arrears_24m",
    "current_streak_on_time", "has_active_arrears", "total_arrear_amount_ghs",
]

NUM_BINS = 10
EPSILON = 1e-6  # Prevent log(0)


def compute_psi(expected: np.ndarray, actual: np.ndarray, bins: int = NUM_BINS) -> float:
    """
    Compute Population Stability Index between two distributions.

    PSI = Σ (actual_pct - expected_pct) × ln(actual_pct / expected_pct)

    Args:
        expected: Training distribution values.
        actual: Recent inference distribution values.
        bins: Number of histogram bins.

    Returns:
        PSI value (0 = identical distributions).
    """
    # Create bins from expected distribution
    bin_edges = np.linspace(0, 1, bins + 1)  # Features are 0-1 binned

    expected_counts, _ = np.histogram(expected, bins=bin_edges)
    actual_counts, _ = np.histogram(actual, bins=bin_edges)

    # Convert to percentages
    expected_pct = expected_counts / max(len(expected), 1) + EPSILON
    actual_pct = actual_counts / max(len(actual), 1) + EPSILON

    # PSI formula
    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    return float(psi)


def compute_feature_distributions(df: pd.DataFrame, bins: int = NUM_BINS) -> dict[str, dict]:
    """
    Compute histogram distributions for all 30 features.

    Args:
        df: DataFrame with feature columns.

    Returns:
        Dict mapping feature_name → {bins, counts, total}.
    """
    distributions = {}
    bin_edges = np.linspace(0, 1, bins + 1).tolist()

    for feature in ALL_FEATURE_NAMES:
        if feature not in df.columns:
            continue
        values = df[feature].dropna().values
        counts, _ = np.histogram(values, bins=bin_edges)
        distributions[feature] = {
            "bin_edges": bin_edges,
            "counts": counts.tolist(),
            "total": len(values),
        }

    return distributions


def check_feature_drift(
    baseline_distributions: dict[str, dict],
    recent_features: pd.DataFrame,
) -> dict[str, Any]:
    """
    Compare recent inference features against training baseline.

    Args:
        baseline_distributions: From compute_feature_distributions() saved during training.
        recent_features: DataFrame of recent inference feature vectors.

    Returns:
        Dict with per-feature PSI, drifted features, and recommendation.
    """
    feature_psi = {}
    drifted_features = {}
    minor_drift_features = {}

    for feature in ALL_FEATURE_NAMES:
        baseline = baseline_distributions.get(feature)
        if baseline is None or feature not in recent_features.columns:
            continue

        recent_values = recent_features[feature].dropna().values
        if len(recent_values) < 10:
            continue

        # Reconstruct baseline values from histogram for PSI computation
        baseline_values = _reconstruct_from_histogram(
            baseline["bin_edges"], baseline["counts"],
        )

        psi = compute_psi(baseline_values, recent_values)
        feature_psi[feature] = round(psi, 4)

        if psi >= PSI_SIGNIFICANT_DRIFT:
            severity = "HIGH" if feature in GROUP_A_FEATURES else "MEDIUM"
            drifted_features[feature] = {"psi": round(psi, 4), "severity": severity}
        elif psi >= PSI_NO_DRIFT:
            minor_drift_features[feature] = {"psi": round(psi, 4), "severity": "MINOR"}

    # Determine recommendation
    has_group_a_drift = any(
        f in GROUP_A_FEATURES for f in drifted_features
    )
    recommendation = "retrain" if has_group_a_drift or len(drifted_features) >= 3 else "monitor"

    return {
        "feature_psi": feature_psi,
        "drifted_features": drifted_features,
        "minor_drift_features": minor_drift_features,
        "recommendation": recommendation,
        "has_group_a_drift": has_group_a_drift,
    }


def _reconstruct_from_histogram(bin_edges: list[float], counts: list[int]) -> np.ndarray:
    """Reconstruct approximate values from histogram bins + counts."""
    values = []
    for i, count in enumerate(counts):
        if count > 0:
            midpoint = (bin_edges[i] + bin_edges[i + 1]) / 2
            values.extend([midpoint] * count)
    return np.array(values) if values else np.array([0.5])


def build_drift_message(
    drift_result: dict[str, Any],
    baseline_metrics: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a drift-detected Service Bus message."""
    # Determine which models need retraining based on drifted features
    models_to_retrain = ["credit_risk"]  # Always retrain credit risk on drift

    if any(f in ["total_outstanding_debt_ghs", "utilisation_ratio", "total_monthly_instalment_ghs"]
           for f in drift_result["drifted_features"]):
        models_to_retrain.append("loan_amount")

    if any(f in ["has_employer_detail", "total_monthly_instalment_ghs", "credit_age_months"]
           for f in drift_result["drifted_features"]):
        models_to_retrain.append("income_verification")

    # Fraud detection always retrained on drift (unsupervised — needs fresh normal baseline)
    models_to_retrain.append("fraud_detection")

    return {
        "event": "drift_detected",
        "recommendation": drift_result["recommendation"],
        "models_to_retrain": list(set(models_to_retrain)),
        "drifted_features": drift_result["drifted_features"],
        "has_group_a_drift": drift_result["has_group_a_drift"],
        "baseline_metrics": baseline_metrics or {},
    }
