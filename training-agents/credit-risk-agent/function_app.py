"""
Credit Risk Agent — Azure Function App.

Service Bus triggered functions for training and inference.
XGBoost binary classifier for probability of default prediction.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time

import azure.functions as func
import pandas as pd
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from shared.constants import ModelType, ServiceBusTopic
from shared.schemas.feature_schema import ALL_FEATURE_NAMES
from shared.schemas.message_schemas import (
    CreditRiskPredictionResult,
    ModelTrainingCompleteMessage,
    TrainModelMessage,
)

logger = logging.getLogger("payswitch-cs.credit-risk")

app = func.FunctionApp()

SERVICE_BUS_CONNECTION = os.environ.get("SERVICE_BUS_CONNECTION", "")
STORAGE_CONNECTION = os.environ.get("STORAGE_CONNECTION", "")


@app.function_name("credit_risk_train")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="credit-risk-train",
    subscription_name="credit-risk-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def credit_risk_train(message: func.ServiceBusMessage) -> None:
    """Handle training requests from the Orchestrator."""
    start_time = time.time()
    raw = message.get_body().decode("utf-8")
    msg = TrainModelMessage.from_json(raw)
    training_id = msg.training_id

    logger.info("Credit Risk training started: %s", training_id)

    try:
        from azure.storage.blob import BlobServiceClient

        from modules.registry import log_and_register_model
        from modules.trainer import prepare_data, run_training_pipeline
        from modules.validator import (
            check_thresholds,
            evaluate_model,
            get_feature_importance,
        )

        # Load dataset
        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_client.get_container_client("curated")
        blob_data = container.get_blob_client(msg.dataset_path).download_blob().readall()
        df = pd.read_parquet(io.BytesIO(blob_data))

        # Train
        model, best_params, split_info = run_training_pipeline(df, n_trials=50)

        # Evaluate on holdout
        _, _, X_holdout, _, _, y_holdout = prepare_data(df)
        metrics = evaluate_model(model, X_holdout, y_holdout)
        warnings = check_thresholds(metrics)
        importance = get_feature_importance(model)

        # Register
        model_version = log_and_register_model(
            model, metrics, best_params, split_info, warnings, importance,
        )

        # Publish completion
        elapsed = time.time() - start_time
        result_msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.CREDIT_RISK.value,
            status="SUCCESS",
            model_version=model_version,
            registry_name="credit-scoring-risk-xgboost",
            metrics=metrics,
            training_duration_seconds=elapsed,
            dataset_records_used=split_info["train_size"] + split_info["val_size"] + split_info["holdout_size"],
            class_distribution={
                "default_0": int((1 - split_info["default_rate"]) * split_info["train_size"]),
                "default_1": int(split_info["default_rate"] * split_info["train_size"]),
            },
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result_msg.to_json()))

        logger.info("Credit Risk training complete: %s (%.1fs)", training_id, elapsed)

    except Exception as exc:
        logger.exception("Credit Risk training failed: %s", training_id)
        _publish_failure(training_id, str(exc))


@app.function_name("credit_risk_predict")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="credit-risk-predict",
    subscription_name="credit-risk-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def credit_risk_predict(message: func.ServiceBusMessage) -> None:
    """Handle prediction requests from the Orchestrator."""
    raw = message.get_body().decode("utf-8")
    data = json.loads(raw)
    request_id = data["request_id"]
    features = data["features"]

    logger.info("Credit Risk prediction started: %s", request_id)

    try:
        from modules.registry import load_champion_model
        from modules.validator import compute_shap_explanation

        # Load model
        model, model_version, calibration_params = load_champion_model()

        # Prepare features
        X = pd.DataFrame([features])[ALL_FEATURE_NAMES]

        # Predict
        proba = model.predict_proba(X)
        raw_pd = float(proba[0, 1])

        # Apply Platt Scaling if calibration params available
        if calibration_params:
            from modules.trainer import apply_platt_scaling
            probability_of_default = apply_platt_scaling(
                raw_pd, calibration_params["A"], calibration_params["B"],
            )
            logger.info("PD calibrated: raw=%.4f → calibrated=%.4f", raw_pd, probability_of_default)
        else:
            probability_of_default = raw_pd

        pd_confidence = max(probability_of_default, 1.0 - probability_of_default)

        # SHAP explanation
        contributions, reason_codes = compute_shap_explanation(model, X)

        # Publish result
        result = CreditRiskPredictionResult(
            request_id=request_id,
            probability_of_default=round(probability_of_default, 6),
            pd_confidence=round(pd_confidence, 4),
            shap_contributions=contributions,
            decision_reason_codes=reason_codes,
            model_version=model_version,
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.PREDICTION_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result.to_json()))

        logger.info(
            "Credit Risk prediction complete: %s (PD=%.4f)",
            request_id, probability_of_default,
        )

    except Exception as exc:
        logger.exception("Credit Risk prediction failed: %s", request_id)
        # Publish error result so orchestrator doesn't hang
        try:
            error_result = CreditRiskPredictionResult(
                request_id=request_id,
                probability_of_default=0.5,
                pd_confidence=0.0,
                shap_contributions=[],
                decision_reason_codes=[],
                model_version=f"ERROR:{type(exc).__name__}:{str(exc)[:200]}",
            )
            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
                sender = sb_client.get_topic_sender(ServiceBusTopic.PREDICTION_COMPLETE.value)
                with sender:
                    sender.send_messages(ServiceBusMessage(error_result.to_json()))
        except Exception:
            logger.exception("Failed to publish prediction error for %s", request_id)


def _publish_failure(training_id: str, error: str) -> None:
    """Publish training failure to model-training-complete."""
    try:
        msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.CREDIT_RISK.value,
            status="FAILED",
            error_message=error,
        )
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(msg.to_json()))
    except Exception:
        logger.exception("Failed to publish training failure for %s", training_id)
