"""
Loan Amount Model validation.

RMSE, MAE, R² metrics for ensemble and individual sub-models.
"""

from __future__ import annotations

import logging
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.preprocessing import StandardScaler

from shared.constants import LOAN_AMOUNT_MAX_GHS, LOAN_AMOUNT_MIN_GHS

logger = logging.getLogger("payswitch-cs.loan-amount.validator")

METRIC_THRESHOLDS = {
    "rmse_max": 2500.0,
    "mae_max": 1500.0,
    "r2_min": 0.55,
}


def evaluate_ensemble(
    lgbm_model: lgb.LGBMRegressor,
    ridge_model: Ridge,
    xgb_model: xgb.XGBRegressor,
    scaler: StandardScaler,
    X_holdout: pd.DataFrame,
    y_holdout: pd.Series,
) -> dict[str, float]:
    """Evaluate ensemble and individual sub-models on holdout."""
    pred_lgbm = lgbm_model.predict(X_holdout)
    pred_ridge = ridge_model.predict(scaler.transform(X_holdout))
    pred_xgb = xgb_model.predict(X_holdout)
    pred_ensemble = np.clip(
        (pred_lgbm + pred_ridge + pred_xgb) / 3.0,
        LOAN_AMOUNT_MIN_GHS, LOAN_AMOUNT_MAX_GHS,
    )

    metrics = {
        "ensemble_rmse": float(root_mean_squared_error(y_holdout, pred_ensemble)),
        "ensemble_mae": float(mean_absolute_error(y_holdout, pred_ensemble)),
        "ensemble_r2": float(r2_score(y_holdout, pred_ensemble)),
        "lgbm_r2": float(r2_score(y_holdout, pred_lgbm)),
        "ridge_r2": float(r2_score(y_holdout, pred_ridge)),
        "xgb_r2": float(r2_score(y_holdout, pred_xgb)),
    }

    logger.info(
        "Ensemble: RMSE=%.0f, MAE=%.0f, R²=%.4f | LGBM=%.4f, Ridge=%.4f, XGB=%.4f",
        metrics["ensemble_rmse"], metrics["ensemble_mae"], metrics["ensemble_r2"],
        metrics["lgbm_r2"], metrics["ridge_r2"], metrics["xgb_r2"],
    )
    return metrics


def check_thresholds(metrics: dict[str, float]) -> list[str]:
    """Check ensemble metrics against minimum thresholds."""
    warnings: list[str] = []

    if metrics["ensemble_rmse"] > METRIC_THRESHOLDS["rmse_max"]:
        warnings.append(f"RMSE {metrics['ensemble_rmse']:.0f} above max {METRIC_THRESHOLDS['rmse_max']:.0f}")
    if metrics["ensemble_mae"] > METRIC_THRESHOLDS["mae_max"]:
        warnings.append(f"MAE {metrics['ensemble_mae']:.0f} above max {METRIC_THRESHOLDS['mae_max']:.0f}")
    if metrics["ensemble_r2"] < METRIC_THRESHOLDS["r2_min"]:
        warnings.append(f"R² {metrics['ensemble_r2']:.4f} below min {METRIC_THRESHOLDS['r2_min']}")

    if warnings:
        for w in warnings:
            logger.warning("Threshold check FAILED: %s", w)
    else:
        logger.info("All metric thresholds passed")

    return warnings
