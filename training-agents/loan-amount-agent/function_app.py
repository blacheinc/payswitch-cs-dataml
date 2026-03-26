"""
Loan Amount Agent — Azure Function App.

Ensemble regression (LightGBM + Ridge + XGBoost) for loan amount recommendation.
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
from shared.schemas.message_schemas import (
    LoanAmountPredictionResult,
    ModelTrainingCompleteMessage,
    TrainModelMessage,
)

logger = logging.getLogger("payswitch-cs.loan-amount")

app = func.FunctionApp()

SERVICE_BUS_CONNECTION = os.environ.get("SERVICE_BUS_CONNECTION", "")
STORAGE_CONNECTION = os.environ.get("STORAGE_CONNECTION", "")


@app.function_name("loan_amount_train")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="loan-amount-train",
    subscription_name="loan-amount-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def loan_amount_train(message: func.ServiceBusMessage) -> None:
    """Handle training requests from the Orchestrator."""
    start_time = time.time()
    raw = message.get_body().decode("utf-8")
    msg = TrainModelMessage.from_json(raw)
    training_id = msg.training_id

    logger.info("Loan Amount training started: %s", training_id)

    try:
        from azure.storage.blob import BlobServiceClient

        from modules.registry import log_and_register_model
        from modules.trainer import (
            prepare_data,
            run_training_pipeline,
        )
        from modules.validator import (
            check_thresholds,
            evaluate_ensemble,
        )

        # Load dataset
        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_client.get_container_client("curated")
        blob_data = container.get_blob_client(msg.dataset_path).download_blob().readall()
        df = pd.read_parquet(io.BytesIO(blob_data))

        # Train
        lgbm_model, ridge_model, xgb_model, scaler, selected, training_info = run_training_pipeline(df)

        # Evaluate on holdout
        _, _, X_holdout, _, _, y_holdout = prepare_data(df)
        X_holdout_sel = X_holdout[selected]
        metrics = evaluate_ensemble(lgbm_model, ridge_model, xgb_model, scaler, X_holdout_sel, y_holdout)
        warnings = check_thresholds(metrics)

        # Register
        model_version = log_and_register_model(
            lgbm_model, ridge_model, xgb_model, scaler, selected,
            metrics, training_info, warnings,
        )

        # Publish completion
        elapsed = time.time() - start_time
        result_msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.LOAN_AMOUNT.value,
            status="SUCCESS",
            model_version=model_version,
            registry_name="credit-scoring-loan-amount",
            metrics=metrics,
            training_duration_seconds=elapsed,
            dataset_records_used=training_info["train_size"] + training_info["val_size"] + training_info["holdout_size"],
            features_selected=training_info["features_selected"],
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result_msg.to_json()))

        logger.info("Loan Amount training complete: %s (%.1fs)", training_id, elapsed)

    except Exception as exc:
        logger.exception("Loan Amount training failed: %s", training_id)
        _publish_failure(training_id, str(exc))


@app.function_name("loan_amount_predict")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="loan-amount-predict",
    subscription_name="loan-amount-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def loan_amount_predict(message: func.ServiceBusMessage) -> None:
    """Handle prediction requests from the Orchestrator."""
    raw = message.get_body().decode("utf-8")
    data = json.loads(raw)
    request_id = data["request_id"]
    features = data["features"]

    logger.info("Loan Amount prediction started: %s", request_id)

    try:
        from modules.registry import load_champion_models
        from modules.trainer import ensemble_predict

        # Load models
        lgbm_model, ridge_model, xgb_model, scaler, selected_features, model_version = load_champion_models()

        # Select features
        X = pd.DataFrame([features])[selected_features]

        # Predict
        prediction = ensemble_predict(lgbm_model, ridge_model, xgb_model, scaler, X)
        amount = float(prediction[0])

        # Publish result
        result = LoanAmountPredictionResult(
            request_id=request_id,
            recommended_loan_amount=round(amount, 2),
            model_version=model_version,
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.PREDICTION_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result.to_json()))

        logger.info("Loan Amount prediction complete: %s (GHS %.2f)", request_id, amount)

    except Exception:
        logger.exception("Loan Amount prediction failed: %s", request_id)


def _publish_failure(training_id: str, error: str) -> None:
    """Publish training failure."""
    try:
        msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.LOAN_AMOUNT.value,
            status="FAILED",
            error_message=error,
        )
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(msg.to_json()))
    except Exception:
        logger.exception("Failed to publish training failure for %s", training_id)
