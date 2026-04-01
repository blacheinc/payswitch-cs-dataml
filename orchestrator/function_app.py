"""
PaySwitch Credit Scoring Orchestrator — Azure Function App.

Service Bus triggered functions for training and inference orchestration.
This is the central coordinator that owns:
- Data preprocessing (imputation, validation)
- Fan-out to 4 model agents via Service Bus
- Result collection from model agents
- Decision engine (final decision, risk tier, conditions)
- Final response assembly and publishing
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import azure.functions as func
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from modules.decision_engine import DecisionResult, run_decision_engine
from modules.message_schemas import (
    build_training_completed,
    build_predict_message,
    build_train_messages,
    parse_inference_request,
    parse_training_data_ready,
)
from modules.preprocessing import (
    imputation_params_from_json,
    imputation_params_to_json,
    impute_features,
    impute_training_dataset,
    validate_inference_features,
    validate_training_dataset,
)
from modules.risk_mapping import loan_amount_to_tier
from shared.constants import (
    DECISION_PRIORITY,
    Decision,
    FraudRiskFlag,
    ModelType,
    ServiceBusTopic,
)
from shared.schemas.message_schemas import (
    CreditRiskPredictionResult,
    FraudDetectionPredictionResult,
    IncomeVerificationPredictionResult,
    LoanAmountPredictionResult,
    parse_prediction_result,
)
from shared.schemas.response_schema import (
    CreditRiskResponse,
    FraudDetectionResponse,
    IncomeVerificationResponse,
    LoanAmountResponse,
    ScoringMetadata,
    ScoringResponse,
)
from shared.utils import utc_now_iso

logger = logging.getLogger("payswitch-cs.orchestrator")

app = func.FunctionApp()

# ── Configuration ───────────────────────────────────────────────────────────

SERVICE_BUS_CONNECTION = os.environ.get("SERVICE_BUS_CONNECTION", "")
STORAGE_CONNECTION = os.environ.get("STORAGE_CONNECTION", "")
IMPUTATION_PARAMS_CONTAINER = "model-artifacts"
IMPUTATION_PARAMS_BLOB = "imputation_params.json"


# ═══════════════════════════════════════════════════════════════════════════
#  TRAINING ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════


@app.function_name("training_orchestrator")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="training-data-ready",
    subscription_name="orchestrator-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def training_orchestrator(message: func.ServiceBusMessage) -> None:
    """
    Handle training-data-ready messages from the Data Engineer.

    Supports selective retraining via models_to_train field:
    - ["all"] (default) — train all 4 models
    - ["credit_risk"] — retrain only credit risk
    - ["credit_risk", "fraud_detection"] — retrain a subset

    If cleaned_dataset_path is provided, skips pull/validate/impute and
    fans out directly using the existing cleaned dataset.
    """
    start_time = time.time()
    raw = message.get_body().decode("utf-8")
    msg = parse_training_data_ready(raw)
    training_id = msg.training_id

    logger.info("Training orchestration started: %s", training_id)

    # Resolve which models to train
    requested = msg.models_to_train if hasattr(msg, "models_to_train") and msg.models_to_train else ["all"]
    valid_models = {m.value for m in ModelType}
    if "all" in requested:
        models = [m.value for m in ModelType]
    else:
        models = [m for m in requested if m in valid_models]
        if not models:
            logger.error("[%s] No valid models in models_to_train: %s", training_id, requested)
            _publish_training_error(training_id, [f"No valid models: {requested}"], msg.training_upload_id)
            return

    logger.info("[%s] Models to train: %s", training_id, models)

    # Map model type → Service Bus topic
    MODEL_TOPIC_MAP = {
        ModelType.CREDIT_RISK.value: ServiceBusTopic.CREDIT_RISK_TRAIN.value,
        ModelType.FRAUD_DETECTION.value: ServiceBusTopic.FRAUD_DETECTION_TRAIN.value,
        ModelType.LOAN_AMOUNT.value: ServiceBusTopic.LOAN_AMOUNT_TRAIN.value,
        ModelType.INCOME_VERIFICATION.value: ServiceBusTopic.INCOME_VERIFICATION_TRAIN.value,
    }

    try:
        import io

        import pandas as pd
        from azure.storage.blob import BlobServiceClient

        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        artifacts_container = blob_client.get_container_client(IMPUTATION_PARAMS_CONTAINER)
        try:
            artifacts_container.create_container()
        except Exception as e:
            if "ContainerAlreadyExists" not in str(e):
                raise

        # Check if we can skip preprocessing (reuse existing cleaned dataset)
        use_existing = bool(
            hasattr(msg, "cleaned_dataset_path") and msg.cleaned_dataset_path
        )

        if use_existing:
            cleaned_path = msg.cleaned_dataset_path
            logger.info("[%s] Reusing existing cleaned dataset: %s", training_id, cleaned_path)
            record_count = msg.record_count
        else:
            # Step 1: Pull dataset from blob storage
            data_container = msg.data_location.get("container", "curated")
            data_blob_path = msg.data_location.get("blob_path", "")
            logger.info("[%s] Pulling dataset from %s/%s", training_id, data_container, data_blob_path)
            container = blob_client.get_container_client(data_container)
            blob_data = container.get_blob_client(data_blob_path).download_blob().readall()

            df = pd.read_parquet(io.BytesIO(blob_data))
            logger.info("[%s] Dataset loaded: %d rows x %d columns", training_id, df.shape[0], df.shape[1])

            # Step 2: Validate dataset structure
            logger.info("[%s] Validating dataset structure...", training_id)
            errors = validate_training_dataset(df)
            if errors:
                logger.error("[%s] Validation FAILED: %s", training_id, errors)
                _publish_training_error(training_id, errors, msg.training_upload_id)
                return
            logger.info("[%s] Validation PASSED", training_id)

            # Step 3: Impute missing values
            null_count_before = df.iloc[:, :30].isnull().sum().sum()
            logger.info("[%s] Imputing missing values (%d nulls across features)...", training_id, null_count_before)
            df_imputed, imputation_params = impute_training_dataset(df)
            null_count_after = df_imputed.iloc[:, :30].isnull().sum().sum()
            logger.info(
                "[%s] Imputation complete: %d nulls -> %d nulls. Params: %s",
                training_id, null_count_before, null_count_after, imputation_params,
            )

            # Step 4: Save imputation params to blob
            # Only overwrite the shared params on full retraining ("all").
            # Selective retraining must not overwrite — another model may be
            # training concurrently with different data.
            is_full_retrain = "all" in requested
            params_json = imputation_params_to_json(imputation_params)

            # Always save a per-training-id copy
            artifacts_container.get_blob_client(
                f"training/{training_id}/imputation_params.json"
            ).upload_blob(params_json, overwrite=True)

            if is_full_retrain:
                artifacts_container.get_blob_client(IMPUTATION_PARAMS_BLOB).upload_blob(
                    params_json, overwrite=True,
                )
                logger.info("[%s] Saved imputation params to %s/%s (full retrain — shared copy updated)",
                            training_id, IMPUTATION_PARAMS_CONTAINER, IMPUTATION_PARAMS_BLOB)
            else:
                logger.info("[%s] Saved imputation params to training/%s/ only (selective retrain — shared copy NOT overwritten)",
                            training_id, training_id)

            # Step 5: Save cleaned dataset
            cleaned_path = data_blob_path.replace(".parquet", "_cleaned.parquet")
            buf = io.BytesIO()
            df_imputed.to_parquet(buf, index=False)
            buf.seek(0)
            container.get_blob_client(cleaned_path).upload_blob(buf.read(), overwrite=True)
            logger.info("[%s] Saved cleaned dataset to %s/%s", training_id, data_container, cleaned_path)
            record_count = len(df)

            # Save drift baselines (feature distributions for drift monitoring)
            if is_full_retrain:
                try:
                    from modules.drift_detector import compute_feature_distributions
                    distributions = compute_feature_distributions(df_imputed)
                    artifacts_container.get_blob_client(
                        "drift_baselines/feature_distributions.json"
                    ).upload_blob(json.dumps(distributions), overwrite=True)
                    logger.info("[%s] Saved drift baseline distributions (%d features)", training_id, len(distributions))
                except Exception:
                    logger.warning("[%s] Failed to save drift baselines", training_id)

        # Step 6: Notify Backend that training has started
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_STARTED.value)
            with sender:
                started_msg = json.dumps({
                    "training_id": training_id,
                    "training_upload_id": msg.training_upload_id,
                    "status": "STARTED",
                    "record_count": record_count,
                    "models_to_train": models,
                })
                sender.send_messages(ServiceBusMessage(started_msg))
        logger.info("[%s] Published model-training-started", training_id)

        # Step 7: Fan out to selected model training topics
        train_msg = build_train_messages(
            training_id=training_id,
            cleaned_dataset_path=cleaned_path,
            imputation_params_path=f"{IMPUTATION_PARAMS_CONTAINER}/{IMPUTATION_PARAMS_BLOB}",
        )

        training_topics = [MODEL_TOPIC_MAP[m] for m in models]

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            for topic in training_topics:
                sender = sb_client.get_topic_sender(topic)
                with sender:
                    sender.send_messages(ServiceBusMessage(train_msg.to_json()))
                    logger.info("[%s] Fan-out: published to %s", training_id, topic)

        # Step 8: Save training context for result collector
        training_ctx = json.dumps({
            "training_upload_id": msg.training_upload_id,
            "record_count": record_count,
            "dataset_version": msg.dataset_version,
            "models_to_train": models,
        })
        artifacts_container.get_blob_client(
            f"training/{training_id}/context.json"
        ).upload_blob(training_ctx, overwrite=True)

        elapsed = time.time() - start_time
        logger.info(
            "[%s] Training orchestration complete (%.1fs). Fan-out to %d model(s): %s",
            training_id, elapsed, len(models), models,
        )

    except Exception as exc:
        logger.exception("Training orchestration failed for %s", training_id)
        _publish_training_error(training_id, [f"Orchestrator error: {type(exc).__name__}: {exc}"])


@app.function_name("training_result_collector")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="model-training-complete",
    subscription_name="orchestrator-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def training_result_collector(message: func.ServiceBusMessage) -> None:
    """
    Collect training results from model agents.

    Uses blob storage as a simple coordination mechanism:
    writes each result, reads models_to_train from the training context
    to determine which models are expected, and publishes to
    model-training-completed when all expected models have reported.
    """
    raw = message.get_body().decode("utf-8")
    data = json.loads(raw)
    training_id = data.get("training_id", "unknown")
    model_type = data.get("model_type", "unknown")

    logger.info("Training result received: %s from %s", training_id, model_type)

    try:
        from azure.storage.blob import BlobServiceClient

        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_client.get_container_client(IMPUTATION_PARAMS_CONTAINER)

        # Save this model's result
        result_blob = f"training/{training_id}/{model_type}.json"
        container.get_blob_client(result_blob).upload_blob(raw, overwrite=True)

        # Load training context to find which models we're waiting for
        expected_models = [m.value for m in ModelType]  # default: all 4
        training_upload_id = ""
        try:
            ctx_blob = f"training/{training_id}/context.json"
            ctx_data = container.get_blob_client(ctx_blob).download_blob().readall()
            ctx = json.loads(ctx_data)
            expected_models = ctx.get("models_to_train", expected_models)
            training_upload_id = ctx.get("training_upload_id", "")
        except Exception:
            logger.warning("Could not load training context for %s — defaulting to all models", training_id)

        logger.info("[%s] Expecting %d model(s): %s", training_id, len(expected_models), expected_models)

        # Check if all expected models have reported
        results: dict[str, Any] = {}
        all_present = True

        for mt in expected_models:
            blob_path = f"training/{training_id}/{mt}.json"
            try:
                blob_data = container.get_blob_client(blob_path).download_blob().readall()
                results[mt] = json.loads(blob_data)
            except Exception:
                all_present = False
                break

        if all_present:
            all_succeeded = all(r.get("status") == "SUCCESS" for r in results.values())
            models_trained = {}
            for mt, result in results.items():
                models_trained[mt] = {
                    "version": result.get("model_version", ""),
                    "registry_name": result.get("registry_name", ""),
                    "metrics": result.get("metrics", {}),
                }

            complete_msg = build_training_completed(
                training_id=training_id,
                training_upload_id=training_upload_id,
                models_trained=models_trained,
                training_duration_seconds=sum(
                    r.get("training_duration_seconds", 0) for r in results.values()
                ),
                dataset_info={},
                all_succeeded=all_succeeded,
            )

            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
                sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETED.value)
                with sender:
                    sender.send_messages(ServiceBusMessage(complete_msg.to_json()))

            logger.info(
                "All training complete for %s (%d/%d models, status=%s)",
                training_id, len(results), len(expected_models), complete_msg.status,
            )
        else:
            logger.info(
                "[%s] Received %d/%d results — waiting for more",
                training_id, len(results), len(expected_models),
            )

    except Exception:
        logger.exception("Training result collection failed for %s", training_id)


# ═══════════════════════════════════════════════════════════════════════════
#  INFERENCE ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════


@app.function_name("inference_orchestrator")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="inference-request",
    subscription_name="orchestrator-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def inference_orchestrator(message: func.ServiceBusMessage) -> None:
    """
    Handle inference requests from the Data Engineer.

    Supports selective model execution via models_to_run field:
    - ["all"] (default) — Phase 1 (Credit Risk + Fraud Detection), then
      conditionally Phase 2 (Income Verification + Loan Amount)
    - ["credit_risk"] — only credit risk prediction
    - ["credit_risk", "fraud_detection"] — Phase 1 only
    - Any subset of: credit_risk, fraud_detection, loan_amount, income_verification

    Saves request context (features, metadata, models_to_run) to blob
    for the prediction_result_collector to use.
    """
    raw = message.get_body().decode("utf-8")
    msg = parse_inference_request(raw)
    request_id = msg.request_id

    # Resolve which models to run
    requested = msg.models_to_run if hasattr(msg, "models_to_run") and msg.models_to_run else ["all"]
    valid_models = {m.value for m in ModelType}
    selective_mode = "all" not in requested

    if selective_mode:
        models = [m for m in requested if m in valid_models]
        if not models:
            logger.error("[%s] No valid models in models_to_run: %s", request_id, requested)
            _publish_scoring_error(request_id, [f"No valid models: {requested}"], msg.metadata if hasattr(msg, "metadata") else {})
            return
    else:
        models = []  # Phase 1/Phase 2 logic handles this

    logger.info("Inference started: %s (models: %s)", request_id, models if selective_mode else "all (Phase 1+2)")

    try:
        from azure.storage.blob import BlobServiceClient

        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        artifacts = blob_client.get_container_client(IMPUTATION_PARAMS_CONTAINER)

        # Load imputation params
        params_raw = artifacts.get_blob_client(IMPUTATION_PARAMS_BLOB).download_blob().readall()
        imputation_params = imputation_params_from_json(params_raw)

        # Validate features
        validation_errors = validate_inference_features(msg.features)
        if validation_errors:
            logger.error("[%s] Feature validation failed: %s", request_id, validation_errors)
            _publish_scoring_error(request_id, validation_errors, msg.metadata)
            return

        # Impute
        features = impute_features(msg.features, imputation_params)

        # Save request context for prediction_result_collector
        context = {
            "features": features,
            "metadata": msg.metadata,
            "models_to_run": models if selective_mode else ["all"],
        }
        ctx_blob = f"inference/{request_id}/context.json"
        artifacts.get_blob_client(ctx_blob).upload_blob(json.dumps(context), overwrite=True)

        # Fan out
        INFERENCE_TOPIC_MAP = {
            ModelType.CREDIT_RISK.value: ServiceBusTopic.CREDIT_RISK_PREDICT.value,
            ModelType.FRAUD_DETECTION.value: ServiceBusTopic.FRAUD_DETECT_PREDICT.value,
            ModelType.LOAN_AMOUNT.value: ServiceBusTopic.LOAN_AMOUNT_PREDICT.value,
            ModelType.INCOME_VERIFICATION.value: ServiceBusTopic.INCOME_VERIFY_PREDICT.value,
        }

        predict_msg = build_predict_message(request_id, features)

        if selective_mode:
            # Selective: fan out only to requested models
            topics = [INFERENCE_TOPIC_MAP[m] for m in models]
        else:
            # Normal: Phase 1 only (Phase 2 triggered by result collector)
            topics = [
                ServiceBusTopic.CREDIT_RISK_PREDICT.value,
                ServiceBusTopic.FRAUD_DETECT_PREDICT.value,
            ]

        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            for topic in topics:
                sender = sb_client.get_topic_sender(topic)
                with sender:
                    sender.send_messages(ServiceBusMessage(predict_msg.to_json()))
                    logger.info("[%s] Inference fan-out: published to %s", request_id, topic)

        logger.info("[%s] Inference fan-out complete (%d models)", request_id, len(topics))

        # Accumulate features for drift monitoring (append to daily JSONL)
        try:
            from datetime import datetime, timezone
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            drift_blob = f"inference_features/{date_str}.jsonl"
            feature_line = json.dumps(features) + "\n"
            try:
                # Append to existing blob
                existing = artifacts.get_blob_client(drift_blob).download_blob().readall().decode()
                artifacts.get_blob_client(drift_blob).upload_blob(
                    existing + feature_line, overwrite=True,
                )
            except Exception:
                # First entry for today
                artifacts.get_blob_client(drift_blob).upload_blob(feature_line, overwrite=True)
        except Exception:
            pass  # Non-critical — don't fail inference for drift logging

    except Exception:
        logger.exception("Inference orchestration failed for %s", request_id)


@app.function_name("prediction_result_collector")
@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="prediction-complete",
    subscription_name="orchestrator-sub",
    connection="SERVICE_BUS_CONNECTION",
)
def prediction_result_collector(message: func.ServiceBusMessage) -> None:
    """
    Collect prediction results from model agents.

    Supports two modes based on models_to_run in the inference context:
    - ["all"]: Standard Phase 1 → decision point → Phase 2 flow
    - Selective (e.g., ["credit_risk"]): Wait for exactly those models,
      use defaults for missing models, then run decision engine

    Stores each result in blob. When all expected results are present,
    runs the decision engine and publishes the final scoring response.
    """
    raw = message.get_body().decode("utf-8")
    result = parse_prediction_result(raw)
    request_id = result.request_id
    model_type = json.loads(raw).get("model_type", "unknown")

    logger.info("Prediction result received: %s from %s", request_id, model_type)

    try:
        from azure.storage.blob import BlobServiceClient

        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_client.get_container_client(IMPUTATION_PARAMS_CONTAINER)

        # Save this result
        result_blob = f"inference/{request_id}/{model_type}.json"
        container.get_blob_client(result_blob).upload_blob(raw, overwrite=True)

        # Load request context (features + metadata + models_to_run)
        ctx_blob = f"inference/{request_id}/context.json"
        try:
            ctx_raw = container.get_blob_client(ctx_blob).download_blob().readall()
            context = json.loads(ctx_raw)
        except Exception:
            logger.warning("No context found for %s — may be first result", request_id)
            return

        models_to_run = context.get("models_to_run", ["all"])
        selective_mode = "all" not in models_to_run

        if selective_mode:
            # ── Selective mode: wait for exactly the requested models ──
            results_present = {}
            all_present = True
            for mt in models_to_run:
                r = _load_result(container, request_id, mt)
                if r is None:
                    all_present = False
                    break
                results_present[mt] = r

            if not all_present:
                logger.info("[%s] Selective: waiting for %d model(s), have %d so far",
                            request_id, len(models_to_run), len(results_present))
                return

            # All requested models present — run decision engine
            logger.info("[%s] Selective: all %d model(s) present, running decision engine",
                        request_id, len(models_to_run))

            credit_risk_result = results_present.get("credit_risk")
            fraud_result = results_present.get("fraud_detection")
            income_result = results_present.get("income_verification")
            loan_result = results_present.get("loan_amount")

            # Provide defaults for models that weren't requested
            if credit_risk_result is None:
                credit_risk_result = {"probability_of_default": 0.5, "pd_confidence": 0.0,
                                       "shap_contributions": [], "decision_reason_codes": [],
                                       "model_version": "N/A"}
            if fraud_result is None:
                fraud_result = {"fraud_anomaly_score": 0.0, "fraud_risk_flag": "LOW",
                                "model_version": "N/A"}

            _run_final_decision(
                request_id, context, credit_risk_result, fraud_result,
                income_result, loan_result, container,
            )
        else:
            # ── Standard Phase 1 / Phase 2 flow ──
            credit_risk_result = _load_result(container, request_id, "credit_risk")
            fraud_result = _load_result(container, request_id, "fraud_detection")

            if credit_risk_result is None or fraud_result is None:
                logger.info("[%s] Waiting for Phase 1 results", request_id)
                return

            # Phase 1 complete — decision point
            fraud_flag = fraud_result.get("fraud_risk_flag", "LOW")
            de_decision = context.get("metadata", {}).get("decision_label", "APPROVE")

            skip_phase_2 = (
                fraud_flag == FraudRiskFlag.HIGH.value
                or de_decision in (Decision.DECLINE.value, Decision.REFER.value)
            )

            if not skip_phase_2:
                income_result = _load_result(container, request_id, "income_verification")
                loan_result = _load_result(container, request_id, "loan_amount")

                if income_result is None or loan_result is None:
                    # Trigger Phase 2 (only if not already triggered)
                    phase2_marker = f"inference/{request_id}/phase2_triggered"
                    try:
                        container.get_blob_client(phase2_marker).download_blob()
                        logger.info("[%s] Phase 2 already triggered, waiting for results", request_id)
                        return
                    except Exception:
                        pass

                    features = context.get("features", {})
                    predict_msg = build_predict_message(request_id, features)

                    with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
                        for topic in [
                            ServiceBusTopic.INCOME_VERIFY_PREDICT.value,
                            ServiceBusTopic.LOAN_AMOUNT_PREDICT.value,
                        ]:
                            sender = sb_client.get_topic_sender(topic)
                            with sender:
                                sender.send_messages(ServiceBusMessage(predict_msg.to_json()))

                    container.get_blob_client(phase2_marker).upload_blob(b"1", overwrite=True)
                    logger.info("[%s] Phase 2 triggered", request_id)
                    return

                # All 4 results present
                _run_final_decision(
                    request_id, context, credit_risk_result, fraud_result,
                    income_result, loan_result, container,
                )
            else:
                # Skip Phase 2
                _run_final_decision(
                    request_id, context, credit_risk_result, fraud_result,
                    None, None, container,
                )

    except Exception:
        logger.exception("Prediction result collection failed for %s", request_id)


# ═══════════════════════════════════════════════════════════════════════════
#  DRIFT MONITORING
# ═══════════════════════════════════════════════════════════════════════════


@app.function_name("drift_monitor")
@app.timer_trigger(schedule="0 0 0 * * 1", arg_name="timer")  # Weekly on Monday midnight UTC
def drift_monitor(timer: func.TimerRequest) -> None:
    """
    Weekly drift detection (BLD Section 5.3, 10.1).

    Compares training feature distributions against recent inference features.
    If PSI > 0.20 on any Group A feature, publishes to drift-detected topic.
    """
    logger.info("Drift monitor started")

    try:
        from azure.storage.blob import BlobServiceClient
        from modules.drift_detector import (
            build_drift_message,
            check_feature_drift,
        )
        import pandas as pd
        from datetime import datetime, timedelta, timezone

        blob_client = BlobServiceClient.from_connection_string(STORAGE_CONNECTION)
        container = blob_client.get_container_client(IMPUTATION_PARAMS_CONTAINER)

        # Load training baseline distributions
        try:
            baseline_raw = container.get_blob_client(
                "drift_baselines/feature_distributions.json"
            ).download_blob().readall()
            baseline_distributions = json.loads(baseline_raw)
        except Exception:
            logger.warning("No drift baseline found — skipping drift check")
            return

        # Load baseline metrics
        baseline_metrics = {}
        try:
            metrics_raw = container.get_blob_client(
                "drift_baselines/baseline_metrics.json"
            ).download_blob().readall()
            baseline_metrics = json.loads(metrics_raw)
        except Exception:
            pass

        # Load recent inference features (last 7 days)
        now = datetime.now(timezone.utc)
        all_features = []
        for days_ago in range(7):
            date_str = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d")
            blob_name = f"inference_features/{date_str}.jsonl"
            try:
                data = container.get_blob_client(blob_name).download_blob().readall().decode()
                for line in data.strip().split("\n"):
                    if line:
                        all_features.append(json.loads(line))
            except Exception:
                continue

        if len(all_features) < 50:
            logger.info("Drift monitor: insufficient recent data (%d records, need 50+)", len(all_features))
            return

        recent_df = pd.DataFrame(all_features)
        logger.info("Drift monitor: comparing %d recent records against baseline", len(recent_df))

        # Compute drift
        drift_result = check_feature_drift(baseline_distributions, recent_df)

        if drift_result["recommendation"] == "retrain":
            logger.warning(
                "DRIFT DETECTED — %d features drifted, Group A drift: %s",
                len(drift_result["drifted_features"]),
                drift_result["has_group_a_drift"],
            )
            drift_msg = build_drift_message(drift_result, baseline_metrics)

            with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
                sender = sb_client.get_topic_sender("drift-detected")
                with sender:
                    sender.send_messages(ServiceBusMessage(json.dumps(drift_msg)))

            logger.info("Drift alert published to drift-detected topic")
        else:
            logger.info(
                "No significant drift — %d minor, %d significant",
                len(drift_result["minor_drift_features"]),
                len(drift_result["drifted_features"]),
            )

    except Exception:
        logger.exception("Drift monitor failed")


# ── Internal Helpers ────────────────────────────────────────────────────────

def _load_result(container, request_id: str, model_type: str) -> Optional[dict]:
    """Try to load a prediction result from blob storage."""
    try:
        blob_path = f"inference/{request_id}/{model_type}.json"
        data = container.get_blob_client(blob_path).download_blob().readall()
        return json.loads(data)
    except Exception:
        return None


def _run_final_decision(
    request_id: str,
    context: dict,
    credit_risk_result: dict,
    fraud_result: dict,
    income_result: Optional[dict],
    loan_result: Optional[dict],
    container,
) -> None:
    """Run decision engine and publish final scoring response."""
    metadata = context.get("metadata", {})
    features = context.get("features", {})

    pd_value = credit_risk_result.get("probability_of_default", 0.5)
    fraud_flag = fraud_result.get("fraud_risk_flag", "LOW")
    score_grade = metadata.get("score_grade", "C")
    de_decision = metadata.get("decision_label", "APPROVE")

    recommended_amount = None
    if loan_result is not None:
        recommended_amount = loan_result.get("recommended_loan_amount")

    decision_result = run_decision_engine(
        probability_of_default=pd_value,
        score_grade=score_grade,
        data_engineer_decision_label=de_decision,
        fraud_risk_flag=fraud_flag,
        features=features,
        recommended_loan_amount_ghs=recommended_amount,
        metadata=metadata,
    )

    # Build response
    credit_risk_response = CreditRiskResponse(
        probability_of_default=pd_value,
        pd_confidence=credit_risk_result.get("pd_confidence", 0.0),
        risk_tier=decision_result.risk_tier.value,
        shap_contributions=credit_risk_result.get("shap_contributions", []),
        decision_reason_codes=credit_risk_result.get("decision_reason_codes", []),
        model_version=credit_risk_result.get("model_version", ""),
    )

    fraud_response = FraudDetectionResponse(
        fraud_anomaly_score=fraud_result.get("fraud_anomaly_score", 0.0),
        fraud_risk_flag=fraud_flag,
        model_version=fraud_result.get("model_version", ""),
    )

    loan_response = None
    if loan_result is not None and recommended_amount is not None:
        loan_response = LoanAmountResponse(
            recommended_amount_ghs=recommended_amount,
            recommended_loan_tier=(
                decision_result.recommended_loan_tier.value
                if decision_result.recommended_loan_tier else ""
            ),
            model_version=loan_result.get("model_version", ""),
        )

    income_response = None
    if income_result is not None:
        income_response = IncomeVerificationResponse(
            income_tier=income_result.get("income_tier", 0),
            income_tier_label=income_result.get("income_tier_label", ""),
            income_confidence=income_result.get("income_confidence", 0.0),
            model_version=income_result.get("model_version", ""),
        )

    scoring_response = ScoringResponse(
        request_id=request_id,
        scoring_timestamp=utc_now_iso(),
        decision=decision_result.decision.value,
        condition_applied=decision_result.conditions,
        credit_risk=credit_risk_response,
        fraud_detection=fraud_response,
        loan_amount=loan_response,
        income_verification=income_response,
        scoring_metadata=ScoringMetadata(
            credit_score=metadata.get("credit_score", 0),
            score_grade=metadata.get("score_grade", ""),
            data_quality_score=metadata.get("data_quality_score", 0.0),
            bureau_hit_status=metadata.get("bureau_hit_status", ""),
            product_source=metadata.get("product_source", ""),
            applicant_age_at_application=metadata.get("applicant_age_at_application", 0),
            credit_age_months_at_application=metadata.get("credit_age_months_at_application", 0),
        ),
        refer_reasons=decision_result.refer_reasons,
    )

    # Publish to scoring-complete
    with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
        sender = sb_client.get_topic_sender(ServiceBusTopic.SCORING_COMPLETE.value)
        with sender:
            sender.send_messages(ServiceBusMessage(scoring_response.to_json()))

    logger.info(
        "Scoring complete for %s: decision=%s, risk_tier=%s",
        request_id, decision_result.decision.value, decision_result.risk_tier.value,
    )


def _publish_training_error(training_id: str, errors: list[str], training_upload_id: str = "") -> None:
    """Publish a training error to model-training-completed."""
    msg = build_training_completed(
        training_id=training_id,
        training_upload_id=training_upload_id,
        models_trained={},
        training_duration_seconds=0,
        dataset_info={"errors": errors},
        all_succeeded=False,
    )
    try:
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.MODEL_TRAINING_COMPLETED.value)
            with sender:
                sender.send_messages(ServiceBusMessage(msg.to_json()))
    except Exception:
        logger.exception("Failed to publish training error for %s", training_id)


def _publish_scoring_error(
    request_id: str,
    errors: list[str],
    metadata: dict,
) -> None:
    """Publish an error response to scoring-complete."""
    error_response = {
        "request_id": request_id,
        "scoring_timestamp": utc_now_iso(),
        "decision": "ERROR",
        "errors": errors,
        "scoring_metadata": metadata,
    }
    try:
        with ServiceBusClient.from_connection_string(SERVICE_BUS_CONNECTION) as sb_client:
            sender = sb_client.get_topic_sender(ServiceBusTopic.SCORING_COMPLETE.value)
            with sender:
                sender.send_messages(ServiceBusMessage(json.dumps(error_response)))
    except Exception:
        logger.exception("Failed to publish scoring error for %s", request_id)
