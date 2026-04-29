"""
System 4.2: PII Anonymizer
Anonymizes PII in DataFrames using hash, tokenize, or generalize methods
"""

import hashlib
import logging
from typing import Dict, List

import pandas as pd

try:
    from system_interfaces import PIIDetectionResult, AnonymizationResult
except ImportError:
    from ..system_interfaces import PIIDetectionResult, AnonymizationResult

logger = logging.getLogger(__name__)


class PIIAnonymizer:
    """
    Anonymizes PII columns in DataFrames.
    Supports: hash (SHA-256), tokenize (PII_1, PII_2), generalize (placeholder)
    """

    def __init__(self, salt: str = ""):
        """
        Args:
            salt: Optional salt for hashing (improves uniqueness, not security)
        """
        self.salt = salt
        self._token_counter: Dict[str, int] = {}

    def anonymize_dataframe(
        self,
        df: pd.DataFrame,
        pii_fields: PIIDetectionResult,
        method: str = "hash"
    ) -> AnonymizationResult:
        """
        Anonymize PII columns in DataFrame.

        Args:
            df: Source DataFrame
            pii_fields: Detected PII fields from PIIDetector
            method: "hash" | "tokenize" | "generalize"

        Returns:
            AnonymizationResult with anonymized DataFrame and mappings
        """
        # Use anonymization_methods keys as the primary source of truth.
        # This ensures strict 1-to-1 mapping with what the LLM specifically flagged.
        if pii_fields.anonymization_methods:
            all_pii_cols = list(pii_fields.anonymization_methods.keys())
        else:
            # Fallback to category lists if anonymization_methods is empty (e.g., rule-based)
            all_pii_cols = (
                pii_fields.names + pii_fields.emails + pii_fields.phones +
                pii_fields.ids + pii_fields.addresses + pii_fields.other
            )
            
        all_pii_cols = [c for c in all_pii_cols if c in df.columns]

        if not all_pii_cols:
            return AnonymizationResult(
                anonymized_data=df.copy(),
                anonymization_mappings={},
                pii_fields=pii_fields
            )

        result_df = df.copy()
        mappings: Dict[str, Dict[str, str]] = {col: {} for col in all_pii_cols}

        for col in all_pii_cols:
            if col not in result_df.columns:
                continue
            
            # Use per-column method from PIIDetectionResult if available, otherwise use default method
            col_method = pii_fields.anonymization_methods.get(col, method)
            
            result_df[col], mappings[col] = self._anonymize_series(
                result_df[col], col, col_method
            )

        return AnonymizationResult(
            anonymized_data=result_df,
            anonymization_mappings=mappings,
            pii_fields=pii_fields
        )

    def _anonymize_series(
        self,
        series: pd.Series,
        col_name: str,
        method: str
    ) -> tuple:
        """Anonymize a single column/series. Returns (anonymized_series, mapping)."""
        mapping: Dict[str, str] = {}
        result = series.copy()
        
        # Convert to object dtype to allow string values (anonymized hashes/tokens)
        # This is necessary when the original column is numeric (int64, float64, etc.)
        # and we're replacing values with string hashes
        if result.dtype != 'object':
            result = result.astype('object')

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
                anonymized = self._tokenize_value(val_str, col_name)
            elif method == "generalize":
                anonymized = self._generalize_value(val_str, col_name)
            else:
                anonymized = self._hash_value(val_str)

            mapping[val_str] = anonymized
            result.loc[idx] = anonymized

        return result, mapping

    def _hash_value(self, value: str) -> str:
        """SHA-256 hash of value (with optional salt)"""
        to_hash = f"{self.salt}{value}".encode('utf-8')
        return hashlib.sha256(to_hash).hexdigest()[:16]

    def _tokenize_value(self, value: str, col_name: str) -> str:
        """Replace with token PII_{col}_{n}"""
        if col_name not in self._token_counter:
            self._token_counter[col_name] = 0
        self._token_counter[col_name] += 1
        return f"PII_{col_name}_{self._token_counter[col_name]}"

    def _generalize_value(self, value: str, col_name: str) -> str:
        """Replace with generalized placeholder"""
        col_lower = col_name.lower()
        if any(p in col_lower for p in ['name', 'email', 'phone']):
            return "[REDACTED]"
        if any(p in col_lower for p in ['address', 'street', 'city']):
            return "[LOCATION]"
        if any(p in col_lower for p in ['id', 'ssn', 'passport']):
            return "[ID]"
        return "[PII]"

    def reset_token_counter(self) -> None:
        """Reset token counter (call between DataFrames if reusing)"""
        self._token_counter.clear()
