"""
Income Verification Model registry integration.

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

import lightgbm as lgb
import mlflow
import mlflow.sklearn

from shared.constants import MODEL_REGISTRY_NAMES, ModelType

logger = logging.getLogger("payswitch-cs.income-verification.registry")

REGISTRY_NAME = MODEL_REGISTRY_NAMES[ModelType.INCOME_VERIFICATION]


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
    model: lgb.LGBMClassifier,
    selected_features: list[str],
    metrics: dict[str, Any],
    training_info: dict[str, Any],
    threshold_warnings: list[str],
    model_version: str = "1.0.0",
) -> str:
    """Log model and register in Azure ML."""
    # Step 1: MLflow local tracking
    with mlflow.start_run(run_name=f"income-verification-{model_version}") as run:
        mlflow.log_params({
            "model_type": "lightgbm_multiclass",
            "model_version": model_version,
            "num_classes": 4,
            "features_selected": len(selected_features),
        })

        # Flatten nested metrics for MLflow
        flat_metrics = {
            "auc_ovr": metrics["auc_ovr"],
            "weighted_f1": metrics["weighted_f1"],
        }
        for cls_name, val in metrics.get("per_class_recall", {}).items():
            flat_metrics[f"recall_{cls_name}"] = val
        for cls_name, val in metrics.get("per_class_precision", {}).items():
            flat_metrics[f"precision_{cls_name}"] = val

        mlflow.log_metrics(flat_metrics)

        mlflow.sklearn.log_model(model, name="model")
        mlflow.log_text(json.dumps(selected_features), "selected_features.json")

        if threshold_warnings:
            mlflow.log_text("\n".join(threshold_warnings), "threshold_warnings.txt")

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

            # Save feature list
            with open(os.path.join(tmpdir, "selected_features.json"), "w") as f:
                json.dump(selected_features, f)

            # Save metrics
            with open(os.path.join(tmpdir, "metrics.json"), "w") as f:
                json.dump(metrics, f, indent=2)

            azure_model = Model(
                name=REGISTRY_NAME,
                path=tmpdir,
                type=AssetTypes.CUSTOM_MODEL,
                description=f"Income Verification LightGBM multiclass v{model_version}",
                tags={
                    "model_version": model_version,
                    "weighted_f1": str(round(metrics.get("weighted_f1", 0), 4)),
                    "auc_ovr": str(round(metrics.get("auc_ovr", 0), 4)),
                    "features_selected": str(len(selected_features)),
                },
            )

            registered = ml_client.models.create_or_update(azure_model)
            logger.info("Model registered in Azure ML: %s v%s", registered.name, registered.version)
            return registered.version

    except Exception:
        logger.exception("Failed to register in Azure ML — model logged to MLflow only")
        return model_version


def load_champion_model() -> tuple[lgb.LGBMClassifier, list[str], str]:
    """
    Load the latest model + selected features from Azure ML registry.

    Returns:
        (model, selected_features, model_version)
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

        with open(os.path.join(model_dir, "selected_features.json")) as f:
            selected_features = json.load(f)

        logger.info("Loaded model %s v%s from Azure ML", REGISTRY_NAME, latest.version)
        return model, selected_features, latest.version

    except Exception:
        logger.exception("Failed to load from Azure ML")
        raise
