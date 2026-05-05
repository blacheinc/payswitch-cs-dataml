"""
Transformation service — Azure Functions host for XDS training and inference.

Exposes HTTP routes under ``/api/transform/...`` and a Service Bus topic trigger for
``schema-mapping-service`` / ``mapping-complete`` (silver handoff). Core logic lives in
``orchestrator``, ``output_delivery``, and related modules; this file wires routes, batch
JSONL, and Service Bus progress events.
"""

import json
import logging
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List

import azure.functions as func
import pandas as pd
import requests
from azure.servicebus import ServiceBusMessage

from auth_clients import get_blob_service_client, get_service_bus_client
from contracts import TransformRequest
from feature_engineering import DeterministicFeatureBuilder
from orchestrator import TransformationOrchestrator
from output_delivery import (
    publish_backend_event,
    publish_ml_messages,
    publish_scoring_complete_hard_stop,
    publish_transformation_progress,
    publish_transformed_training_complete,
    write_training_parquet,
    write_training_batch_parquets,
    new_row_id,
)
from quality_provider import System04QualityAdapter
from rule_engine import DeterministicRuleEngine, HardStopEvaluator
from silver_loader import load_silver_json, load_silver_parquet
from inference_anonymize import anonymize_inference_dataframe
from imputation_contract import refresh_live_contract_from_training
from xds_payload_normalize import normalize_nested_xds_payload
from xds_parsers import Product45Parser, Product49Parser, XdsParser

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

app = func.FunctionApp()
_DE_ML_BATCH_SCHEMA_VERSION = "de-ml-batch-pointer-v1"

# When flat `consumer_full_report_45.response.statusCode` is 200, these agreement fields are required.
# Product 49-only rows need only `consumer_mobile_report_49.response.statusCode` == 200 (see _validate_flat_row_schema_v1).
FLATTENED_XDS_SCHEMA_V1_REQUIRED_COLUMNS = (
    "consumer_full_report_45.response.statusCode",
    "consumer_full_report_45.creditAgreementSummary.accountStatusCode",
    "consumer_full_report_45.creditAgreementSummary.monthsInArrears",
    "consumer_full_report_45.creditAgreementSummary.openingBalanceAmt",
)


def _build_orchestrator() -> TransformationOrchestrator:
    """Construct the default parser + feature + rules pipeline for a single request."""
    return TransformationOrchestrator(
        parser=XdsParser(Product45Parser(), Product49Parser()),
        feature_builder=DeterministicFeatureBuilder(),
        hard_stop_evaluator=HardStopEvaluator(),
        rule_engine=DeterministicRuleEngine(),
        quality_provider=System04QualityAdapter(),
        transform_version="v1",
        rule_version="v1",
    )


def _emit_transformation_progress(payload: Dict[str, Any], status: str, subscription: str) -> None:
    """Publish a non-fatal progress notification to Service Bus when configured."""
    try:
        publish_transformation_progress(payload=payload, status=status, subscription=subscription)
    except Exception as exc:
        logger.warning(
            "Progress publish failed status=%s subscription=%s error=%s",
            status,
            subscription,
            exc,
        )


def _transform_payload(data: Dict[str, Any], publish_outputs: bool = True) -> Dict[str, Any]:
    """
    Run single-row training or inference transform, optionally write gold parquet and publish
    handoff messages (backend + ML topics).
    """
    request = TransformRequest.from_dict(data)
    orchestrator = _build_orchestrator()
    result = orchestrator.run(request)
    payload = result.to_dict()
    payload["flow_type"] = request.flow_type
    payload["source_system"] = request.source_system
    payload["data_source_id"] = request.data_source_id
    payload["training_upload_id"] = request.training_upload_id
    payload["training_id"] = data.get("training_id")
    payload["dataset_version"] = data.get("dataset_version")
    payload["record_count"] = data.get("record_count")
    payload["product_distribution"] = data.get("product_distribution", {})
    payload["models_to_train"] = data.get("models_to_train")
    payload["models_to_run"] = data.get("models_to_run")
    payload["cleaned_dataset_path"] = data.get("cleaned_dataset_path", "")
    gold_blob = write_training_parquet(payload)
    if gold_blob:
        payload.setdefault("metadata", {})["gold_parquet_path"] = gold_blob
    if publish_outputs:
        # Publish enriched payload to backend completion topic when configured.
        publish_backend_event(payload)
        # Publish ML-facing contracts to expected topics.
        publish_ml_messages(payload)
        if gold_blob:
            publish_transformed_training_complete(payload, gold_blob)
    return payload


def _parse_json_object_maybe(value: Any, field_name: str) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"Expected JSON object for {field_name}")


