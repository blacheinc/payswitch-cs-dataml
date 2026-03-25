"""
Credit Risk Model trainer.

XGBoost binary classifier for predicting probability of default.
Uses Optuna for hyperparameter tuning, SHAP for explanations.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import optuna
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split

from shared.schemas.feature_schema import ALL_FEATURE_NAMES

logger = logging.getLogger("payswitch-cs.credit-risk.trainer")

# Silence Optuna info logs during tuning
optuna.logging.set_verbosity(optuna.logging.WARNING)

TARGET_COLUMN = "default_flag"


def prepare_data(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """
    Extract features + target and split into train/val/holdout.

    Split: 70% train / 15% validation / 15% holdout (stratified).

    Returns:
        (X_train, X_val, X_holdout, y_train, y_val, y_holdout)
    """
    # Drop rows where target is null (ambiguous records excluded)
    df_clean = df.dropna(subset=[TARGET_COLUMN]).copy()
    df_clean[TARGET_COLUMN] = df_clean[TARGET_COLUMN].astype(int)

    X = df_clean[ALL_FEATURE_NAMES]
    y = df_clean[TARGET_COLUMN]

    # First split: 85% train+val / 15% holdout
    X_trainval, X_holdout, y_trainval, y_holdout = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y,
    )

    # Second split: ~82.4% train / ~17.6% val (of trainval) → 70/15 of total
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=0.176, random_state=42, stratify=y_trainval,
    )

    logger.info(
        "Data split: train=%d, val=%d, holdout=%d (default rate: %.2f%%)",
        len(X_train), len(X_val), len(X_holdout),
        y.mean() * 100,
    )

    return X_train, X_val, X_holdout, y_train, y_val, y_holdout


def compute_scale_pos_weight(y_train: pd.Series) -> float:
    """Compute scale_pos_weight for class imbalance handling."""
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    if n_pos == 0:
        return 1.0
    weight = n_neg / n_pos
    logger.info("Class balance: neg=%d, pos=%d, scale_pos_weight=%.2f", n_neg, n_pos, weight)
    return weight


def tune_hyperparameters(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    scale_pos_weight: float,
    n_trials: int = 50,
) -> dict[str, Any]:
    """
    Run Optuna hyperparameter search optimizing AUC-ROC on validation set.

    Returns:
        Best hyperparameter dict.
    """
    def objective(trial: optuna.Trial) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 500, 1000),
            "max_depth": trial.suggest_int("max_depth", 4, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
            "subsample": trial.suggest_float("subsample", 0.7, 0.9),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 0.8),
            "min_child_weight": trial.suggest_int("min_child_weight", 3, 7),
            "reg_alpha": trial.suggest_float("reg_alpha", 0.01, 1.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 10.0),
            "scale_pos_weight": scale_pos_weight,
            "objective": "binary:logistic",
            "eval_metric": "auc",
            "random_state": 42,
            "verbosity": 0,
        }

        model = xgb.XGBClassifier(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        from sklearn.metrics import roc_auc_score
        y_pred_proba = model.predict_proba(X_val)[:, 1]
        return roc_auc_score(y_val, y_pred_proba)

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)

    logger.info("Best AUC: %.4f with params: %s", study.best_value, study.best_params)
    return study.best_params


def train_final_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    best_params: dict[str, Any],
    scale_pos_weight: float,
) -> xgb.XGBClassifier:
    """
    Train the final model with best hyperparameters on train + validation data.
    """
    # Combine train + val for final training (85% of data)
    X_final = pd.concat([X_train, X_val])
    y_final = pd.concat([y_train, y_val])

    params = {
        **best_params,
        "scale_pos_weight": scale_pos_weight,
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "random_state": 42,
        "verbosity": 0,
    }

    model = xgb.XGBClassifier(**params)
    model.fit(X_final, y_final, verbose=False)

    logger.info("Final model trained on %d records", len(X_final))
    return model


def run_training_pipeline(
    df: pd.DataFrame,
    n_trials: int = 50,
) -> tuple[xgb.XGBClassifier, dict[str, Any], dict[str, Any]]:
    """
    Full training pipeline: prepare → tune → train → return model + metadata.

    Returns:
        (trained_model, best_params, split_info)
    """
    X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

    # Class imbalance
    minority_pct = min(y_train.mean(), 1 - y_train.mean())
    scale_pos_weight = compute_scale_pos_weight(y_train) if minority_pct < 0.3 else 1.0

    # Tune
    best_params = tune_hyperparameters(
        X_train, y_train, X_val, y_val,
        scale_pos_weight=scale_pos_weight,
        n_trials=n_trials,
    )

    # Train final
    model = train_final_model(X_train, y_train, X_val, y_val, best_params, scale_pos_weight)

    split_info = {
        "train_size": len(X_train),
        "val_size": len(X_val),
        "holdout_size": len(X_holdout),
        "default_rate": float(y_train.mean()),
        "scale_pos_weight": scale_pos_weight,
    }

    return model, best_params, split_info
