"""
Orchestrator-specific message handling.

Thin wrappers for building and parsing Service Bus messages
specific to the orchestrator's fan-out and collection patterns.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.schemas.message_schemas import (
    InferenceRequestMessage,
    ModelTrainingCompletedMessage,
    PredictMessage,
    TrainModelMessage,
    TrainingDataReadyMessage,
)


def build_train_messages(
    training_id: str,
    cleaned_dataset_path: str,
    imputation_params_path: str,
) -> TrainModelMessage:
    """Build a training message for fan-out to all 4 model agents."""
    return TrainModelMessage(
        training_id=training_id,
        dataset_path=cleaned_dataset_path,
        imputation_params_path=imputation_params_path,
    )


def build_predict_message(
    request_id: str,
    features: dict[str, float],
) -> PredictMessage:
    """Build a prediction message for fan-out to model agents."""
    return PredictMessage(
        request_id=request_id,
        features=features,
    )


def build_training_completed(
    training_id: str,
    training_upload_id: str,
    models_trained: dict[str, Any],
    training_duration_seconds: float,
    dataset_info: dict[str, Any],
    all_succeeded: bool,
) -> ModelTrainingCompletedMessage:
    """Build the model-training-completed message for Backend."""
    return ModelTrainingCompletedMessage(
        training_id=training_id,
        training_upload_id=training_upload_id,
        status="COMPLETE" if all_succeeded else "PARTIAL",
        models_trained=models_trained,
        training_duration_seconds=training_duration_seconds,
        dataset_info=dataset_info,
    )


def parse_training_data_ready(raw: str | bytes) -> TrainingDataReadyMessage:
    """Parse a training-data-ready message from Data Engineer."""
    return TrainingDataReadyMessage.from_json(raw)


def parse_inference_request(raw: str | bytes) -> InferenceRequestMessage:
    """Parse an inference-request message from Data Engineer."""
    return InferenceRequestMessage.from_json(raw)
