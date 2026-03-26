"""
Credit Risk Model registry integration.

Uses MLflow for local experiment tracking (metrics, params, artifacts).
Uses Azure ML SDK (azure-ai-ml) for model registration in Azure ML workspace.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

import mlflow
import mlflow.xgboost
import xgboost as xgb

from shared.constants import MODEL_REGISTRY_NAMES, ModelType

logger = logging.getLogger("payswitch-cs.credit-risk.registry")

REGISTRY_NAME = MODEL_REGISTRY_NAMES[ModelType.CREDIT_RISK]


def _get_azure_ml_client():
    """Create Azure ML client from environment variables."""
    from azure.ai.ml import MLClient
    from azure.identity import DefaultAzureCredential

    return MLClient(
        credential=DefaultAzureCredential(),
        subscription_id=os.environ.get("AZURE_ML_SUBSCRIPTION_ID", ""),
        resource_group_name=os.environ.get("AZURE_ML_RESOURCE_GROUP", ""),
        workspace_name=os.environ.get("AZURE_ML_WORKSPACE_NAME", ""),
    )


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
    Log model to MLflow (local tracking) and register in Azure ML.

    Returns:
        The registered model version string.
    """
    # Step 1: Log to MLflow (local experiment tracking)
    with mlflow.start_run(run_name=f"credit-risk-{model_version}") as run:
        mlflow.log_params(best_params)
        mlflow.log_params({
            "model_type": "xgboost_binary_classifier",
            "model_version": model_version,
            "target_column": "default_flag",
            "feature_count": 30,
        })
        mlflow.log_params({f"split_{k}": v for k, v in split_info.items()})
        mlflow.log_metrics(metrics)

        mlflow.xgboost.log_model(model, name="model")

        importance_json = json.dumps(feature_importance, indent=2)
        mlflow.log_text(importance_json, "feature_importance.json")

        if threshold_warnings:
            mlflow.log_text("\n".join(threshold_warnings), "threshold_warnings.txt")
            mlflow.set_tag("threshold_warnings", "true")

        mlflow.set_tag("model_version", model_version)

        logger.info("MLflow run logged: %s (run_id=%s)", REGISTRY_NAME, run.info.run_id)

    # Step 2: Register in Azure ML model registry
    try:
        from azure.ai.ml.entities import Model
        from azure.ai.ml.constants import AssetTypes

        ml_client = _get_azure_ml_client()

        # Save model to temp dir for registration
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "model.xgb")
            model.save_model(model_path)

            # Save metrics alongside
            metrics_path = os.path.join(tmpdir, "metrics.json")
            with open(metrics_path, "w") as f:
                json.dump(metrics, f, indent=2)

            azure_model = Model(
                name=REGISTRY_NAME,
                path=tmpdir,
                type=AssetTypes.CUSTOM_MODEL,
                description=f"Credit Risk XGBoost model v{model_version}",
                tags={
                    "model_version": model_version,
                    "auc": str(round(metrics.get("auc", 0), 4)),
                    "f1": str(round(metrics.get("f1", 0), 4)),
                },
                properties={
                    "metrics": json.dumps(metrics),
                    "best_params": json.dumps(best_params),
                },
            )

            registered = ml_client.models.create_or_update(azure_model)
            logger.info(
                "Model registered in Azure ML: %s v%s",
                registered.name, registered.version,
            )
            return registered.version

    except Exception:
        logger.exception("Failed to register in Azure ML — model logged to MLflow only")
        return model_version


def load_champion_model() -> tuple[xgb.XGBClassifier, str]:
    """
    Load the latest model from Azure ML registry.

    Returns:
        Tuple of (loaded XGBoost model, model version string).
    """
    try:
        ml_client = _get_azure_ml_client()

        # Get latest version
        models = list(ml_client.models.list(name=REGISTRY_NAME))
        if not models:
            raise RuntimeError(f"No model found for {REGISTRY_NAME}")

        latest = max(models, key=lambda m: int(m.version))
        download_dir = f"./{REGISTRY_NAME}"
        ml_client.models.download(name=REGISTRY_NAME, version=latest.version, download_path=download_dir)

        # Find model.xgb in the downloaded directory
        import glob
        xgb_files = glob.glob(os.path.join(download_dir, "**", "model.xgb"), recursive=True)
        if not xgb_files:
            raise RuntimeError(f"model.xgb not found in downloaded artifacts at {download_dir}")

        model = xgb.XGBClassifier()
        model.load_model(xgb_files[0])

        logger.info("Loaded model %s v%s from Azure ML (%s)", REGISTRY_NAME, latest.version, xgb_files[0])
        return model, latest.version

    except Exception:
        logger.exception("Failed to load from Azure ML — falling back to local MLflow")
        model_uri = f"models:/{REGISTRY_NAME}/latest"
        model = mlflow.xgboost.load_model(model_uri)
        return model, "local"
