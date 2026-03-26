"""
Income Verification Model validation.

Multiclass AUC, weighted F1, per-class precision/recall.
"""

from __future__ import annotations

import logging
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from shared.constants import INCOME_TIER_LABELS

logger = logging.getLogger("payswitch-cs.income-verification.validator")

METRIC_THRESHOLDS = {
    "auc_ovr_min": 0.75,
    "weighted_f1_min": 0.70,
    "per_class_recall_min": 0.60,
    "per_class_precision_min": 0.55,
}

TARGET_NAMES = ["LOW", "MID", "UPPER_MID", "HIGH"]


def evaluate_model(
    model: lgb.LGBMClassifier,
    X_holdout: pd.DataFrame,
    y_holdout: pd.Series,
) -> dict[str, Any]:
    """Evaluate model on holdout, return metrics dict."""
    y_pred = model.predict(X_holdout)
    y_pred_proba = model.predict_proba(X_holdout)

    auc_ovr = float(roc_auc_score(y_holdout, y_pred_proba, multi_class="ovr", average="weighted"))
    weighted_f1 = float(f1_score(y_holdout, y_pred, average="weighted"))

    per_class_precision = precision_score(y_holdout, y_pred, average=None, zero_division=0)
    per_class_recall = recall_score(y_holdout, y_pred, average=None, zero_division=0)

    metrics: dict[str, Any] = {
        "auc_ovr": auc_ovr,
        "weighted_f1": weighted_f1,
        "per_class_recall": {
            TARGET_NAMES[i]: float(per_class_recall[i])
            for i in range(len(per_class_recall))
        },
        "per_class_precision": {
            TARGET_NAMES[i]: float(per_class_precision[i])
            for i in range(len(per_class_precision))
        },
    }

    logger.info(
        "Holdout: AUC(OvR)=%.4f, Weighted F1=%.4f",
        auc_ovr, weighted_f1,
    )
    return metrics


def check_thresholds(metrics: dict[str, Any]) -> list[str]:
    """Check against minimum thresholds."""
    warnings: list[str] = []

    if metrics["auc_ovr"] < METRIC_THRESHOLDS["auc_ovr_min"]:
        warnings.append(f"AUC(OvR) {metrics['auc_ovr']:.4f} below min {METRIC_THRESHOLDS['auc_ovr_min']}")
    if metrics["weighted_f1"] < METRIC_THRESHOLDS["weighted_f1_min"]:
        warnings.append(f"Weighted F1 {metrics['weighted_f1']:.4f} below min {METRIC_THRESHOLDS['weighted_f1_min']}")

    for cls_name, recall_val in metrics.get("per_class_recall", {}).items():
        if recall_val < METRIC_THRESHOLDS["per_class_recall_min"]:
            warnings.append(f"Recall for {cls_name} {recall_val:.4f} below min {METRIC_THRESHOLDS['per_class_recall_min']}")

    for cls_name, prec_val in metrics.get("per_class_precision", {}).items():
        if prec_val < METRIC_THRESHOLDS["per_class_precision_min"]:
            warnings.append(f"Precision for {cls_name} {prec_val:.4f} below min {METRIC_THRESHOLDS['per_class_precision_min']}")

    if warnings:
        for w in warnings:
            logger.warning("Threshold check FAILED: %s", w)
    else:
        logger.info("All metric thresholds passed")

    return warnings


def get_confusion_matrix(
    model: lgb.LGBMClassifier,
    X_holdout: pd.DataFrame,
    y_holdout: pd.Series,
) -> np.ndarray:
    """Return 4x4 confusion matrix."""
    y_pred = model.predict(X_holdout)
    return confusion_matrix(y_holdout, y_pred)


def get_classification_report(
    model: lgb.LGBMClassifier,
    X_holdout: pd.DataFrame,
    y_holdout: pd.Series,
) -> str:
    """Return formatted classification report."""
    y_pred = model.predict(X_holdout)
    return classification_report(y_holdout, y_pred, target_names=TARGET_NAMES)
