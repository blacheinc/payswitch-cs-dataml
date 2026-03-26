"""
Income Verification Agent — Azure Function App.

LightGBM multiclass classifier for income tier prediction.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time

import azure.functions as func
import numpy as np
import pandas as pd
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from shared.constants import INCOME_TIER_LABELS, ModelType, ServiceBusTopic
from shared.schemas.message_schemas import (
    IncomeVerificationPredictionResult,
    ModelTrainingCompleteMessage,
    TrainModelMessage,
)

logger = logging.getLogger("payswitch-cs.income-verification")

app = func.FunctionApp()

SERVICE_BUS_CONNECTION = os.environ.get("SERVICE_BUS_CONNECTION", "")
STORAGE_CONNECTION = os.environ.get("STORAGE_CONNECTION", "")


@app.function_name("income_verification_train")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="income-verification-train",
    subscription_name="income-verification-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def income_verification_train(message: func.ServiceBusMessage) -> None:
    """Handle training requests from the Orchestrator."""
    start_time = time.time()
    raw = message.get_body().decode("utf-8")
    msg = TrainModelMessage.from_json(raw)
    training_id = msg.training_id

    logger.info("Income Verification training started: %s", training_id)

    try:
        from azure.storage.blob import BlobServiceClient

        from modules.registry import log_and_register_model
        from modules.trainer import (
            prepare_data,
            run_training_pipeline,
        )
        from modules.validator import (
            check_thresholds,
            evaluate_model,
        )

        # Load dataset
        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_client.get_container_client("curated")
        blob_data = container.get_blob_client(msg.dataset_path).download_blob().readall()
        df = pd.read_parquet(io.BytesIO(blob_data))

        # Train
        model, selected, training_info = run_training_pipeline(df)

        # Evaluate on holdout
        _, _, X_holdout, _, _, y_holdout = prepare_data(df)
        X_holdout_sel = X_holdout[selected]
        metrics = evaluate_model(model, X_holdout_sel, y_holdout)
        warnings = check_thresholds(metrics)

        # Register
        model_version = log_and_register_model(
            model, selected, metrics, training_info, warnings,
        )

        # Publish completion
        elapsed = time.time() - start_time
        result_msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.INCOME_VERIFICATION.value,
            status="SUCCESS",
            model_version=model_version,
            registry_name="credit-scoring-income",
            metrics={
                "auc_ovr": metrics["auc_ovr"],
                "weighted_f1": metrics["weighted_f1"],
                "per_class_recall": metrics["per_class_recall"],
                "per_class_precision": metrics["per_class_precision"],
            },
            training_duration_seconds=elapsed,
            dataset_records_used=training_info["train_size"] + training_info["val_size"] + training_info["holdout_size"],
            features_selected=training_info["features_selected"],
            class_distribution=training_info.get("class_distribution", {}),
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result_msg.to_json()))

        logger.info("Income Verification training complete: %s (%.1fs)", training_id, elapsed)

    except Exception as exc:
        logger.exception("Income Verification training failed: %s", training_id)
        _publish_failure(training_id, str(exc))


@app.function_name("income_verification_predict")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="income-verify-predict",
    subscription_name="income-verification-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def income_verification_predict(message: func.ServiceBusMessage) -> None:
    """Handle prediction requests from the Orchestrator."""
    raw = message.get_body().decode("utf-8")
    data = json.loads(raw)
    request_id = data["request_id"]
    features = data["features"]

    logger.info("Income Verification prediction started: %s", request_id)

    try:
        from modules.registry import load_champion_model

        # Load model
        model, selected_features, model_version = load_champion_model()

        # Select features
        X = pd.DataFrame([features])[selected_features]

        # Predict
        proba = model.predict_proba(X)
        income_tier = int(np.argmax(proba[0]))
        income_confidence = float(np.max(proba[0]))
        income_tier_label = INCOME_TIER_LABELS.get(income_tier, "UNKNOWN")

        # Publish result
        result = IncomeVerificationPredictionResult(
            request_id=request_id,
            income_tier=income_tier,
            income_tier_label=income_tier_label,
            income_confidence=round(income_confidence, 4),
            model_version=model_version,
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.PREDICTION_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result.to_json()))

        logger.info(
            "Income Verification prediction complete: %s (tier=%d/%s, confidence=%.4f)",
            request_id, income_tier, income_tier_label, income_confidence,
        )

    except Exception:
        logger.exception("Income Verification prediction failed: %s", request_id)


def _publish_failure(training_id: str, error: str) -> None:
    """Publish training failure."""
    try:
        msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.INCOME_VERIFICATION.value,
            status="FAILED",
            error_message=error,
        )
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(msg.to_json()))
    except Exception:
        logger.exception("Failed to publish training failure for %s", training_id)
