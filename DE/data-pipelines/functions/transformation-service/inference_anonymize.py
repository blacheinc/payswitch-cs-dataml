"""Inference preprocessing: anonymize flattened rows using bundled PII detector/anonymizer."""

from __future__ import annotations

import logging
import os
from typing import Any, Tuple, Type

import pandas as pd
from transformation_service_anonymization.dataset_anonymizer import DatasetAnonymizer
from transformation_service_anonymization.system_interfaces import (
    DataAnalysisResult,
    SchemaDetectionResult,
)

logger = logging.getLogger(__name__)


def _load_anonymizer_types() -> Tuple[Any, Any, Any]:
    return DatasetAnonymizer, SchemaDetectionResult, DataAnalysisResult


def _scalar_type(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    return "string"


def _schema_detection_from_df(df: pd.DataFrame, SchemaDetectionResult: Type[Any]) -> Any:
    cols = [str(c) for c in df.columns]
    types = {c: _scalar_type(df[c].iloc[0]) for c in cols}
    return SchemaDetectionResult(
        format="json",
        encoding="utf-8",
        column_count=len(cols),
        row_count=len(df),
        column_names=cols,
        column_types=types,
        confidence=1.0,
    )


def _analysis_from_df(df: pd.DataFrame, DataAnalysisResult: Type[Any]) -> Any:
    cols = [str(c) for c in df.columns]
    n = len(df)
    missing_data = {}
    for c in cols:
        nulls = int(df[c].isna().sum())
        missing_data[c] = {
            "null_count": nulls,
            "total_rows": n,
            "completeness_pct": round(100.0 * (1 - nulls / n), 4) if n else 0.0,
        }
    return DataAnalysisResult(
        data_types={c: _scalar_type(df[c].iloc[0]) for c in cols},
        missing_data=missing_data,
        distributions={},
        formats={},
        text_patterns={},
        nested_structures={"array_fields": [], "nested_paths": []},
        aggregated_insights={},
    )


def anonymize_inference_dataframe(
    df: pd.DataFrame,
    bank_id: str,
    request_id: str | None = None,
) -> pd.DataFrame:
    """
    PII-detect and anonymize a small inference frame using DatasetAnonymizer.
    """
    DatasetAnonymizer, SchemaDetectionResult, DataAnalysisResult = _load_anonymizer_types()
    kv = os.getenv("KEY_VAULT_URL", "").strip() or None
    use_llm = bool(kv)
    anonymizer = DatasetAnonymizer(
        key_vault_url=kv,
        use_llm=use_llm,
        service_bus_writer=None,
        run_id=request_id,
        state_tracker=None,
    )
    schema = _schema_detection_from_df(df, SchemaDetectionResult)
    analysis = _analysis_from_df(df, DataAnalysisResult)
    parsed_message = {
        "bank_id": bank_id,
        "training_upload_id": request_id or "inference",
        "run_id": request_id or "inference",
    }
    anonymizer.set_system_results(
        introspection_result=None,
        schema_result=schema,
        sampling_result=None,
        analysis_result=analysis,
        parsed_message=parsed_message,
    )
    pii = anonymizer.detect_pii(schema, analysis, bank_id=bank_id)
    result = anonymizer.anonymize_dataframe(df, pii, method="hash")
    return result.anonymized_data