def _flat_row_status_code(row: Dict[str, Any], key: str) -> int | None:
    v = row.get(key)
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _validate_flat_row_schema_v1(row: Dict[str, Any], row_idx: int) -> None:
    s45 = _flat_row_status_code(row, "consumer_full_report_45.response.statusCode")
    s49 = _flat_row_status_code(row, "consumer_mobile_report_49.response.statusCode")
    has_45 = s45 == 200
    has_49 = s49 == 200
    if has_45:
        missing = [
            c
            for c in FLATTENED_XDS_SCHEMA_V1_REQUIRED_COLUMNS
            if row.get(c) is None or str(row.get(c)).strip() == ""
        ]
        if missing:
            raise ValueError(
                f"Row {row_idx}: flattened_xds_schema_v1 missing required Product 45 columns: "
                f"{', '.join(missing)}"
            )
        return
    if has_49:
        return
    raise ValueError(
        f"Row {row_idx}: flattened_xds_schema_v1 requires Product 45 (status 200 + agreement fields) "
        f"or Product 49 (status 200); neither satisfied."
    )


def _flat_field_missing_for_contract(row: Dict[str, Any], key: str) -> bool:
    """Same emptiness rule as _validate_flat_row_schema_v1 for a single column."""
    v = row.get(key)
    if v is None:
        return True
    if isinstance(v, str) and not str(v).strip():
        return True
    try:
        if pd.isna(v):
            return True
    except TypeError:
        pass
    return False


def _restore_required_flat_45_fields_after_anonymize(
    original: Dict[str, Any], anonymized: Dict[str, Any]
) -> Dict[str, Any]:
    """
    DatasetAnonymizer may drop or blank dotted-path columns (e.g. creditAgreementSummary.*).
    Training silver keeps those fields for ML; restore them from the pre-anonymize row when
    Product 45 was a 200 hit so inference matches the same flattened_xds_schema_v1 contract.
    """
    if _flat_row_status_code(original, "consumer_full_report_45.response.statusCode") != 200:
        return anonymized
    out = dict(anonymized)
    for c in FLATTENED_XDS_SCHEMA_V1_REQUIRED_COLUMNS:
        if _flat_field_missing_for_contract(out, c) and not _flat_field_missing_for_contract(
            original, c
        ):
            out[c] = original[c]
    return out


