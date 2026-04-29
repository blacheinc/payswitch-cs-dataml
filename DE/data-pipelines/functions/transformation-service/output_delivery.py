import io
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from azure.servicebus import ServiceBusMessage

from auth_clients import get_blob_service_client, get_service_bus_client

from feature_engineering import DeterministicFeatureBuilder

logger = logging.getLogger(__name__)

# Matches schema-mapping `ServiceBusWriter` backend publish contract for `transformed` subscription.
_SUBSCRIPTION_TRANSFORMED = "transformed"
_STATUS_TRANSFORMED = "TRANSFORMED"
_TRANSFORMATION_PROGRESS_TOPIC = "transformation-service"

_MISSING_FEATURE_FRIENDLY_MESSAGES: Dict[str, str] = {
    "highest_delinquency_rating": "Highest delinquency status is unavailable.",
    "months_on_time_24m": "On-time repayment history for the last 24 months is unavailable.",
    "worst_arrears_24m": "Worst arrears level in the last 24 months is unavailable.",
    "current_streak_on_time": "Current on-time payment streak is unavailable.",
    "has_active_arrears": "Current arrears status is unavailable.",
    "total_arrear_amount_ghs": "Total arrears amount is unavailable.",
    "total_outstanding_debt_ghs": "Total outstanding debt amount is unavailable.",
    "utilisation_ratio": "Credit utilization ratio is unavailable.",
    "num_active_accounts": "Number of active credit accounts is unavailable.",
    "total_monthly_instalment_ghs": "Total monthly installment amount is unavailable.",
    "credit_age_months": "Credit history length is unavailable.",
    "num_accounts_total": "Total number of credit accounts is unavailable.",
    "num_closed_accounts_good": "Number of well-closed credit accounts is unavailable.",
    "product_diversity_score": "Credit product diversity information is unavailable.",
    "mobile_loan_history_count": "Mobile loan history count is unavailable.",
    "mobile_max_loan_ghs": "Maximum historical mobile loan amount is unavailable.",
    "has_judgement": "Court judgment status is unavailable.",
    "has_written_off": "Written-off account status is unavailable.",
    "has_charged_off": "Charged-off account status is unavailable.",
    "has_legal_handover": "Legal handover status is unavailable.",
    "num_bounced_cheques": "Bounced cheque count is unavailable.",
    "has_adverse_default": "Adverse default status is unavailable.",
    "num_enquiries_3m": "Credit enquiries in the last 3 months are unavailable.",
    "num_enquiries_12m": "Credit enquiries in the last 12 months are unavailable.",
    "enquiry_reason_flags": "Credit enquiry reason indicators are unavailable.",
    "applicant_age": "Applicant age information is unavailable.",
    "identity_verified": "Identity verification status is unavailable.",
    "num_dependants": "Number of dependants is unavailable.",
    "has_employer_detail": "Employer detail information is unavailable.",
    "address_stability": "Address stability information is unavailable.",
}


def _friendly_missing_feature_message(name: Any) -> str:
    key = str(name).strip()
    if not key:
        return "Required credit data field is unavailable."
    return _MISSING_FEATURE_FRIENDLY_MESSAGES.get(
        key, f"Required credit data field is unavailable ({key})."
    )


