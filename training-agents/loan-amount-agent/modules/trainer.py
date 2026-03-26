"""
Loan Amount Recommendation Model trainer.

Ensemble of LightGBM + Ridge + XGBoost regressors.
Simple average of predictions, capped to GHS [500, 10000].
"""

from __future__ import annotations

import logging
import os
from typing import Any

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import Ridge
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from shared.constants import LOAN_AMOUNT_MAX_GHS, LOAN_AMOUNT_MIN_GHS
from shared.schemas.feature_schema import ALL_FEATURE_NAMES

logger = logging.getLogger("payswitch-cs.loan-amount.trainer")

optuna.logging.set_verbosity(optuna.logging.WARNING)

TARGET_COLUMN = "max_successful_loan_ghs"


def prepare_data(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """
    Extract features + target, drop nulls, clip target, split.

    Returns:
        (X_train, X_val, X_holdout, y_train, y_val, y_holdout)
    """
    df_clean = df.dropna(subset=[TARGET_COLUMN]).copy()

    # Clip target to valid range
    df_clean[TARGET_COLUMN] = df_clean[TARGET_COLUMN].clip(
        LOAN_AMOUNT_MIN_GHS, LOAN_AMOUNT_MAX_GHS,
    )

    X = df_clean[ALL_FEATURE_NAMES]
    y = df_clean[TARGET_COLUMN]

    X_trainval, X_holdout, y_trainval, y_holdout = train_test_split(
        X, y, test_size=0.15, random_state=42,
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=0.176, random_state=42,
    )

    logger.info(
        "Data split: train=%d, val=%d, holdout=%d",
        len(X_train), len(X_val), len(X_holdout),
    )
    return X_train, X_val, X_holdout, y_train, y_val, y_holdout


def select_features(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    threshold_pct: float = 0.95,
) -> list[str]:
    """
    Feature selection using LightGBM importance.

    Trains an initial model, ranks features, and selects
    the smallest subset explaining >= threshold_pct of total importance.

    Returns:
        List of selected feature names.
    """
    model = lgb.LGBMRegressor(n_estimators=300, random_state=42, verbosity=-1)
    model.fit(X_train, y_train)

    importance = model.feature_importances_
    feature_names = list(X_train.columns)

    # Sort by importance descending
    pairs = sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True)
    total = sum(imp for _, imp in pairs)

    selected = []
    cumulative = 0.0
    for name, imp in pairs:
        selected.append(name)
        cumulative += imp
        if cumulative / total >= threshold_pct:
            break

    logger.info("Selected %d/%d features (%.1f%% importance)", len(selected), len(feature_names), (cumulative / total) * 100)
    return selected


def tune_and_train_lgbm(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    n_trials: int = 30,
) -> lgb.LGBMRegressor:
    """Tune and train LightGBM regressor."""

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 300, 800),
            "num_leaves": trial.suggest_int("num_leaves", 15, 50),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
            "reg_alpha": trial.suggest_float("reg_alpha", 0.01, 1.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 10.0),
            "random_state": 42,
            "verbosity": -1,
        }
        model = lgb.LGBMRegressor(**params)
        model.fit(X_train, y_train)
        pred = model.predict(X_val)
        from sklearn.metrics import root_mean_squared_error
        return root_mean_squared_error(y_val, pred)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)

    best = study.best_params
    best.update({"random_state": 42, "verbosity": -1})
    model = lgb.LGBMRegressor(**best)
    model.fit(pd.concat([X_train, X_val]), pd.concat([y_train, y_val]))
    return model


def train_ridge(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
) -> tuple[Ridge, StandardScaler]:
    """Train Ridge regression with feature scaling."""
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)

    X_all = np.vstack([X_train_scaled, X_val_scaled])
    y_all = pd.concat([y_train, y_val])

    model = Ridge(alpha=1.0, fit_intercept=True)
    model.fit(X_all, y_all)
    return model, scaler


def tune_and_train_xgboost(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    n_trials: int = 30,
) -> xgb.XGBRegressor:
    """Tune and train XGBoost regressor."""

    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 300, 800),
            "max_depth": trial.suggest_int("max_depth", 4, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "subsample": trial.suggest_float("subsample", 0.7, 0.9),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 0.8),
            "random_state": 42,
            "verbosity": 0,
        }
        model = xgb.XGBRegressor(**params)
        model.fit(X_train, y_train, verbose=False)
        pred = model.predict(X_val)
        from sklearn.metrics import root_mean_squared_error
        return root_mean_squared_error(y_val, pred)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)

    best = study.best_params
    best.update({"random_state": 42, "verbosity": 0})
    model = xgb.XGBRegressor(**best)
    model.fit(pd.concat([X_train, X_val]), pd.concat([y_train, y_val]), verbose=False)
    return model


def ensemble_predict(
    lgbm_model: lgb.LGBMRegressor,
    ridge_model: Ridge,
    xgb_model: xgb.XGBRegressor,
    scaler: StandardScaler,
    X: pd.DataFrame,
) -> np.ndarray:
    """Simple average ensemble prediction, clipped to [500, 10000]."""
    pred_lgbm = lgbm_model.predict(X)
    pred_ridge = ridge_model.predict(scaler.transform(X))
    pred_xgb = xgb_model.predict(X)

    avg = (pred_lgbm + pred_ridge + pred_xgb) / 3.0
    return np.clip(avg, LOAN_AMOUNT_MIN_GHS, LOAN_AMOUNT_MAX_GHS)


def run_training_pipeline(
    df: pd.DataFrame,
    n_trials: int = 30,
) -> tuple[
    lgb.LGBMRegressor, Ridge, xgb.XGBRegressor, StandardScaler,
    list[str], dict[str, Any],
]:
    """
    Full training pipeline.

    Returns:
        (lgbm_model, ridge_model, xgb_model, scaler, selected_features, training_info)
    """
    X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

    # Feature selection
    selected = select_features(X_train, y_train, X_val, y_val)
    X_train_sel = X_train[selected]
    X_val_sel = X_val[selected]

    # Train 3 sub-models
    enable_tuning = os.environ.get("ENABLE_HYPERPARAMETER_TUNING", "true").lower() == "true"

    if enable_tuning:
        lgbm_model = tune_and_train_lgbm(X_train_sel, y_train, X_val_sel, y_val, n_trials)
        xgb_model = tune_and_train_xgboost(X_train_sel, y_train, X_val_sel, y_val, n_trials)
    else:
        logger.info("Hyperparameter tuning DISABLED — using defaults for LightGBM + XGBoost")
        lgbm_model = lgb.LGBMRegressor(
            n_estimators=500, num_leaves=31, learning_rate=0.05,
            min_child_samples=20, reg_alpha=0.1, reg_lambda=5.0,
            random_state=42, verbosity=-1,
        )
        lgbm_model.fit(pd.concat([X_train_sel, X_val_sel]), pd.concat([y_train, y_val]))

        xgb_model = xgb.XGBRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.7,
            random_state=42, verbosity=0,
        )
        xgb_model.fit(pd.concat([X_train_sel, X_val_sel]), pd.concat([y_train, y_val]))

    ridge_model, scaler = train_ridge(X_train_sel, y_train, X_val_sel, y_val)

    training_info = {
        "train_size": len(X_train),
        "val_size": len(X_val),
        "holdout_size": len(X_holdout),
        "features_selected": len(selected),
        "selected_feature_names": selected,
    }

    return lgbm_model, ridge_model, xgb_model, scaler, selected, training_info