def _parse_possible_date(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    token = raw.split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(token, fmt)
        except ValueError:
            continue
    return None


def _latest_from_array(values: list[Any]) -> Any:
    dicts = [v for v in values if isinstance(v, dict)]
    if not dicts:
        return values[-1] if values else None
    date_keys = (
        "dateRequested",
        "dateAccountOpened",
        "dateOpened",
        "date_opened",
        "closedDate",
        "closed_date",
        "updatedAt",
        "createdAt",
    )
    scored = []
    for idx, item in enumerate(dicts):
        dt = None
        for key in date_keys:
            dt = _parse_possible_date(item.get(key))
            if dt:
                break
        scored.append((dt, idx, item))
    dated = [x for x in scored if x[0] is not None]
    if dated:
        dated.sort(key=lambda x: x[0], reverse=True)
        return dated[0][2]
    return scored[-1][2]


def _flatten_xds_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                nxt = f"{prefix}.{k}" if prefix else str(k)
                walk(nxt, v)
            return
        if isinstance(value, list):
            latest = _latest_from_array(value)
            if isinstance(latest, dict):
                for k, v in latest.items():
                    nxt = f"{prefix}.{k}" if prefix else str(k)
                    walk(nxt, v)
            else:
                out[prefix] = latest
            return
        out[prefix] = value

    walk("", payload)
    return out


def _post_inference_multipart(
    parquet_bytes: bytes, request_id: str, source_system: str, endpoint_url: str
) -> None:
    files = {"file": (f"{request_id}.parquet", parquet_bytes, "application/octet-stream")}
    data = {"request_id": request_id, "source_system": source_system}
    response = requests.post(endpoint_url, files=files, data=data, timeout=30)
    response.raise_for_status()


def _ml_engineer_http_endpoint_for_post() -> str | None:
    """Return ML engineer multipart POST URL when configured (non-empty)."""
    raw = (os.getenv("ML_ENGINEER_HTTP_ENDPOINT") or "").strip()
    return raw or None


def _is_azure_runtime() -> bool:
    # Present on deployed Function Apps; absent in most local `func start` runs.
    return bool((os.getenv("WEBSITE_INSTANCE_ID") or "").strip())


def _ensure_inference_publish_config() -> None:
    """
    Guardrail: in Azure runtime, inference must have Service Bus publish config.
    This prevents false-positive HTTP 200 responses where inference-request is never published.
    """
    if not _is_azure_runtime():
        return
    conn = (os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING") or "").strip()
    ns = (
        (os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_NAMESPACE") or "").strip()
    )
    topic = (os.getenv("INFERENCE_REQUEST_TOPIC") or "inference-request").strip()
    if not conn and not ns:
        raise ValueError(
            "Missing Service Bus auth config in Azure runtime; "
            "cannot publish inference-request."
        )
    if not topic:
        raise ValueError("Missing INFERENCE_REQUEST_TOPIC in Azure runtime.")


def _transform_training_batch_from_silver(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Training batch path after schema-mapping: read flattened silver parquet + sidecar JSON,
    transform each row, write curated feature/metadata parquet pair, publish ML/backend events.
    """
    silver_path = str(data.get("anonymized_silver_path") or "")
    sidecar_path = str(data.get("analysis_context_path") or "")
    if not silver_path or not sidecar_path:
        raise ValueError("Missing anonymized_silver_path or analysis_context_path")

    # Contract completeness: sidecar must exist and contain core fields.
    sidecar = load_silver_json(sidecar_path)
    for key in ("run_id", "training_upload_id", "anonymized_silver_path"):
        if not sidecar.get(key):
            raise ValueError(f"Invalid systems04_context.json: missing {key}")

    df = load_silver_parquet(silver_path)
    rows = df.to_dict(orient="records")
    if not rows:
        raise ValueError("Silver parquet is empty")

    orchestrator = _build_orchestrator()
    feature_rows: list[dict] = []
    metadata_rows: list[dict] = []

    def _legacy_xds_payload_present(r: Dict[str, Any]) -> bool:
        if "xds_payload" not in r:
            return False
        v = r.get("xds_payload")
        if v is None:
            return False
        try:
            if isinstance(v, float) and pd.isna(v):
                return False
        except TypeError:
            pass
        return True

    for idx, row in enumerate(rows):
        if _legacy_xds_payload_present(row):
            raise ValueError(
                f"Row {idx}: silver training parquet must contain only flat anonymized columns "
                "(no non-null xds_payload column). Use flattened_xds_schema_v1 rows as written by Systems 0-4."
            )
        _validate_flat_row_schema_v1(row, idx)
        request_payload = {
            "flow_type": "training",
            "request_id": f"{data.get('request_id') or data.get('training_upload_id')}-{idx}",
            "data_source_id": data.get("data_source_id") or data.get("bank_id"),
            "source_system": data.get("source_system", "xds"),
            "xds_payload": {"__flat_row__": row},
            "run_id": data.get("run_id"),
            "training_upload_id": data.get("training_upload_id"),
        }
        request = TransformRequest.from_dict(request_payload)
        result = orchestrator.run(request).to_dict()

        row_id = new_row_id()
        feature_rows.append(
            {
                **(result.get("features") or {}),
                **(result.get("targets") or {}),
                "row_id": row_id,
            }
        )
        metadata_rows.append(
            {
                "row_id": row_id,
                "request_id": result.get("request_id"),
                "bureau_hit_status": result.get("bureau_hit_status"),
                **(result.get("metadata") or {}),
                **(result.get("decision_package") or {}),
                **(result.get("diagnostics") or {}),
            }
        )

    # Keep a living DE imputation contract in data lake and refresh medians
    # only when drift exceeds threshold from previous live contract.
    try:
        refresh_info = refresh_live_contract_from_training(
            feature_rows=feature_rows,
            training_upload_id=str(data.get("training_upload_id") or ""),
            run_id=str(data.get("run_id") or ""),
        )
        logger.warning(
            "DE imputation live contract refreshed: path=%s updated=%s version=%s",
            refresh_info.get("path"),
            refresh_info.get("updated"),
            refresh_info.get("policy_version"),
        )
    except Exception as exc:
        # Best-effort only: contract refresh should not block training transformation.
        logger.warning("DE imputation live contract refresh skipped: %s", exc)

    features_blob, metadata_blob = write_training_batch_parquets(
        payload={**data, "flow_type": "training"},
        feature_rows=feature_rows,
        metadata_rows=metadata_rows,
    )
    if not features_blob:
        raise ValueError("Failed to write curated batch parquet outputs")

    payload: Dict[str, Any] = {
        "flow_type": "training",
        "request_id": data.get("request_id"),
        "run_id": data.get("run_id"),
        "source_system": data.get("source_system", "xds"),
        "data_source_id": data.get("data_source_id") or data.get("bank_id"),
        "training_upload_id": data.get("training_upload_id"),
        "dataset_version": data.get("dataset_version"),
        "record_count": len(feature_rows),
        "product_distribution": data.get("product_distribution", {}),
        "models_to_train": data.get("models_to_train"),
        "cleaned_dataset_path": data.get("cleaned_dataset_path", ""),
        "metadata": {
            "gold_parquet_path": features_blob,
            "gold_metadata_parquet_path": metadata_blob or "",
        },
    }
    publish_backend_event(payload)
    publish_ml_messages(payload)
    publish_transformed_training_complete(payload, features_blob)
    return payload


def _inference_batch_max_lines() -> int:
    raw = (os.getenv("INFERENCE_BATCH_MAX_LINES") or "100").strip()
    try:
        n = int(raw)
        return max(1, min(n, 10_000))
    except ValueError:
        return 100


def _batch_score_inline_threshold() -> int:
    raw = (os.getenv("BATCH_SCORE_INLINE_THRESHOLD") or "50").strip()
    try:
        n = int(raw)
        return max(1, min(n, 10_000))
    except ValueError:
        return 50


def _parse_reprocess_query_default_true(raw: str | None) -> bool:
    if raw is None:
        return True
    s = str(raw).strip().lower()
    if s in ("", "1", "true", "yes", "y"):
        return True
    if s in ("0", "false", "no", "n"):
        return False
    return True


def _has_batch_score_service_bus_auth() -> bool:
    return bool(
        (os.getenv("BATCH_SCORE_REQUEST_SERVICE_BUS_CONNECTION_STRING") or "").strip()
        or (os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING") or "").strip()
        or (os.getenv("BATCH_SCORE_SERVICE_BUS_NAMESPACE") or "").strip()
        or (os.getenv("TRANSFORM_OUTPUT_SERVICE_BUS_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE") or "").strip()
        or (os.getenv("SERVICE_BUS_NAMESPACE") or "").strip()
    )


def _has_batch_score_storage_auth() -> bool:
    return bool(
        (os.getenv("BATCH_SCORE_STORAGE_CONNECTION_STRING") or "").strip()
        or (os.getenv("GOLD_STORAGE_CONNECTION_STRING") or "").strip()
        or (os.getenv("BATCH_SCORE_STORAGE_ACCOUNT_URL") or "").strip()
        or (os.getenv("GOLD_STORAGE_ACCOUNT_URL") or "").strip()
        or (os.getenv("AZURE_STORAGE_ACCOUNT_URL") or "").strip()
        or (os.getenv("BATCH_SCORE_STORAGE_ACCOUNT") or "").strip()
        or (os.getenv("AZURE_STORAGE_ACCOUNT") or "").strip()
    )


def _batch_score_topic_name() -> str:
    return (os.getenv("BATCH_SCORE_REQUEST_TOPIC") or "batch-score-request").strip()


def _batch_score_container_name() -> str:
    return (os.getenv("BATCH_SCORE_CONTAINER") or "curated").strip()


def _batch_score_blob_prefix() -> str:
    return (os.getenv("BATCH_SCORE_INPUT_PREFIX") or "ml-batch").strip().strip("/")


def _parse_jsonl_lines(body_bytes: bytes) -> list[tuple[int, dict]]:
    if not body_bytes:
        raise ValueError("Request body is empty")
    try:
        text = body_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Body must be UTF-8: {exc}") from exc
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not raw_lines:
        raise ValueError("Request body has no JSONL lines")
    parsed: list[tuple[int, dict]] = []
    for line_no, line in enumerate(raw_lines, start=1):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {line_no}: invalid JSON ({exc})") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"Line {line_no}: JSON line must be an object")
        parsed.append((line_no, obj))
    return parsed


def _normalize_batch_score_applicants(parsed: list[tuple[int, dict]]) -> list[dict]:
    expected = set(DeterministicFeatureBuilder.FEATURE_NAMES)
    required_metadata = ("data_source_id", "source_system")
    normalized: list[dict] = []
    seen_request_ids: set[str] = set()
    for line_no, obj in parsed:
        request_id = str(obj.get("request_id") or "").strip()
        if not request_id:
            raise ValueError(f"Line {line_no}: request_id is required")
        if request_id in seen_request_ids:
            raise ValueError(f"Line {line_no}: duplicate request_id '{request_id}' in same job")
        seen_request_ids.add(request_id)

        features = obj.get("features")
        if not isinstance(features, dict):
            raise ValueError(f"Line {line_no}: features must be an object")
        got = set(features.keys())
        if got != expected:
            missing = sorted(expected - got)
            extra = sorted(got - expected)
            parts = []
            if missing:
                parts.append(f"missing keys: {', '.join(missing)}")
            if extra:
                parts.append(f"extra keys: {', '.join(extra)}")
            raise ValueError(f"Line {line_no}: features keys mismatch ({'; '.join(parts)})")
        for key in expected:
            if features.get(key) is None:
                raise ValueError(f"Line {line_no}: features.{key} cannot be null")

        metadata = obj.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"Line {line_no}: metadata must be an object")
        for key in required_metadata:
            val = metadata.get(key)
            if val is None or not str(val).strip():
                raise ValueError(f"Line {line_no}: metadata.{key} is required")

        normalized.append(
            {
                "request_id": request_id,
                "features": features,
                "metadata": metadata,
            }
        )
    return normalized


def _blob_path_for_batch_job(job_id: str) -> str:
    return f"{_batch_score_blob_prefix()}/{job_id}/applicants.jsonl"


def _write_batch_applicants_jsonl(
    *,
    job_id: str,
    applicants: list[dict],
    reprocess: bool,
) -> tuple[str, str]:
    if not _has_batch_score_storage_auth():
        raise ValueError(
            "Missing batch-score storage auth config (connection string or account URL/name)."
        )
    container = _batch_score_container_name()
    blob_path = _blob_path_for_batch_job(job_id)
    blob_service = get_blob_service_client(
        connection_string_env_vars=(
            "BATCH_SCORE_STORAGE_CONNECTION_STRING",
            "GOLD_STORAGE_CONNECTION_STRING",
        ),
        account_url_env_vars=(
            "BATCH_SCORE_STORAGE_ACCOUNT_URL",
            "GOLD_STORAGE_ACCOUNT_URL",
            "AZURE_STORAGE_ACCOUNT_URL",
            "BATCH_SCORE_STORAGE_ACCOUNT",
            "AZURE_STORAGE_ACCOUNT",
        ),
    )
    blob_client = blob_service.get_blob_client(container=container, blob=blob_path)
    exists = blob_client.exists()
    if exists and not reprocess:
        raise ValueError(
            f"job_id '{job_id}' already exists at {container}/{blob_path}; set reprocess=true to overwrite"
        )
    jsonl = "\n".join(json.dumps(x, separators=(",", ":")) for x in applicants) + "\n"
    blob_client.upload_blob(jsonl.encode("utf-8"), overwrite=True)
    props = blob_client.get_blob_properties()
    if int(props.size or 0) <= 0:
        raise ValueError(f"Uploaded blob is empty for job_id '{job_id}'")
    return container, blob_path


def _publish_batch_score_request_message(message: dict, *, message_id: str | None = None) -> None:
    if not _has_batch_score_service_bus_auth():
        raise ValueError(
            "Missing batch-score Service Bus auth config (connection string or namespace/FQDN)."
        )
    topic = _batch_score_topic_name()
    client = get_service_bus_client(
        connection_string_env_vars=(
            "BATCH_SCORE_REQUEST_SERVICE_BUS_CONNECTION_STRING",
            "TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING",
        ),
        namespace_env_vars=(
            "BATCH_SCORE_SERVICE_BUS_NAMESPACE",
            "TRANSFORM_OUTPUT_SERVICE_BUS_NAMESPACE",
            "SERVICE_BUS_FULLY_QUALIFIED_NAMESPACE",
            "SERVICE_BUS_NAMESPACE",
        ),
    )
    with client:
        with client.get_topic_sender(topic_name=topic) as sender:
            sender.send_messages(
                ServiceBusMessage(
                    json.dumps(message),
                    content_type="application/json",
                    message_id=message_id or str(message.get("job_id") or uuid.uuid4().hex),
                )
            )


def _submit_de_ml_batch(
    *,
    job_id: str,
    reprocess: bool,
    applicants: list[dict],
    correlation_id: str | None,
) -> dict:
    if not job_id:
        raise ValueError("Query parameter job_id is required")
    submitted_at = datetime.now(timezone.utc).isoformat()
    threshold = _batch_score_inline_threshold()
    row_count = len(applicants)
    if row_count <= threshold:
        message = {
            "schema_version": _DE_ML_BATCH_SCHEMA_VERSION,
            "job_id": job_id,
            "delivery_mode": "inline",
            "row_count": row_count,
            "applicants": applicants,
            "submitted_at": submitted_at,
        }
        if correlation_id:
            message["correlation_id"] = correlation_id
        _publish_batch_score_request_message(message, message_id=job_id)
        return {
            "schema_version": _DE_ML_BATCH_SCHEMA_VERSION,
            "job_id": job_id,
            "delivery_mode": "inline",
            "row_count": row_count,
            "inline_threshold": threshold,
            "published_topic": _batch_score_topic_name(),
            "reprocess": reprocess,
        }

    container, blob_path = _write_batch_applicants_jsonl(
        job_id=job_id, applicants=applicants, reprocess=reprocess
    )
    storage_account = (
        os.getenv("BATCH_SCORE_STORAGE_ACCOUNT")
        or os.getenv("AZURE_STORAGE_ACCOUNT")
        or ""
    ).strip()
    message = {
        "schema_version": _DE_ML_BATCH_SCHEMA_VERSION,
        "job_id": job_id,
        "delivery_mode": "blob_pointer",
        "row_count": row_count,
        "storage_account": storage_account,
        "container": container,
        "blob_path": blob_path,
        "submitted_at": submitted_at,
        "reprocess": reprocess,
    }
    if correlation_id:
        message["correlation_id"] = correlation_id
    _publish_batch_score_request_message(message, message_id=job_id)
    return {
        "schema_version": _DE_ML_BATCH_SCHEMA_VERSION,
        "job_id": job_id,
        "delivery_mode": "blob_pointer",
        "row_count": row_count,
        "inline_threshold": threshold,
        "published_topic": _batch_score_topic_name(),
        "storage_account": storage_account,
        "container": container,
        "blob_path": blob_path,
        "reprocess": reprocess,
    }


def _xds_payload_from_jsonl_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Map one JSONL object to the nested xds_payload shape expected by the orchestrator."""
    nested = obj.get("xds_payload")
    if isinstance(nested, dict):
        return nested
    if "consumer_full_report_45" in obj or "consumer_mobile_report_49" in obj:
        return dict(obj)
    # Matches dummified samples under project execution artifacts (raw inner bureau JSON per line).
    if "detailedFacilityInfo" in obj:
        return {"consumer_mobile_report_49": obj}
    return {"consumer_full_report_45": obj}


def _line_has_explicit_request_id(obj: Dict[str, Any]) -> bool:
    return bool(str(obj.get("request_id") or "").strip())


def _validate_jsonl_request_id_uniform(parsed: List[tuple[int, Dict[str, Any]]]) -> None:
    """
    Every line must follow the same rule as the single-inference contract:
    either all lines include a non-empty top-level request_id (backend standard),
    or none do (raw bureau JSONL only; ids derived as inference-{consumerID} / etc.).
    Mixing the two in one batch is rejected.
    """
    if len(parsed) < 2:
        return
    flags = [_line_has_explicit_request_id(obj) for _, obj in parsed]
    if any(flags) and not all(flags):
        raise ValueError(
            "JSONL request_id must be uniform: either every line includes a non-empty "
            '"request_id" (recommended; matches POST /transform/inference), or no line '
            "includes it (raw bureau lines only). Do not mix both styles in one batch."
        )


def _request_id_from_jsonl_object(obj: Dict[str, Any], line_number: int) -> str:
    rid = obj.get("request_id")
    if rid is not None and str(rid).strip():
        return str(rid).strip()
    inner: Dict[str, Any] | None = None
    if isinstance(obj.get("xds_payload"), dict):
        x = obj["xds_payload"]
        inner = x.get("consumer_full_report_45") or x.get("consumer_mobile_report_49")
    elif "consumer_full_report_45" in obj:
        inner = obj.get("consumer_full_report_45")
    elif "consumer_mobile_report_49" in obj:
        inner = obj.get("consumer_mobile_report_49")
    else:
        inner = obj
    if isinstance(inner, dict):
        pd = inner.get("personalDetailsSummary") or {}
        cid = pd.get("consumerID")
        if cid is not None and str(cid).strip() != "":
            return f"inference-{cid}"
        sl = inner.get("subjectList") or []
        if sl and isinstance(sl[0], dict):
            uid = sl[0].get("uniqueID")
            if uid is not None and str(uid).strip() != "":
                return f"inference-{uid}"
    return f"inference-batch-L{line_number}-{uuid.uuid4().hex[:12]}"


def _applicant_context_from_jsonl_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    ac = obj.get("applicant_context")
    return ac if isinstance(ac, dict) else {}


def _parse_models_to_run_query(raw: str | None) -> Any:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if s.startswith("["):
        try:
            v = json.loads(s)
            return v if isinstance(v, list) else None
        except json.JSONDecodeError:
            return None
    return [x.strip() for x in s.split(",") if x.strip()]


def _run_inference_batch_jsonl(
    parsed: List[tuple[int, Dict[str, Any]]],
    *,
    data_source_id: str,
    source_system: str,
    models_to_run: Any,
) -> Dict[str, Any]:
    """Best-effort: each item is (1-based line number, object); failures recorded in errors."""
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for i, obj in parsed:
        try:
            xds_payload = _xds_payload_from_jsonl_object(obj)
            request_id = _request_id_from_jsonl_object(obj, i)
            payload: Dict[str, Any] = {
                "request_id": request_id,
                "data_source_id": data_source_id,
                "source_system": source_system,
                "models_to_run": models_to_run,
                "xds_payload": xds_payload,
            }
            ac = _applicant_context_from_jsonl_object(obj)
            if ac:
                payload["applicant_context"] = ac
            result = _run_inference_pipeline(payload)
            results.append({"line": i, **result})
        except Exception as exc:
            logger.warning("Inference batch line %s failed: %s", i, exc, exc_info=True)
            errors.append({"line": i, "error": str(exc)})
    return {
        "data_source_id": data_source_id,
        "source_system": source_system,
        "total_lines": len(parsed),
        "succeeded": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def _run_inference_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Inference does not use schema-registry Redis (mapping cache). Anonymizer + stores
    honor INFERENCE_SKIP_REDIS for this call only so the worker can still use Redis
    on other routes after the request finishes.
    """
    prev_skip_redis = os.environ.get("INFERENCE_SKIP_REDIS")
    os.environ["INFERENCE_SKIP_REDIS"] = "1"
    _emit_transformation_progress(payload, "STARTING", "transform-started")
    try:
        xds_payload = _parse_json_object_maybe(payload.get("xds_payload"), "xds_payload")
        xds_payload = normalize_nested_xds_payload(xds_payload)
        flat_row = _flatten_xds_payload(xds_payload)
        request_id = str(payload.get("request_id", "inference-request"))
        data_source_id = str(payload.get("data_source_id") or "unknown")
        _validate_flat_row_schema_v1(flat_row, 0)
        inference_df = pd.DataFrame([flat_row])
        anonymized_df = anonymize_inference_dataframe(
            inference_df, bank_id=data_source_id, request_id=request_id
        )
        anonymized_row = anonymized_df.to_dict(orient="records")[0]
        anonymized_row = _restore_required_flat_45_fields_after_anonymize(flat_row, anonymized_row)
        _validate_flat_row_schema_v1(anonymized_row, 0)

        source_system = str(payload.get("source_system", "xds"))

        # ML handoff for inference: Service Bus topic inference-request (and optional HTTP parquet).

        transform_payload = {
            "flow_type": "inference",
            "request_id": request_id,
            "data_source_id": data_source_id,
            "source_system": source_system,
            "xds_payload": {"__flat_row__": anonymized_row},
            "models_to_run": payload.get("models_to_run"),
        }
        result = _transform_payload(transform_payload, publish_outputs=False)
        # inference contract: features only (no training targets)
        result.pop("targets", None)

        endpoint = _ml_engineer_http_endpoint_for_post()
        parquet_buf = io.BytesIO()
        pd.DataFrame([{"row_id": new_row_id(), **(result.get("features") or {})}]).to_parquet(
            parquet_buf, index=False
        )
        parquet_bytes = parquet_buf.getvalue()
        max_workers = 3 if endpoint else 2
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            if endpoint:
                futures.append(
                    executor.submit(
                        _post_inference_multipart,
                        parquet_bytes,
                        request_id,
                        source_system,
                        endpoint,
                    )
                )
            else:
                logger.warning(
                    "ML_ENGINEER_HTTP_ENDPOINT is not set; skipping multipart POST to ML engineer. "
                    "Inference-request Service Bus publish still runs when the connection string is configured."
                )
            futures.append(executor.submit(publish_backend_event, result))
            futures.append(executor.submit(publish_ml_messages, result))
            futures.append(executor.submit(publish_scoring_complete_hard_stop, result))
            for fut in futures:
                fut.result()
        hard_stop = bool((result.get("decision_package") or {}).get("hard_stop_triggered"))
        if hard_stop:
            _emit_transformation_progress(result, "HARD_STOP", "inference-hard-stop")
        else:
            _emit_transformation_progress(result, "INFERENCE_REQUEST_READY", "inference-features-ready")
        return result
    except Exception:
        _emit_transformation_progress(payload, "FAILED", "failed")
        raise
    finally:
        if prev_skip_redis is None:
            os.environ.pop("INFERENCE_SKIP_REDIS", None)
        else:
            os.environ["INFERENCE_SKIP_REDIS"] = prev_skip_redis


def _validate_mapping_complete_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate mapping-complete handoff contract for transformation trigger."""
    if not payload.get("request_id"):
        payload["request_id"] = payload.get("training_upload_id")
    required_fields = (
        "request_id",
        "training_upload_id",
        "anonymized_silver_path",
        "analysis_context_path",
    )
    missing = [f for f in required_fields if not payload.get(f)]
    if missing:
        raise ValueError(f"Missing required mapping-complete fields: {', '.join(missing)}")
    return payload


@app.route(route="transform/inference", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def transform_inference(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP: single-applicant inference (JSON body) — features, hard-stop, ML handoff."""
    try:
        _ensure_inference_publish_config()
        payload = req.get_json()
        result = _run_inference_pipeline(payload)

        return func.HttpResponse(
            body=json.dumps(result),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.error("Inference transformation failed: %s", exc, exc_info=True)
        return func.HttpResponse(
            body=json.dumps({"error": str(exc)}),
            status_code=400,
            mimetype="application/json",
        )


@app.route(route="transform/inference/batch", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def transform_inference_batch(req: func.HttpRequest) -> func.HttpResponse:
    """Bulk inference: UTF-8 body is JSONL (one JSON object per line, one consumer per line)."""
    try:
        _ensure_inference_publish_config()
        data_source_id = (req.params.get("data_source_id") or "").strip()
        if not data_source_id:
            return func.HttpResponse(
                body=json.dumps({"error": "Query parameter data_source_id is required"}),
                status_code=400,
                mimetype="application/json",
            )
        source_system = (req.params.get("source_system") or "xds").strip() or "xds"
        models_to_run = _parse_models_to_run_query(req.params.get("models_to_run"))

        body_bytes = req.get_body()
        if not body_bytes:
            return func.HttpResponse(
                body=json.dumps({"error": "Request body is empty"}),
                status_code=400,
                mimetype="application/json",
            )
        text = body_bytes.decode("utf-8")
        raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        max_n = _inference_batch_max_lines()
        if len(raw_lines) > max_n:
            return func.HttpResponse(
                body=json.dumps(
                    {
                        "error": f"Too many lines: {len(raw_lines)} (max {max_n})",
                        "max_lines": max_n,
                    }
                ),
                status_code=400,
                mimetype="application/json",
            )
        parse_errors: List[Dict[str, Any]] = []
        parsed: List[tuple[int, Dict[str, Any]]] = []
        for line_no, line in enumerate(raw_lines, start=1):
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError("JSON line must be an object")
                parsed.append((line_no, obj))
            except Exception as exc:
                parse_errors.append({"line": line_no, "error": str(exc)})
        try:
            _validate_jsonl_request_id_uniform(parsed)
        except ValueError as exc:
            return func.HttpResponse(
                body=json.dumps({"error": str(exc)}),
                status_code=400,
                mimetype="application/json",
            )
        out = _run_inference_batch_jsonl(
            parsed,
            data_source_id=data_source_id,
            source_system=source_system,
            models_to_run=models_to_run,
        )
        out["errors"] = parse_errors + out["errors"]
        out["failed"] = len(out["errors"])
        out["total_lines"] = len(raw_lines)
        out["succeeded"] = len(out["results"])
        return func.HttpResponse(
            body=json.dumps(out),
            status_code=200,
            mimetype="application/json",
        )
    except UnicodeDecodeError as exc:
        return func.HttpResponse(
            body=json.dumps({"error": f"Body must be UTF-8: {exc}"}),
            status_code=400,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.error("Inference batch failed: %s", exc, exc_info=True)
        return func.HttpResponse(
            body=json.dumps({"error": str(exc)}),
            status_code=400,
            mimetype="application/json",
        )


@app.route(route="transform/inference/batch/submit", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def transform_inference_batch_submit(req: func.HttpRequest) -> func.HttpResponse:
    """
    DE -> ML async batch handoff.
    Body is JSONL where each line is {request_id, features(30 keys), metadata}.
    Publishes to batch-score-request using inline (<= threshold) or blob pointer mode.
    """
    try:
        job_id = (req.params.get("job_id") or "").strip()
        reprocess = _parse_reprocess_query_default_true(req.params.get("reprocess"))
        correlation_id = (req.params.get("correlation_id") or "").strip() or None
        parsed = _parse_jsonl_lines(req.get_body())
        applicants = _normalize_batch_score_applicants(parsed)
        out = _submit_de_ml_batch(
            job_id=job_id,
            reprocess=reprocess,
            applicants=applicants,
            correlation_id=correlation_id,
        )
        return func.HttpResponse(
            body=json.dumps(out),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.error("Batch submit failed: %s", exc, exc_info=True)
        return func.HttpResponse(
            body=json.dumps({"error": str(exc)}),
            status_code=400,
            mimetype="application/json",
        )


@app.route(route="transform/training", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def transform_training(req: func.HttpRequest) -> func.HttpResponse:
    """HTTP: single training transform — gold parquet + backend/ML publishing when enabled."""
    try:
        payload = req.get_json()
        payload["flow_type"] = "training"
        _emit_transformation_progress(payload, "STARTING", "transform-started")
        result = _transform_payload(payload)
        _emit_transformation_progress(result, "TRANSFORMED", "training-curation-complete")
        _emit_transformation_progress(result, "ML_HANDOFF_READY", "training-ready-for-ml")
        return func.HttpResponse(
            body=json.dumps(result),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as exc:
        _emit_transformation_progress(payload if "payload" in locals() else {}, "FAILED", "failed")
        logger.error("Training transformation failed: %s", exc, exc_info=True)
        return func.HttpResponse(
            body=json.dumps({"error": str(exc)}),
            status_code=400,
            mimetype="application/json",
        )


@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="schema-mapping-service",
    subscription_name="mapping-complete",
    # Keep this name for backward compatibility; identity mode uses
    # ServiceBusConnectionString__fullyQualifiedNamespace app setting.
    connection="ServiceBusConnectionString",
)
def transformation_trigger(message: func.ServiceBusMessage) -> None:
    """
    Keep topic trigger for current orchestration compatibility.
    Message payload must contain the deterministic request contract.
    """
    try:
        payload = json.loads(message.get_body().decode("utf-8"))
        payload = _validate_mapping_complete_payload(payload)
        _emit_transformation_progress(payload, "STARTING", "transform-started")

        # Default to training flow when triggered from pipeline.
        payload.setdefault("flow_type", "training")
        if payload.get("flow_type") == "training":
            result = _transform_training_batch_from_silver(payload)
            _emit_transformation_progress(result, "TRANSFORMED", "training-curation-complete")
            _emit_transformation_progress(result, "ML_HANDOFF_READY", "training-ready-for-ml")
        else:
            result = _transform_payload(payload)
            hard_stop = bool((result.get("decision_package") or {}).get("hard_stop_triggered"))
            if hard_stop:
                _emit_transformation_progress(result, "HARD_STOP", "inference-hard-stop")
            else:
                _emit_transformation_progress(result, "INFERENCE_REQUEST_READY", "inference-features-ready")

        logger.warning(
            "Transformation completed: request_id=%s status=%s",
            result.get("request_id"),
            result.get("bureau_hit_status"),
        )
    except Exception as exc:
        _emit_transformation_progress(payload if "payload" in locals() else {}, "FAILED", "failed")
        logger.error("Service Bus transformation failed: %s", exc, exc_info=True)
        raise