def build_inference_request_message_body(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonical JSON for ML inference handoff. Published only to Service Bus topic
    ``INFERENCE_REQUEST_TOPIC`` (default: ``inference-request``): full ``features`` and
    ``metadata`` are embedded in the message (no auxiliary blob for inference).

    Shape: request_id, timestamp, features, metadata, models_to_run.
    """
    metadata = payload.get("metadata", {}) or {}
    decision = payload.get("decision_package", {}) or {}
    out_meta: Dict[str, Any] = {
        "credit_score": metadata.get("credit_score"),
        "score_grade": metadata.get("score_grade"),
        "decision_label": metadata.get("decision_label"),
        "data_quality_score": metadata.get("data_quality_score"),
        "bureau_hit_status": metadata.get("bureau_hit_status"),
        "product_source": metadata.get("product_source"),
        "imputation_policy_version": metadata.get("imputation_policy_version"),
        "required_non_imputable_missing_flag": metadata.get(
            "required_non_imputable_missing_flag"
        ),
        "required_non_imputable_missing_list": metadata.get(
            "required_non_imputable_missing_list", []
        ),
        "applicant_age_at_application": decision.get("applicant_age_at_application"),
        "credit_age_months_at_application": metadata.get("credit_age_months_at_application")
        if metadata.get("credit_age_months_at_application") is not None
        else decision.get("credit_age_months_at_application"),
    }
    return {
        "request_id": payload.get("request_id"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "features": payload.get("features") or {},
        "metadata": out_meta,
        "models_to_run": payload.get("models_to_run") or ["all"],
    }


def build_scoring_complete_hard_stop_body(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Inference fallback envelope published only when a hard stop is triggered."""
    decision = payload.get("decision_package", {}) or {}
    metadata = payload.get("metadata", {}) or {}
    diagnostics = payload.get("diagnostics", {}) or {}
    missing = diagnostics.get("missing_feature_list") or []
    technical_errors = [f"Feature validation failed: missing '{name}'" for name in missing]
    errors = [_friendly_missing_feature_message(name) for name in missing]
    condition = decision.get("condition_applied")
    if condition is None:
        condition_applied: List[str] = []
    elif isinstance(condition, list):
        condition_applied = condition
    else:
        condition_applied = [str(condition)]

    ts = payload.get("scoring_timestamp") or datetime.now(timezone.utc).isoformat()
    decision_label = metadata.get("decision_label") or decision.get("decision")
    return {
        "request_id": payload.get("request_id"),
        "scoring_timestamp": ts,
        "decision": decision.get("decision"),
        "errors": errors,
        "technical_errors": technical_errors,
        "condition_applied": condition_applied,
        "credit_risk": {
            "probability_of_default": None,
            "pd_confidence": None,
            "risk_tier": None,
            "shap_contributions": [],
            "decision_reason_codes": [],
            "model_version": None,
        },
        "fraud_detection": {
            "fraud_anomaly_score": None,
            "fraud_risk_flag": None,
            "model_version": None,
        },
        "loan_amount": {
            "recommended_amount_ghs": None,
            "recommended_loan_tier": None,
            "model_version": None,
        },
        "income_verification": {
            "income_tier": None,
            "income_tier_label": None,
            "income_confidence": None,
            "model_version": None,
        },
        "scoring_metadata": {
            "request_id": payload.get("request_id"),
            "scoring_timestamp": ts,
            "decision": decision.get("decision"),
            "errors": errors,
            "technical_errors": technical_errors,
            "credit_score": metadata.get("credit_score"),
            "score_grade": metadata.get("score_grade"),
            "decision_label": decision_label,
            "data_quality_score": metadata.get("data_quality_score"),
            "bureau_hit_status": metadata.get("bureau_hit_status"),
            "product_source": metadata.get("product_source"),
            "applicant_age_at_application": decision.get("applicant_age_at_application"),
            "credit_age_months_at_application": metadata.get("credit_age_months_at_application")
            if metadata.get("credit_age_months_at_application") is not None
            else decision.get("credit_age_months_at_application"),
        },
    }


def _publish_to_topic(
    topic_name: str,
    body: Dict[str, Any],
    application_properties: Dict[str, str],
    subject: str,
    *,
    session_id: Optional[str] = None,
    use_session: bool = True,
) -> None:
    try:
        client = get_service_bus_client(
            connection_string_env_vars=(
                "TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING",
                "SERVICE_BUS_CONNECTION_STRING",
            ),
            namespace_env_vars=(
                "TRANSFORM_OUTPUT_SERVICE_BUS_NAMESPACE",
                "SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE",
                "SERVICE_BUS_NAMESPACE",
            ),
        )
    except ValueError:
        return
    with client:
        with client.get_topic_sender(topic_name=topic_name) as sender:
            sid: Optional[str] = None
            if use_session:
                sid = session_id or str(
                    body.get("request_id")
                    or body.get("training_id")
                    or body.get("training_upload_id")
                    or application_properties.get("flow_type")
                    or "session"
                )
            msg_kwargs: Dict[str, Any] = {
                "subject": subject,
                "application_properties": application_properties,
            }
            if sid is not None:
                msg_kwargs["session_id"] = sid
            sender.send_messages(ServiceBusMessage(json.dumps(body), **msg_kwargs))


def _features_mapped_for_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic pipeline: count of known feature columns present (or full set size)."""
    names = DeterministicFeatureBuilder.FEATURE_NAMES
    features = payload.get("features")
    if isinstance(features, dict) and features:
        present = sum(1 for n in names if n in features)
        return {"count": present, "mappings": {}}
    return {"count": len(names), "mappings": {}}


def publish_transformed_training_complete(
    payload: Dict[str, Any], gold_features_blob_path: str
) -> None:
    """
    Publish final curated (gold) training artifact to data-ingested / transformed.

    Application properties align with schema-mapping-service `publish_transformed` so
    subscription SQL filters (status, run_id, transformed_file_path) match.
    """
    if payload.get("flow_type") != "training":
        return
    topic = os.getenv("TRANSFORM_OUTPUT_TOPIC", "data-ingested")
    if os.getenv("TRANSFORM_DISABLE_PUBLISH_TRANSFORMED", "").lower() in ("1", "true", "yes"):
        return
    if not topic:
        return
    training_upload_id = str(payload.get("training_upload_id") or "").strip()
    if not training_upload_id:
        return
    path = str(gold_features_blob_path or "").strip()
    if not path:
        return
    run_id = str(payload.get("run_id") or payload.get("request_id") or training_upload_id).strip()
    schema_template_id = os.getenv("SCHEMA_TEMPLATE_ID", "deterministic-xds-v1")
    features_mapped = _features_mapped_for_payload(payload)
    message_data: Dict[str, Any] = {
        "run_id": run_id,
        "training_upload_id": training_upload_id,
        "transformed_file_path": path,
        "features_mapped": features_mapped,
        "schema_template_id": schema_template_id,
        "status": _STATUS_TRANSFORMED,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    message_id = f"{training_upload_id}-transformed-{datetime.now(timezone.utc).timestamp()}"
    application_properties: Dict[str, Any] = {
        "subscription": _SUBSCRIPTION_TRANSFORMED,
        "status": _STATUS_TRANSFORMED,
        "run_id": run_id,
        "training_upload_id": training_upload_id,
        "transformed_file_path": path,
    }
    client = get_service_bus_client(
        connection_string_env_vars=(
            "TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING",
            "SERVICE_BUS_CONNECTION_STRING",
        ),
        namespace_env_vars=(
            "TRANSFORM_OUTPUT_SERVICE_BUS_NAMESPACE",
            "SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE",
            "SERVICE_BUS_NAMESPACE",
        ),
    )
    with client:
        with client.get_topic_sender(topic_name=topic) as sender:
            sender.send_messages(
                ServiceBusMessage(
                    body=json.dumps(message_data),
                    content_type="application/json",
                    message_id=message_id,
                    application_properties=application_properties,
                    session_id=training_upload_id,
                )
            )


def publish_backend_event(payload: Dict[str, Any]) -> None:
    topic = os.getenv("TRANSFORM_OUTPUT_TOPIC", "data-ingested")
    # Allow local runs to skip backend event publishing if desired
    if os.getenv("TRANSFORM_DISABLE_BACKEND_EVENT", "").lower() in ("1", "true", "yes"):
        return
    if not topic:
        return
    _publish_to_topic(
        topic_name=topic,
        body=payload,
        subject="transformation_pipeline_output",
        application_properties={
            "is_pipeline_output": "true",
            "event_type": "transformation_completed",
            "source_system": str(payload.get("source_system", "unknown")).lower(),
            "flow_type": str(payload.get("flow_type", "unknown")).lower(),
            "contract_version": str(payload.get("contract_version", "unknown")),
        },
    )


def publish_transformation_progress(
    *,
    payload: Dict[str, Any],
    status: str,
    subscription: str,
) -> None:
    topic = os.getenv("TRANSFORMATION_PROGRESS_TOPIC", _TRANSFORMATION_PROGRESS_TOPIC)
    if not topic:
        return

    request_id = str(payload.get("request_id") or "").strip()
    run_id = str(payload.get("run_id") or request_id or "").strip()
    training_upload_id = str(payload.get("training_upload_id") or "").strip()
    flow_type = str(payload.get("flow_type") or "").strip().lower()
    source_system = str(payload.get("source_system") or "unknown").strip().lower()
    event_body = {
        "request_id": request_id or None,
        "run_id": run_id or None,
        "training_upload_id": training_upload_id or None,
        "flow_type": flow_type or None,
        "source_system": source_system,
        "status": status,
        "subscription": subscription,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    app_props: Dict[str, str] = {
        "status": status,
        "subscription": subscription,
        "source_system": source_system,
    }
    if run_id:
        app_props["run_id"] = run_id
    if training_upload_id:
        app_props["training_upload_id"] = training_upload_id
    if request_id:
        app_props["request_id"] = request_id
    if flow_type:
        app_props["flow_type"] = flow_type

    _publish_to_topic(
        topic_name=topic,
        body=event_body,
        subject="transformation_progress",
        application_properties=app_props,
    )


def publish_ml_messages(payload: Dict[str, Any]) -> None:
    has_conn = bool((os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING") or "").strip())
    has_ns = bool(
        (os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_NAMESPACE") or "").strip()
    )
    if not (has_conn or has_ns):
        if str(payload.get("flow_type", "")).lower() == "inference":
            logger.error(
                "No Service Bus auth config found (connection string or namespace): "
                "inference-request was not published. Set auth config so ML receives "
                "features+metadata on topic %s.",
                os.getenv("INFERENCE_REQUEST_TOPIC", "inference-request"),
            )
        return
    flow_type = str(payload.get("flow_type", "")).lower()
    source_system = str(payload.get("source_system", "unknown")).lower()

    if flow_type == "training":
        topic = os.getenv("TRAINING_DATA_READY_TOPIC", "training-data-ready")
        training_upload_id = payload.get("training_upload_id")
        record_count = payload.get("record_count")
        if record_count is None:
            record_count = 1
        body = {
            "training_id": payload.get("training_id") or training_upload_id,
            "training_upload_id": training_upload_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data_location": {
                "container": os.getenv("GOLD_CONTAINER_NAME", "curated"),
                "blob_path": (payload.get("metadata", {}) or {}).get("gold_parquet_path", ""),
            },
            "record_count": record_count,
            "dataset_version": payload.get("dataset_version") or "v1",
            "product_distribution": payload.get("product_distribution") or {},
            "models_to_train": payload.get("models_to_train") or ["all"],
            "cleaned_dataset_path": payload.get("cleaned_dataset_path") or "",
        }
        _publish_to_topic(
            topic_name=topic,
            body=body,
            subject="training_data_ready",
            application_properties={
                "is_pipeline_output": "true",
                "message_type": "training_data_ready",
                "source_system": source_system,
                "flow_type": "training",
            },
        )
        return

    if flow_type == "inference":
        topic = os.getenv("INFERENCE_REQUEST_TOPIC", "inference-request")
        body = build_inference_request_message_body(payload)
        no_session = os.getenv("INFERENCE_REQUEST_DISABLE_SESSION_ID", "").lower() in (
            "1",
            "true",
            "yes",
        )
        _publish_to_topic(
            topic_name=topic,
            body=body,
            subject="inference_request",
            application_properties={
                "is_pipeline_output": "true",
                "message_type": "inference_request",
                "source_system": source_system,
                "flow_type": "inference",
            },
            use_session=not no_session,
        )
        logger.debug(
            "Published inference-request to topic=%s request_id=%s session=%s",
            topic,
            body.get("request_id"),
            "off" if no_session else "on",
        )
        return


def publish_scoring_complete_hard_stop(payload: Dict[str, Any]) -> None:
    """
    Inference-only hard-stop fallback for backend consumption.
    Publish null-model envelope to `SCORING_COMPLETE_TOPIC` (default `scoring-complete`).
    """
    if str(payload.get("flow_type", "")).lower() != "inference":
        return
    decision = payload.get("decision_package", {}) or {}
    if not bool(decision.get("hard_stop_triggered")):
        return
    has_conn = bool((os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING") or "").strip())
    has_ns = bool(
        (os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_NAMESPACE") or "").strip()
    )
    if not (has_conn or has_ns):
        logger.error(
            "No Service Bus auth config found (connection string or namespace): "
            "scoring-complete was not published for request_id=%s",
            payload.get("request_id"),
        )
        return
    topic = os.getenv("SCORING_COMPLETE_TOPIC", "scoring-complete")
    body = build_scoring_complete_hard_stop_body(payload)
    _publish_to_topic(
        topic_name=topic,
        body=body,
        subject="scoring_complete",
        application_properties={
            "is_pipeline_output": "true",
            "message_type": "scoring_complete",
            "source_system": str(payload.get("source_system", "unknown")).lower(),
            "flow_type": "inference",
            "hard_stop_triggered": "true",
        },
    )
    logger.debug(
        "Published scoring-complete hard-stop fallback to topic=%s request_id=%s",
        topic,
        body.get("request_id"),
    )


def write_training_parquet(payload: Dict[str, Any]) -> str | None:
    if payload.get("flow_type") != "training":
        return None
    container = os.getenv("GOLD_CONTAINER_NAME")
    base_path = os.getenv("GOLD_OUTPUT_PREFIX", "gold/training")
    if not container:
        return None

    features = payload.get("features", {})
    targets = payload.get("targets", {})
    metadata = payload.get("metadata", {})
    row = {**features, **targets, **metadata}
    df = pd.DataFrame([row])
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = payload.get("request_id", "unknown")
    source_system = str(payload.get("source_system", "unknown")).lower()
    data_source_id = str(payload.get("data_source_id", "unknown"))
    blob_name = f"{base_path}/source_system={source_system}/data_source_id={data_source_id}/{ts}_{request_id}.parquet"
    blob_service = get_blob_service_client(
        connection_string_env_vars=("GOLD_STORAGE_CONNECTION_STRING",),
        account_url_env_vars=("GOLD_STORAGE_ACCOUNT_URL", "AZURE_STORAGE_ACCOUNT_URL"),
    )
    blob_client = blob_service.get_blob_client(container=container, blob=blob_name)
    blob_client.upload_blob(buf.getvalue(), overwrite=True)
    return blob_name


def _to_scalar(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value)
    return value


def write_training_batch_parquets(
    payload: Dict[str, Any],
    feature_rows: List[Dict[str, Any]],
    metadata_rows: List[Dict[str, Any]],
) -> Tuple[str | None, str | None]:
    """
    Write training curated outputs as two parquet files:
    - features parquet: 30 features + targets + row_id
    - metadata parquet: metadata + row_id
    """
    if payload.get("flow_type") != "training":
        return None, None
    container = os.getenv("GOLD_CONTAINER_NAME")
    base_path = os.getenv("GOLD_OUTPUT_PREFIX", "gold/training")
    if not container:
        return None, None
    if not feature_rows:
        return None, None

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = str(payload.get("request_id") or payload.get("training_upload_id") or "unknown")
    source_system = str(payload.get("source_system", "unknown")).lower()
    data_source_id = str(payload.get("data_source_id", "unknown"))
    prefix = f"{base_path}/source_system={source_system}/data_source_id={data_source_id}"
    features_blob = f"{prefix}/{ts}_{request_id}_features.parquet"
    metadata_blob = f"{prefix}/{ts}_{request_id}_metadata.parquet"

    normalized_features = [{k: _to_scalar(v) for k, v in row.items()} for row in feature_rows]
    normalized_metadata = [{k: _to_scalar(v) for k, v in row.items()} for row in metadata_rows]

    features_df = pd.DataFrame(normalized_features)
    metadata_df = pd.DataFrame(normalized_metadata)

    features_buf = io.BytesIO()
    metadata_buf = io.BytesIO()
    features_df.to_parquet(features_buf, index=False)
    metadata_df.to_parquet(metadata_buf, index=False)
    features_buf.seek(0)
    metadata_buf.seek(0)

    blob_service = get_blob_service_client(
        connection_string_env_vars=("GOLD_STORAGE_CONNECTION_STRING",),
        account_url_env_vars=("GOLD_STORAGE_ACCOUNT_URL", "AZURE_STORAGE_ACCOUNT_URL"),
    )
    feature_client = blob_service.get_blob_client(container=container, blob=features_blob)
    metadata_client = blob_service.get_blob_client(container=container, blob=metadata_blob)
    feature_client.upload_blob(features_buf.getvalue(), overwrite=True)
    metadata_client.upload_blob(metadata_buf.getvalue(), overwrite=True)
    return features_blob, metadata_blob


def new_row_id() -> str:
    return str(uuid.uuid4())
