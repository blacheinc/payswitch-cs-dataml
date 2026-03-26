"""
Fraud Detection Model validation.

Validates score distributions and sanity-checks anomaly detection
against known bad records.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from shared.schemas.feature_schema import ALL_FEATURE_NAMES

logger = logging.getLogger("payswitch-cs.fraud-detection.validator")


def validate_distribution(training_info: dict[str, Any]) -> list[str]:
    """
    Validate that the score distribution is within expected ranges.

    Expected ranges (from PLAN_FRAUD_DETECTION.md Section 5.3):
    - LOW: 90-95% of records
    - MEDIUM: 4-8% of records
    - HIGH: 0.5-2% of records

    Returns:
        List of warning messages (empty = valid).
    """
    warnings: list[str] = []

    low = training_info.get("low_pct", 0)
    med = training_info.get("medium_pct", 0)
    high = training_info.get("high_pct", 0)

    if not (0.90 <= low <= 0.95):
        warnings.append(f"LOW distribution {low:.1%} outside expected range 90-95%")
    if not (0.04 <= med <= 0.08):
        warnings.append(f"MEDIUM distribution {med:.1%} outside expected range 4-8%")
    if not (0.005 <= high <= 0.02):
        warnings.append(f"HIGH distribution {high:.1%} outside expected range 0.5-2%")

    if warnings:
        for w in warnings:
            logger.warning("Distribution check: %s", w)
    else:
        logger.info("Distribution checks passed")

    return warnings


def sanity_check_known_bad(
    model: IsolationForest,
    df: pd.DataFrame,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    """
    Sanity check: records with W/G/L status (write-off, charge-off, legal)
    should tend to have higher anomaly scores than clean records.

    This uses has_written_off, has_charged_off, has_legal_handover as proxies
    since we don't have actual fraud labels.

    Returns:
        Dict with sanity check results.
    """
    X = df[ALL_FEATURE_NAMES]
    scores = model.score_samples(X)

    # Identify "bad" records (has adverse events)
    bad_mask = (
        (df.get("has_written_off", pd.Series(dtype=float)).fillna(0) > 0.5)
        | (df.get("has_charged_off", pd.Series(dtype=float)).fillna(0) > 0.5)
        | (df.get("has_legal_handover", pd.Series(dtype=float)).fillna(0) > 0.5)
    )

    if bad_mask.sum() == 0:
        logger.warning("No known bad records found for sanity check")
        return {"check": "skipped", "reason": "no_bad_records"}

    bad_scores = scores[bad_mask]
    clean_scores = scores[~bad_mask]

    bad_mean = float(np.mean(bad_scores))
    clean_mean = float(np.mean(clean_scores))

    # Bad records should have lower (more negative) scores on average
    trend_correct = bad_mean < clean_mean

    result = {
        "check": "passed" if trend_correct else "warning",
        "bad_record_count": int(bad_mask.sum()),
        "bad_mean_score": round(bad_mean, 4),
        "clean_mean_score": round(clean_mean, 4),
        "trend_correct": trend_correct,
    }

    if trend_correct:
        logger.info(
            "Sanity check passed: bad records (mean=%.4f) more anomalous than clean (mean=%.4f)",
            bad_mean, clean_mean,
        )
    else:
        logger.warning(
            "Sanity check WARNING: bad records (mean=%.4f) NOT more anomalous than clean (mean=%.4f)",
            bad_mean, clean_mean,
        )

    return result
