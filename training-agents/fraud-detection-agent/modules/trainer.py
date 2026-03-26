"""
Fraud Detection Model trainer.

Isolation Forest (unsupervised) for anomaly detection on credit profiles.
No labels needed — learns what "normal" looks like and flags deviations.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split

from shared.schemas.feature_schema import ALL_FEATURE_NAMES

logger = logging.getLogger("payswitch-cs.fraud-detection.trainer")


def prepare_data(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extract features and hold out 15% for threshold calibration validation.

    Isolation Forest is unsupervised, so it trains on the full dataset.
    The holdout is only for validating the learned score distributions.

    Returns:
        (X_full, X_holdout)
    """
    X = df[ALL_FEATURE_NAMES].copy()

    # Hold out 15% for validation (only need the holdout, not the complement)
    _, X_holdout = train_test_split(X, test_size=0.15, random_state=42)

    logger.info("Data prepared: full=%d, holdout=%d", len(X), len(X_holdout))
    return X, X_holdout


def train_isolation_forest(
    X: pd.DataFrame,
    contamination: float = 0.03,
    n_estimators: int = 200,
) -> IsolationForest:
    """
    Train Isolation Forest on the full dataset.

    Args:
        X: Full feature matrix (no target needed).
        contamination: Expected proportion of anomalies (default 3%).
        n_estimators: Number of isolation trees.

    Returns:
        Trained IsolationForest model.
    """
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        max_samples="auto",
        max_features=1.0,
        random_state=42,
        n_jobs=-1,
    )

    model.fit(X)
    logger.info(
        "Isolation Forest trained: n_estimators=%d, contamination=%.3f",
        n_estimators, contamination,
    )
    return model


def calibrate_thresholds(
    model: IsolationForest,
    X: pd.DataFrame,
) -> dict[str, float]:
    """
    Compute percentile-based thresholds from anomaly scores.

    Score mapping:
    - score >= P5 → LOW (normal, bottom 95%)
    - P1 <= score < P5 → MEDIUM (unusual, 95th-99th percentile)
    - score < P1 → HIGH (highly anomalous, top 1%)

    Note: Isolation Forest scores are negative — more negative = more anomalous.

    Returns:
        Threshold params dict (also saved as artifact for inference).
    """
    raw_scores = model.score_samples(X)

    p5 = float(np.percentile(raw_scores, 5))
    p1 = float(np.percentile(raw_scores, 1))
    min_score = float(np.min(raw_scores))
    max_score = float(np.max(raw_scores))

    thresholds = {
        "low_medium_boundary": p5,     # 95th percentile of anomaly
        "medium_high_boundary": p1,    # 99th percentile of anomaly
        "percentile_95": p5,
        "percentile_99": p1,
        "min_score": min_score,
        "max_score": max_score,
    }

    logger.info(
        "Thresholds calibrated: LOW/MED=%.4f, MED/HIGH=%.4f, range=[%.4f, %.4f]",
        p5, p1, min_score, max_score,
    )
    return thresholds


def normalize_anomaly_score(
    raw_score: float,
    min_score: float,
    max_score: float,
) -> float:
    """
    Normalize raw Isolation Forest score to 0-1 scale.

    Higher = more suspicious (inverted from raw where more negative = more anomalous).
    """
    if max_score == min_score:
        return 0.5
    normalized = 1.0 - (raw_score - min_score) / (max_score - min_score)
    return float(np.clip(normalized, 0.0, 1.0))


def classify_fraud_flag(
    raw_score: float,
    thresholds: dict[str, float],
) -> str:
    """
    Map raw anomaly score to fraud risk flag using calibrated thresholds.

    Returns:
        "LOW", "MEDIUM", or "HIGH"
    """
    if raw_score < thresholds["medium_high_boundary"]:
        return "HIGH"
    elif raw_score < thresholds["low_medium_boundary"]:
        return "MEDIUM"
    return "LOW"


def run_training_pipeline(
    df: pd.DataFrame,
    contamination: float = 0.03,
    n_estimators: int = 200,
) -> tuple[IsolationForest, dict[str, float], dict[str, Any]]:
    """
    Full training pipeline.

    Returns:
        (model, thresholds, training_info)
    """
    X_full, X_holdout = prepare_data(df)

    model = train_isolation_forest(X_full, contamination, n_estimators)
    thresholds = calibrate_thresholds(model, X_full)

    # Compute distribution stats
    raw_scores = model.score_samples(X_full)
    flags = [classify_fraud_flag(s, thresholds) for s in raw_scores]
    low_pct = flags.count("LOW") / len(flags)
    med_pct = flags.count("MEDIUM") / len(flags)
    high_pct = flags.count("HIGH") / len(flags)

    training_info = {
        "total_records": len(X_full),
        "holdout_size": len(X_holdout),
        "low_pct": round(low_pct, 4),
        "medium_pct": round(med_pct, 4),
        "high_pct": round(high_pct, 4),
        "contamination": contamination,
    }

    logger.info(
        "Distribution: LOW=%.1f%%, MEDIUM=%.1f%%, HIGH=%.1f%%",
        low_pct * 100, med_pct * 100, high_pct * 100,
    )

    return model, thresholds, training_info
