"""
Income Verification Model trainer.

LightGBM multiclass classifier for income tier prediction (4 classes).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import train_test_split

from shared.schemas.feature_schema import ALL_FEATURE_NAMES

logger = logging.getLogger("payswitch-cs.income-verification.trainer")

optuna.logging.set_verbosity(optuna.logging.WARNING)

TARGET_COLUMN = "income_tier"
NUM_CLASSES = 4


def prepare_data(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """
    Extract features + target, stratified split.

    Returns:
        (X_train, X_val, X_holdout, y_train, y_val, y_holdout)
    """
    df_clean = df.dropna(subset=[TARGET_COLUMN]).copy()
    df_clean[TARGET_COLUMN] = df_clean[TARGET_COLUMN].astype(int)

    X = df_clean[ALL_FEATURE_NAMES]
    y = df_clean[TARGET_COLUMN]

    X_trainval, X_holdout, y_trainval, y_holdout = train_test_split(
        X, y, test_size=0.15, random_state=42, stratify=y,
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=0.176, random_state=42, stratify=y_trainval,
    )

    logger.info(
        "Data split: train=%d, val=%d, holdout=%d | Class dist: %s",
        len(X_train), len(X_val), len(X_holdout),
        dict(y.value_counts().sort_index()),
    )
    return X_train, X_val, X_holdout, y_train, y_val, y_holdout


def select_features(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    threshold_pct: float = 0.95,
) -> list[str]:
    """Feature selection using LightGBM importance."""
    model = lgb.LGBMClassifier(
        objective="multiclass", num_class=NUM_CLASSES,
        n_estimators=300, random_state=42, verbosity=-1,
    )
    model.fit(X_train, y_train)

    importance = model.feature_importances_
    feature_names = list(X_train.columns)

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


def tune_and_train(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    n_trials: int = 50,
) -> lgb.LGBMClassifier:
    """Tune and train LightGBM multiclass classifier."""
    from sklearn.metrics import f1_score

    def objective(trial: optuna.Trial) -> float:
        params = {
            "objective": "multiclass",
            "num_class": NUM_CLASSES,
            "n_estimators": trial.suggest_int("n_estimators", 300, 800),
            "num_leaves": trial.suggest_int("num_leaves", 15, 50),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
            "reg_alpha": trial.suggest_float("reg_alpha", 0.01, 1.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 10.0),
            "subsample": trial.suggest_float("subsample", 0.7, 0.9),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 0.9),
            "random_state": 42,
            "verbosity": -1,
        }

        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_val)
        return f1_score(y_val, y_pred, average="weighted")

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials)

    logger.info("Best weighted F1: %.4f", study.best_value)

    # Train final on train + val
    best = study.best_params
    best.update({
        "objective": "multiclass",
        "num_class": NUM_CLASSES,
        "random_state": 42,
        "verbosity": -1,
    })
    model = lgb.LGBMClassifier(**best)
    model.fit(pd.concat([X_train, X_val]), pd.concat([y_train, y_val]))
    return model


def run_training_pipeline(
    df: pd.DataFrame,
    n_trials: int = 50,
) -> tuple[lgb.LGBMClassifier, list[str], dict[str, Any]]:
    """
    Full training pipeline.

    Returns:tsk
        (model, selected_features, training_info)
    """
    X_train, X_val, X_holdout, y_train, y_val, y_holdout = prepare_data(df)

    # Feature selection
    selected = select_features(X_train, y_train)
    X_train_sel = X_train[selected]
    X_val_sel = X_val[selected]

    # Train
    enable_tuning = os.environ.get("ENABLE_HYPERPARAMETER_TUNING", "true").lower() == "true"

    if enable_tuning:
        model = tune_and_train(X_train_sel, y_train, X_val_sel, y_val, n_trials)
    else:
        logger.info("Hyperparameter tuning DISABLED — using defaults")
        model = lgb.LGBMClassifier(
            objective="multiclass", num_class=NUM_CLASSES,
            n_estimators=500, num_leaves=31, learning_rate=0.05,
            min_child_samples=20, reg_alpha=0.1, reg_lambda=5.0,
            subsample=0.8, colsample_bytree=0.7,
            random_state=42, verbosity=-1,
        )
        model.fit(pd.concat([X_train_sel, X_val_sel]), pd.concat([y_train, y_val]))

    training_info = {
        "train_size": len(X_train),
        "val_size": len(X_val),
        "holdout_size": len(X_holdout),
        "features_selected": len(selected),
        "selected_feature_names": selected,
        "class_distribution": dict(y_train.value_counts().sort_index()),
    }

    return model, selected, training_info
