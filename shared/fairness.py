"""
Fairness & Bias Controls for the PaySwitch Credit Scoring Engine.

BLD Section 9.2 requirements:
- Disparate Impact: approval rates across demographics must not differ by > 15%
- Equal Opportunity: FNR across demographics must not differ by > 10 points
- Calibration: predicted probabilities must be well-calibrated across segments

Demographic slicing uses applicant_age bin weights:
  0.00 = Ineligible (<18 or >75)
  0.70 = Young (18-25)
  1.00 = Prime (26-40)
  0.90 = Mature (41-60)
  0.65 = Senior (>60)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("payswitch-cs.fairness")

# BLD Section 9.2 thresholds
DISPARATE_IMPACT_MIN = 0.80  # 80% rule
EQUAL_OPPORTUNITY_MAX_GAP = 0.10  # 10 percentage point FNR gap

# Applicant age bin weight → demographic group
AGE_GROUP_MAP = {
    0.00: "INELIGIBLE",
    0.70: "YOUNG",
    1.00: "PRIME",
    0.90: "MATURE",
    0.65: "SENIOR",
}


def _map_age_group(age_weight: float) -> str:
    """Map an applicant_age bin weight to a demographic group."""
    # Find closest bin weight
    closest = min(AGE_GROUP_MAP.keys(), key=lambda k: abs(k - age_weight))
    if abs(closest - age_weight) < 0.05:
        return AGE_GROUP_MAP[closest]
    return "UNKNOWN"


def compute_disparate_impact(
    y_pred: np.ndarray,
    groups: pd.Series,
) -> dict[str, Any]:
    """
    Compute disparate impact ratio across demographic groups.

    DI = min(approval_rate) / max(approval_rate) across all groups.
    Must be >= 0.80 (80% rule).

    Args:
        y_pred: Binary predictions (0/1) or thresholded probabilities.
        groups: Demographic group labels per sample.

    Returns:
        Dict with per-group rates, DI ratio, and violation flag.
    """
    group_rates = {}
    for group in groups.unique():
        if group in ("INELIGIBLE", "UNKNOWN"):
            continue
        mask = groups == group
        if mask.sum() < 10:  # Skip groups with too few samples
            continue
        group_rates[group] = float(np.mean(y_pred[mask]))

    if len(group_rates) < 2:
        return {"group_rates": group_rates, "di_ratio": 1.0, "violation": False}

    min_rate = min(group_rates.values())
    max_rate = max(group_rates.values())

    di_ratio = min_rate / max_rate if max_rate > 0 else 1.0

    return {
        "group_rates": group_rates,
        "di_ratio": round(di_ratio, 4),
        "violation": di_ratio < DISPARATE_IMPACT_MIN,
        "threshold": DISPARATE_IMPACT_MIN,
    }


def compute_equal_opportunity(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    groups: pd.Series,
) -> dict[str, Any]:
    """
    Compute equal opportunity (FNR gap) across demographic groups.

    FNR = FN / (FN + TP) per group. Max gap must be <= 0.10.

    Args:
        y_true: True labels (0/1).
        y_pred: Binary predictions (0/1).
        groups: Demographic group labels per sample.

    Returns:
        Dict with per-group FNR, max gap, and violation flag.
    """
    group_fnr = {}
    for group in groups.unique():
        if group in ("INELIGIBLE", "UNKNOWN"):
            continue
        mask = groups == group
        positives = (y_true[mask] == 1)
        if positives.sum() < 5:  # Skip groups with too few positive samples
            continue
        fn = ((y_true[mask] == 1) & (y_pred[mask] == 0)).sum()
        tp = ((y_true[mask] == 1) & (y_pred[mask] == 1)).sum()
        fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
        group_fnr[group] = round(float(fnr), 4)

    if len(group_fnr) < 2:
        return {"group_fnr": group_fnr, "max_gap": 0.0, "violation": False}

    max_gap = max(group_fnr.values()) - min(group_fnr.values())

    return {
        "group_fnr": group_fnr,
        "max_gap": round(max_gap, 4),
        "violation": max_gap > EQUAL_OPPORTUNITY_MAX_GAP,
        "threshold": EQUAL_OPPORTUNITY_MAX_GAP,
    }


def run_fairness_checks(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    features_df: pd.DataFrame,
    pd_threshold: float = 0.5,
) -> dict[str, Any]:
    """
    Run all fairness checks using applicant_age as the demographic slicer.

    Args:
        y_true: True labels (0/1).
        y_pred: Predicted probabilities (continuous 0-1).
        features_df: DataFrame with all 30 features (must include applicant_age).
        pd_threshold: Threshold to binarize predictions (default 0.5).

    Returns:
        Dict with disparate_impact, equal_opportunity results, and list of violations.
    """
    # Map age weights to demographic groups
    age_weights = features_df["applicant_age"].values
    groups = pd.Series([_map_age_group(w) for w in age_weights])

    # Binarize predictions
    y_pred_binary = (np.array(y_pred) >= pd_threshold).astype(int)

    # Run checks
    di_result = compute_disparate_impact(y_pred_binary, groups)
    eo_result = compute_equal_opportunity(np.array(y_true), y_pred_binary, groups)

    violations = []
    if di_result["violation"]:
        violations.append(
            f"Disparate Impact violation: DI ratio {di_result['di_ratio']:.4f} < {DISPARATE_IMPACT_MIN} "
            f"(rates: {di_result['group_rates']})"
        )
    if eo_result["violation"]:
        violations.append(
            f"Equal Opportunity violation: FNR gap {eo_result['max_gap']:.4f} > {EQUAL_OPPORTUNITY_MAX_GAP} "
            f"(FNR: {eo_result['group_fnr']})"
        )

    if violations:
        for v in violations:
            logger.warning("FAIRNESS: %s", v)
    else:
        logger.info("Fairness checks passed (DI=%.4f, FNR gap=%.4f)",
                     di_result["di_ratio"], eo_result["max_gap"])

    return {
        "disparate_impact": di_result,
        "equal_opportunity": eo_result,
        "violations": violations,
        "passed": len(violations) == 0,
    }
