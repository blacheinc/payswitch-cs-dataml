"""
Fraud Detection Agent — Azure Function App.

Isolation Forest unsupervised anomaly detection for credit profiles.
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
    FraudDetectionPredictionResult,
    ModelTrainingCompleteMessage,
    TrainModelMessage,
)

logger = logging.getLogger("payswitch-cs.fraud-detection")

app = func.FunctionApp()

SERVICE_BUS_CONNECTION = os.environ.get("SERVICE_BUS_CONNECTION", "")
STORAGE_CONNECTION = os.environ.get("STORAGE_CONNECTION", "")


@app.function_name("fraud_detection_train")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="fraud-detection-train",
    subscription_name="fraud-detection-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def fraud_detection_train(message: func.ServiceBusMessage) -> None:
    """Handle training requests from the Orchestrator."""
    start_time = time.time()
    raw = message.get_body().decode("utf-8")
    msg = TrainModelMessage.from_json(raw)
    training_id = msg.training_id

    logger.info("Fraud Detection training started: %s", training_id)

    try:
        from azure.storage.blob import BlobServiceClient

        from modules.registry import log_and_register_model
        from modules.trainer import run_training_pipeline
        from modules.validator import (
            sanity_check_known_bad,
            validate_distribution,
        )

        # Load dataset
        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_client.get_container_client("curated")
        blob_data = container.get_blob_client(msg.dataset_path).download_blob().readall()
        df = pd.read_parquet(io.BytesIO(blob_data))

        # Train
        model, thresholds, training_info = run_training_pipeline(df)

        # Validate
        dist_warnings = validate_distribution(training_info)
        sanity = sanity_check_known_bad(model, df, thresholds)

        # Register
        model_version = log_and_register_model(
            model, thresholds, training_info, dist_warnings, sanity,
        )

        # Publish completion
        elapsed = time.time() - start_time
        result_msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.FRAUD_DETECTION.value,
            status="SUCCESS",
            model_version=model_version,
            registry_name="credit-scoring-fraud-iforest",
            metrics={
                "contamination_rate": training_info["contamination"],
                "low_pct": training_info["low_pct"],
                "medium_pct": training_info["medium_pct"],
                "high_pct": training_info["high_pct"],
                "low_medium_threshold": thresholds["low_medium_boundary"],
                "medium_high_threshold": thresholds["medium_high_boundary"],
            },
            training_duration_seconds=elapsed,
            dataset_records_used=training_info["total_records"],
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result_msg.to_json()))

        logger.info("Fraud Detection training complete: %s (%.1fs)", training_id, elapsed)

    except Exception as exc:
        logger.exception("Fraud Detection training failed: %s", training_id)
        _publish_failure(training_id, str(exc))


@app.function_name("fraud_detection_predict")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="fraud-detect-predict",
    subscription_name="fraud-detection-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def fraud_detection_predict(message: func.ServiceBusMessage) -> None:
    """Handle prediction requests from the Orchestrator."""
    raw = message.get_body().decode("utf-8")
    data = json.loads(raw)
    request_id = data["request_id"]
    features = data["features"]

    logger.info("Fraud Detection prediction started: %s", request_id)

    try:
        from modules.registry import load_champion_model
        from modules.trainer import (
            classify_fraud_flag,
            normalize_anomaly_score,
        )

        # Load model + thresholds
        model, thresholds, model_version = load_champion_model()

        # Prepare features
        X = pd.DataFrame([features])[ALL_FEATURE_NAMES]

        # Score
        raw_score = float(model.score_samples(X)[0])
        normalized_score = normalize_anomaly_score(
            raw_score, thresholds["min_score"], thresholds["max_score"],
        )
        flag = classify_fraud_flag(raw_score, thresholds)

        # Publish result
        result = FraudDetectionPredictionResult(
            request_id=request_id,
            fraud_anomaly_score=round(normalized_score, 4),
            fraud_risk_flag=flag,
            model_version=model_version,
        )

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.PREDICTION_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(result.to_json()))

        logger.info(
            "Fraud Detection prediction complete: %s (score=%.4f, flag=%s)",
            request_id, normalized_score, flag,
        )

    except Exception:
        logger.exception("Fraud Detection prediction failed: %s", request_id)


def _publish_failure(training_id: str, error: str) -> None:
    """Publish training failure."""
    try:
        msg = ModelTrainingCompleteMessage(
            training_id=training_id,
            model_type=ModelType.FRAUD_DETECTION.value,
            status="FAILED",
            error_message=error,
        )
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(msg.to_json()))
    except Exception:
        logger.exception("Failed to publish training failure for %s", training_id)
