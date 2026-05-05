"""Applies PII detection + anonymization to a DataFrame for inference exports."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from transformation_service_anonymization.pii_anonymizer import PIIAnonymizer
from transformation_service_anonymization.pii_detector import PIIDetector
from transformation_service_anonymization.system_interfaces import (
    AnonymizationResult,
    DataAnalysisResult,
    PIIDetectionResult,
    SchemaDetectionResult,
)


class DatasetAnonymizer:
    """
    Local transformation-service copy of required anonymization behavior.
    This intentionally keeps the minimal API used by inference_anonymize.py.
    """

    def __init__(
        self,
        use_llm: bool = False,
        key_vault_url: Optional[str] = None,
        service_bus_writer: Any = None,
        run_id: Optional[str] = None,
        state_tracker: Any = None,
    ) -> None:
        self.use_llm = use_llm
        self.key_vault_url = key_vault_url
        self.service_bus_writer = service_bus_writer
        self.run_id = run_id
        self.state_tracker = state_tracker
        self.pii_detector = PIIDetector()
        self.pii_anonymizer = PIIAnonymizer()
        self._message_context: Optional[Dict[str, Any]] = None
        self._schema_result: Optional[SchemaDetectionResult] = None
        self._analysis_result: Optional[DataAnalysisResult] = None

    def set_system_results(
        self,
        introspection_result: Optional[Dict[str, Any]] = None,
        schema_result: Optional[SchemaDetectionResult] = None,
        sampling_result: Optional[Dict[str, Any]] = None,
        analysis_result: Optional[DataAnalysisResult] = None,
        parsed_message: Optional[Dict[str, Any]] = None,
    ) -> None:
        _ = introspection_result
        _ = sampling_result
        self._schema_result = schema_result
        self._analysis_result = analysis_result
        self._message_context = parsed_message

    def detect_pii(
        self,
        schema_result: SchemaDetectionResult,
        data_analysis_result: Optional[DataAnalysisResult] = None,
        bank_id: Optional[str] = None,
    ) -> PIIDetectionResult:
        _ = bank_id
        if not schema_result.column_names:
            raise ValueError("schema_result.column_names is required for PII detection")
        column_types = (
            (data_analysis_result.data_types if data_analysis_result else None)
            or schema_result.column_types
            or {name: "string" for name in schema_result.column_names}
        )
        return self.pii_detector.detect_pii(schema_result.column_names, column_types)

    def anonymize_dataframe(
        self,
        df: pd.DataFrame,
        pii_fields: PIIDetectionResult,
        method: str = "hash",
    ) -> AnonymizationResult:
        return self.pii_anonymizer.anonymize_dataframe(df, pii_fields, method)

