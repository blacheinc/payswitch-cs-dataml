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

import warnings
warnings.filterwarnings("ignore", message=".*pickle.*cloudpickle.*")
warnings.filterwarnings("ignore", message=".*Failed to resolve installed pip.*")

import mlflow
import mlflow.xgboost
import xgboost as xgb

from shared.constants import MODEL_REGISTRY_NAMES, ModelType

logger = logging.getLogger("payswitch-cs.credit-risk.registry")

REGISTRY_NAME = MODEL_REGISTRY_NAMES[ModelType.CREDIT_RISK]


def _should_promote(
    ml_client,
    registry_name: str,
    new_metrics: dict[str, float],
    primary_metric: str = "auc",
) -> tuple[bool, dict]:
    """
    Champion-Challenger comparison (BLD Section 5.3).

    Compares new model's primary metric against current champion.
    Returns (should_promote, champion_info_dict).
    """
    try:
        models = list(ml_client.models.list(name=registry_name))
        if not models:
            logger.info("No existing champion — first model will be promoted")
            return True, {}

        latest = max(models, key=lambda m: int(m.version))
        champion_metrics = json.loads(latest.properties.get("metrics", "{}"))
        champion_value = champion_metrics.get(primary_metric, 0)
        new_value = new_metrics.get(primary_metric, 0)

        info = {
            "champion_version": latest.version,
            "champion_value": champion_value,
            "new_value": new_value,
        }

        if new_value >= champion_value:
            logger.info(
                "Challenger wins: %s %.4f >= champion %.4f (v%s)",
                primary_metric, new_value, champion_value, latest.version,
            )
            return True, info
        else:
            logger.info(
                "Champion retains: %s %.4f < champion %.4f (v%s)",
                primary_metric, new_value, champion_value, latest.version,
            )
            return False, info

    except Exception:
        logger.warning("Cannot compare with champion — promoting by default")
        return True, {}


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
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    mlflow.set_tracking_uri(tracking_uri)
    # Create experiment with /tmp artifact root (Azure Functions filesystem is read-only)
    exp_name = "credit-risk"
    try:
        mlflow.create_experiment(exp_name, artifact_location="/tmp/mlruns")
    except Exception:
        pass  # Already exists
    mlflow.set_experiment(exp_name)
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

        mlflow.xgboost.log_model(model, artifact_path="model")

        importance_json = json.dumps(feature_importance, indent=2)
        mlflow.log_text(importance_json, "feature_importance.json")

        if threshold_warnings:
            mlflow.log_text("\n".join(threshold_warnings), "threshold_warnings.txt")
            mlflow.set_tag("threshold_warnings", "true")

        mlflow.set_tag("model_version", model_version)

        logger.info("MLflow run logged: %s (run_id=%s)", REGISTRY_NAME, run.info.run_id)

    # Step 2: Register in Azure ML model registry (with champion-challenger gate)
    try:
        from azure.ai.ml.entities import Model
        from azure.ai.ml.constants import AssetTypes

        ml_client = _get_azure_ml_client()

        # Champion-Challenger: compare before promoting
        should_register, champion_info = _should_promote(
            ml_client, REGISTRY_NAME, metrics, primary_metric="auc",
        )
        if not should_register:
            logger.warning(
                "Model NOT promoted — new AUC %.4f <= champion AUC %.4f (v%s)",
                metrics.get("auc", 0), champion_info.get("champion_value", 0),
                champion_info.get("champion_version", "?"),
            )
            return f"REJECTED:champion_v{champion_info.get('champion_version', '?')}_auc_{champion_info.get('champion_value', 0):.4f}"

        # Save model to temp dir for registration
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "model.ubj")
            model.save_model(model_path)

            # Save metrics alongside
            metrics_path = os.path.join(tmpdir, "metrics.json")
            with open(metrics_path, "w") as f:
                json.dump(metrics, f, indent=2)

            # Save Platt Scaling calibration params (BLD Section 6.2)
            if split_info.get("calibration_A") is not None:
                cal_path = os.path.join(tmpdir, "calibration_params.json")
                with open(cal_path, "w") as f:
                    json.dump({
                        "A": split_info["calibration_A"],
                        "B": split_info["calibration_B"],
                    }, f, indent=2)

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


def load_champion_model() -> tuple[xgb.XGBClassifier, str, dict[str, float] | None]:
    """
    Load the latest model + calibration params from Azure ML registry.

    Returns:
        Tuple of (loaded XGBoost model, model version, calibration_params or None).
    """
    try:
        import glob

        ml_client = _get_azure_ml_client()

        models = list(ml_client.models.list(name=REGISTRY_NAME))
        if not models:
            raise RuntimeError(f"No model found for {REGISTRY_NAME}")

        latest = max(models, key=lambda m: int(m.version))
        download_dir = f"/tmp/{REGISTRY_NAME}"
        ml_client.models.download(name=REGISTRY_NAME, version=latest.version, download_path=download_dir)

        # Find model file (.ubj or .xgb)
        xgb_files = glob.glob(os.path.join(download_dir, "**", "model.ubj"), recursive=True)
        if not xgb_files:
            xgb_files = glob.glob(os.path.join(download_dir, "**", "model.xgb"), recursive=True)
        if not xgb_files:
            raise RuntimeError(f"model.ubj/model.xgb not found in {download_dir}")

        model = xgb.XGBClassifier()
        model.load_model(xgb_files[0])

        # Load Platt Scaling calibration params if available
        model_dir = os.path.dirname(xgb_files[0])
        calibration_params = None
        cal_path = os.path.join(model_dir, "calibration_params.json")
        if os.path.exists(cal_path):
            with open(cal_path) as f:
                calibration_params = json.load(f)
            logger.info("Loaded calibration params: A=%.4f, B=%.4f",
                        calibration_params["A"], calibration_params["B"])

        logger.info("Loaded model %s v%s from Azure ML", REGISTRY_NAME, latest.version)
        return model, latest.version, calibration_params

    except Exception as exc:
        logger.exception("Failed to load from Azure ML")
        raise RuntimeError(f"Cannot load model: {type(exc).__name__}: {exc}") from exc
