"""
Credit Risk Model MLflow registry integration.

Handles model logging, registration, and loading from Azure ML MLflow.
"""

from __future__ import annotations

import logging
from typing import Any

import mlflow
import mlflow.xgboost
import xgboost as xgb

from shared.constants import MODEL_REGISTRY_NAMES, ModelType

logger = logging.getLogger("payswitch-cs.credit-risk.registry")

REGISTRY_NAME = MODEL_REGISTRY_NAMES[ModelType.CREDIT_RISK]


def log_and_register_model(
    model: xgb.XGBClassifier,
    metrics: dict[str, float],
    best_params: dict[str, Any],
    split_info: dict[str, Any],
    threshold_warnings: list[str],
    feature_importance: list[dict[str, Any]],
    model_version: str = "1.0.0",
) -> str:
    """
    Log model, metrics, and artifacts to MLflow and register.

    Returns:
        The registered model version string.
    """
    with mlflow.start_run(run_name=f"credit-risk-{model_version}") as run:
        # Log hyperparameters
        mlflow.log_params(best_params)
        mlflow.log_params({
            "model_type": "xgboost_binary_classifier",
            "model_version": model_version,
            "target_column": "default_flag",
            "feature_count": 30,
        })

        # Log split info
        mlflow.log_params({f"split_{k}": v for k, v in split_info.items()})

        # Log metrics
        mlflow.log_metrics(metrics)

        # Log model
        mlflow.xgboost.log_model(
            model,
            artifact_path="model",
            registered_model_name=REGISTRY_NAME,
        )

        # Log feature importance as artifact
        import json
        importance_json = json.dumps(feature_importance, indent=2)
        mlflow.log_text(importance_json, "feature_importance.json")

        # Log warnings if any
        if threshold_warnings:
            mlflow.log_text("\n".join(threshold_warnings), "threshold_warnings.txt")
            mlflow.set_tag("threshold_warnings", "true")

        mlflow.set_tag("model_version", model_version)

        logger.info(
            "Model registered as %s (run_id=%s)",
            REGISTRY_NAME, run.info.run_id,
        )

        return model_version


def load_champion_model() -> xgb.XGBClassifier:
    """
    Load the Champion model from MLflow registry.

    Returns:
        Loaded XGBoost model ready for inference.
    """
    model_uri = f"models:/{REGISTRY_NAME}/Champion"
    model = mlflow.xgboost.load_model(model_uri)
    logger.info("Loaded champion model from %s", model_uri)
    return model
