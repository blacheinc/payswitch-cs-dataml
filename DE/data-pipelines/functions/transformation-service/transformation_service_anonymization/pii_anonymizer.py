from __future__ import annotations

import hashlib
from typing import Dict

import pandas as pd

from transformation_service_anonymization.system_interfaces import AnonymizationResult, PIIDetectionResult


class PIIAnonymizer:
    def __init__(self, salt: str = "") -> None:
        self.salt = salt
        self._token_counter: Dict[str, int] = {}

    def anonymize_dataframe(
        self, df: pd.DataFrame, pii_fields: PIIDetectionResult, method: str = "hash"
    ) -> AnonymizationResult:
        all_pii_cols = list(pii_fields.anonymization_methods.keys())
        all_pii_cols = [c for c in all_pii_cols if c in df.columns]
        if not all_pii_cols:
            return AnonymizationResult(
                anonymized_data=df.copy(),
                anonymization_mappings={},
                pii_fields=pii_fields,
            )

        result_df = df.copy()
        mappings: Dict[str, Dict[str, str]] = {col: {} for col in all_pii_cols}
        for col in all_pii_cols:
            col_method = pii_fields.anonymization_methods.get(col, method)
            result_df[col], mappings[col] = self._anonymize_series(result_df[col], col, col_method)

        return AnonymizationResult(
            anonymized_data=result_df,
            anonymization_mappings=mappings,
            pii_fields=pii_fields,
        )

    def _anonymize_series(self, series: pd.Series, col_name: str, method: str) -> tuple[pd.Series, Dict[str, str]]:
        mapping: Dict[str, str] = {}
        result = series.copy()
        if result.dtype != "object":
            result = result.astype("object")
        for idx in series.dropna().index:
            val = series.loc[idx]
            val_str = str(val).strip()
            if not val_str:
                continue
            if val_str in mapping:
                result.loc[idx] = mapping[val_str]
                continue
            if method == "hash":
                anonymized = self._hash_value(val_str)
            elif method == "tokenize":
                anonymized = self._tokenize_value(col_name)
            elif method == "generalize":
                anonymized = self._generalize_value(col_name)
            else:
                anonymized = self._hash_value(val_str)
            mapping[val_str] = anonymized
            result.loc[idx] = anonymized
        return result, mapping

    def _hash_value(self, value: str) -> str:
        return hashlib.sha256(f"{self.salt}{value}".encode("utf-8")).hexdigest()[:16]

    def _tokenize_value(self, col_name: str) -> str:
        self._token_counter[col_name] = self._token_counter.get(col_name, 0) + 1
        return f"PII_{col_name}_{self._token_counter[col_name]}"

    def _generalize_value(self, col_name: str) -> str:
        lower = col_name.lower()
        if any(token in lower for token in ("address", "street", "city")):
            return "[LOCATION]"
        if any(token in lower for token in ("id", "ssn", "passport")):
            return "[ID]"
        return "[REDACTED]"

