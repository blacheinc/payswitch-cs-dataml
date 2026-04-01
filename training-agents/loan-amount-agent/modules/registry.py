"""
Loan Amount Model registry integration.

Uses MLflow for local experiment tracking.
Uses Azure ML SDK (azure-ai-ml) for model registration.
Logs 3 sub-models + scaler + feature list as a single registered model.
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
warnings.filterwarnings("ignore", message=".*Model was missing function.*")

import lightgbm as lgb
import mlflow
import mlflow.sklearn
import mlflow.xgboost
import xgboost as xgb
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from shared.constants import MODEL_REGISTRY_NAMES, ModelType

logger = logging.getLogger("payswitch-cs.loan-amount.registry")

REGISTRY_NAME = MODEL_REGISTRY_NAMES[ModelType.LOAN_AMOUNT]


def _should_promote(
    ml_client, registry_name: str, new_metrics: dict[str, float], primary_metric: str = "ensemble_r2",
) -> tuple[bool, dict]:
    """Champion-Challenger comparison. Returns (should_promote, info)."""
    try:
        models = list(ml_client.models.list(name=registry_name))
        if not models:
            return True, {}
        latest = max(models, key=lambda m: int(m.version))
        champion_metrics = json.loads(latest.properties.get("metrics", "{}"))
        champion_value = champion_metrics.get(primary_metric, 0)
        new_value = new_metrics.get(primary_metric, 0)
        info = {"champion_version": latest.version, "champion_value": champion_value, "new_value": new_value}
        if new_value >= champion_value:
            logger.info("Challenger wins: %s %.4f >= champion %.4f (v%s)", primary_metric, new_value, champion_value, latest.version)
            return True, info
        logger.info("Champion retains: %s %.4f < champion %.4f (v%s)", primary_metric, new_value, champion_value, latest.version)
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
    lgbm_model: lgb.LGBMRegressor,
    ridge_model: Ridge,
    xgb_model: xgb.XGBRegressor,
    scaler: StandardScaler,
    selected_features: list[str],
    metrics: dict[str, float],
    training_info: dict[str, Any],
    threshold_warnings: list[str],
    model_version: str = "1.0.0",
) -> str:
    """Log all sub-models and register in Azure ML."""
    # Step 1: MLflow local tracking
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
    mlflow.set_tracking_uri(tracking_uri)
    try:
        mlflow.create_experiment("loan-amount", artifact_location="/tmp/mlruns")
    except Exception:
        pass
    mlflow.set_experiment("loan-amount")
    with mlflow.start_run(run_name=f"loan-amount-{model_version}") as run:
        mlflow.log_params({
            "model_type": "ensemble_lgbm_ridge_xgb",
            "model_version": model_version,
            "features_selected": len(selected_features),
        })

        mlflow.log_metrics(metrics)

        mlflow.sklearn.log_model(lgbm_model, artifact_path="lgbm_model")
        mlflow.sklearn.log_model(ridge_model, artifact_path="ridge_model")
        mlflow.xgboost.log_model(xgb_model, artifact_path="xgb_model")
        mlflow.sklearn.log_model(scaler, artifact_path="scaler")

        mlflow.log_text(json.dumps(selected_features), "selected_features.json")

        if threshold_warnings:
            mlflow.log_text("\n".join(threshold_warnings), "threshold_warnings.txt")

        mlflow.set_tag("model_version", model_version)
        logger.info("MLflow run logged: %s (run_id=%s)", REGISTRY_NAME, run.info.run_id)

    # Step 2: Register in Azure ML (with champion-challenger gate)
    try:
        from azure.ai.ml.constants import AssetTypes
        from azure.ai.ml.entities import Model

        ml_client = _get_azure_ml_client()

        should_register, champion_info = _should_promote(ml_client, REGISTRY_NAME, metrics)
        if not should_register:
            logger.warning("Model NOT promoted — new R2 %.4f <= champion R2 %.4f (v%s)",
                           metrics.get("ensemble_r2", 0), champion_info.get("champion_value", 0),
                           champion_info.get("champion_version", "?"))
            return f"REJECTED:champion_v{champion_info.get('champion_version', '?')}"

        with tempfile.TemporaryDirectory() as tmpdir:
            # Save all sub-models
            with open(os.path.join(tmpdir, "lgbm_model.pkl"), "wb") as f:
                pickle.dump(lgbm_model, f)
            with open(os.path.join(tmpdir, "ridge_model.pkl"), "wb") as f:
                pickle.dump(ridge_model, f)

            xgb_path = os.path.join(tmpdir, "xgb_model.ubj")
            xgb_model.save_model(xgb_path)

            with open(os.path.join(tmpdir, "scaler.pkl"), "wb") as f:
                pickle.dump(scaler, f)

            with open(os.path.join(tmpdir, "selected_features.json"), "w") as f:
                json.dump(selected_features, f)

            with open(os.path.join(tmpdir, "metrics.json"), "w") as f:
                json.dump(metrics, f, indent=2)

            azure_model = Model(
                name=REGISTRY_NAME,
                path=tmpdir,
                type=AssetTypes.CUSTOM_MODEL,
                description=f"Loan Amount ensemble (LightGBM+Ridge+XGBoost) v{model_version}",
                tags={
                    "model_version": model_version,
                    "ensemble_r2": str(round(metrics.get("ensemble_r2", 0), 4)),
                    "ensemble_rmse": str(round(metrics.get("ensemble_rmse", 0), 2)),
                    "features_selected": str(len(selected_features)),
                },
            )

            registered = ml_client.models.create_or_update(azure_model)
            logger.info("Model registered in Azure ML: %s v%s", registered.name, registered.version)
            return registered.version

    except Exception:
        logger.exception("Failed to register in Azure ML — model logged to MLflow only")
        return model_version


def load_champion_models() -> tuple[lgb.LGBMRegressor, Ridge, xgb.XGBRegressor, StandardScaler, list[str], str]:
    """
    Load the latest ensemble from Azure ML registry.

    Returns:
        (lgbm_model, ridge_model, xgb_model, scaler, selected_features, model_version)
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

        pkl_files = glob.glob(os.path.join(download_dir, "**", "lgbm_model.pkl"), recursive=True)
        if not pkl_files:
            raise RuntimeError(f"lgbm_model.pkl not found in {download_dir}")

        model_dir = os.path.dirname(pkl_files[0])

        with open(os.path.join(model_dir, "lgbm_model.pkl"), "rb") as f:
            lgbm_model = pickle.load(f)
        with open(os.path.join(model_dir, "ridge_model.pkl"), "rb") as f:
            ridge_model = pickle.load(f)

        xgb_model = xgb.XGBRegressor()
        xgb_path = os.path.join(model_dir, "xgb_model.ubj")
        if not os.path.exists(xgb_path):
            xgb_path = os.path.join(model_dir, "xgb_model.xgb")
        xgb_model.load_model(xgb_path)

        with open(os.path.join(model_dir, "scaler.pkl"), "rb") as f:
            scaler = pickle.load(f)

        with open(os.path.join(model_dir, "selected_features.json")) as f:
            selected_features = json.load(f)

        logger.info("Loaded ensemble %s v%s from Azure ML", REGISTRY_NAME, latest.version)
        return lgbm_model, ridge_model, xgb_model, scaler, selected_features, latest.version

    except Exception:
        logger.exception("Failed to load from Azure ML")
        raise
