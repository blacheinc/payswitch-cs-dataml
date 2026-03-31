"""
Fraud Detection Model registry integration.

Uses MLflow for local experiment tracking.
Uses Azure ML SDK (azure-ai-ml) for model registration.
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import tempfile
from typing import Any

import warnings
warnings.filterwarnings("ignore", message=".*pickle.*cloudpickle.*")
warnings.filterwarnings("ignore", message=".*Failed to resolve installed pip.*")

import mlflow
import mlflow.sklearn
from sklearn.ensemble import IsolationForest

from shared.constants import MODEL_REGISTRY_NAMES, ModelType

logger = logging.getLogger("payswitch-cs.fraud-detection.registry")

REGISTRY_NAME = MODEL_REGISTRY_NAMES[ModelType.FRAUD_DETECTION]


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
    model: IsolationForest,
    thresholds: dict[str, float],
    training_info: dict[str, Any],
    distribution_warnings: list[str],
    sanity_check: dict[str, Any],
    model_version: str = "1.0.0",
) -> str:
    """Log model + thresholds and register in Azure ML."""
    # Step 1: MLflow local tracking
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    mlflow.set_tracking_uri(tracking_uri)
    try:
        mlflow.create_experiment("fraud-detection", artifact_location="/tmp/mlruns")
    except Exception:
        pass
    mlflow.set_experiment("fraud-detection")
    with mlflow.start_run(run_name=f"fraud-detection-{model_version}") as run:
        mlflow.log_params({
            "model_type": "isolation_forest",
            "model_version": model_version,
            "contamination": training_info.get("contamination", 0.03),
            "n_estimators": model.n_estimators,
        })

        mlflow.log_metrics({
            "low_pct": training_info["low_pct"],
            "medium_pct": training_info["medium_pct"],
            "high_pct": training_info["high_pct"],
        })

        mlflow.sklearn.log_model(model, artifact_path="model")
        mlflow.log_text(json.dumps(thresholds, indent=2), "threshold_params.json")
        mlflow.log_text(json.dumps(sanity_check, indent=2), "sanity_check.json")

        if distribution_warnings:
            mlflow.log_text("\n".join(distribution_warnings), "distribution_warnings.txt")

        mlflow.set_tag("model_version", model_version)
        logger.info("MLflow run logged: %s (run_id=%s)", REGISTRY_NAME, run.info.run_id)

    # Step 2: Register in Azure ML
    try:
        from azure.ai.ml.constants import AssetTypes
        from azure.ai.ml.entities import Model

        ml_client = _get_azure_ml_client()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Save model
            model_path = os.path.join(tmpdir, "model.pkl")
            with open(model_path, "wb") as f:
                pickle.dump(model, f)

            # Save thresholds (needed at inference)
            thresh_path = os.path.join(tmpdir, "threshold_params.json")
            with open(thresh_path, "w") as f:
                json.dump(thresholds, f, indent=2)

            azure_model = Model(
                name=REGISTRY_NAME,
                path=tmpdir,
                type=AssetTypes.CUSTOM_MODEL,
                description=f"Fraud Detection IsolationForest v{model_version}",
                tags={
                    "model_version": model_version,
                    "low_pct": str(round(training_info["low_pct"], 4)),
                    "high_pct": str(round(training_info["high_pct"], 4)),
                },
            )

            registered = ml_client.models.create_or_update(azure_model)
            logger.info("Model registered in Azure ML: %s v%s", registered.name, registered.version)
            return registered.version

    except Exception:
        logger.exception("Failed to register in Azure ML — model logged to MLflow only")
        return model_version


def load_champion_model() -> tuple[IsolationForest, dict[str, float], str]:
    """
    Load the latest model + thresholds from Azure ML registry.

    Returns:
        (model, thresholds, model_version)
    """
    try:
        import glob

        ml_client = _get_azure_ml_client()

        models = list(ml_client.models.list(name=REGISTRY_NAME))
        if not models:
            raise RuntimeError(f"No model found for {REGISTRY_NAME}")

        latest = max(models, key=lambda m: int(m.version))
        download_dir = f"./{REGISTRY_NAME}"
        ml_client.models.download(name=REGISTRY_NAME, version=latest.version, download_path=download_dir)

        pkl_files = glob.glob(os.path.join(download_dir, "**", "model.pkl"), recursive=True)
        if not pkl_files:
            raise RuntimeError(f"model.pkl not found in {download_dir}")

        model_dir = os.path.dirname(pkl_files[0])

        with open(pkl_files[0], "rb") as f:
            model = pickle.load(f)

        with open(os.path.join(model_dir, "threshold_params.json")) as f:
            thresholds = json.load(f)

        logger.info("Loaded model %s v%s from Azure ML", REGISTRY_NAME, latest.version)
        return model, thresholds, latest.version

    except Exception:
        logger.exception("Failed to load from Azure ML")
        raise
