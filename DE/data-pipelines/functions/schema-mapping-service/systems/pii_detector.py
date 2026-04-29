"""
System 4.1: PII Detector
Schema-only PII detection using rule-based patterns and optional LLM
"""

import logging
import re
from typing import Dict, List, Optional, Callable, Any

import pandas as pd

try:
    from system_interfaces import (
        PIIDetectionResult, 
        SchemaDetectionResult,
        DataAnalysisResult
    )
except ImportError:
    from ..system_interfaces import (
        PIIDetectionResult, 
        SchemaDetectionResult,
        DataAnalysisResult
    )

logger = logging.getLogger(__name__)


# Column name patterns for rule-based PII detection (case-insensitive)
NAME_PATTERNS = [
    r'\bname\b', r'\bnames\b', r'\bfirst_name\b', r'\blast_name\b',
    r'\bfull_name\b', r'\bcustomer_name\b', r'\bapplicant_name\b',
    r'\bclient_name\b', r'\bcontact_name\b', r'\bperson_name\b',
]
EMAIL_PATTERNS = [
    r'\bemail\b', r'\bemails\b', r'\bemail_address\b', r'\be_mail\b',
    r'\bmail\b', r'\bcontact_email\b', r'\bcustomer_email\b',
]
PHONE_PATTERNS = [
    r'\bphone\b', r'\bphones\b', r'\btelephone\b', r'\bmobile\b',
    r'\bcell\b', r'\bcontact_number\b', r'\bphone_number\b',
    r'\bmobile_number\b', r'\btelephone_number\b',
]
ID_PATTERNS = [
    r'\bnational_id\b', r'\bpassport\b', r'\bpassport_number\b', r'\bssn\b',
    r'\bsocial_security\b', r'\bdriver_license\b', r'\bdrivers_license\b',
    r'\bvin\b', r'\bemployee_id\b', r'\bcustomer_id\b', r'\bapplicant_id\b',
]
ADDRESS_PATTERNS = [
    r'\baddress\b', r'\baddresses\b', r'\bhome_address\b', r'\bbilling_address\b',
    r'\bmailing_address\b', r'\bstreet\b', r'\bcity\b', r'\bpostal\b',
    r'\bzip\b', r'\bzipcode\b', r'\bpostcode\b', r'\blocation\b',
]


def _matches_any_pattern(column_name: str, patterns: List[str]) -> bool:
    """Check if column name matches any pattern (case-insensitive)"""
    col_lower = column_name.lower().strip()
    for pattern in patterns:
        if re.search(pattern, col_lower, re.IGNORECASE):
            return True
    return False


def _categorize_column(column_name: str, column_type: str) -> Optional[str]:
    """
    Categorize a column as PII type based on name and type.
    Returns: 'names', 'emails', 'phones', 'ids', 'addresses', 'other', or None
    """
    if _matches_any_pattern(column_name, NAME_PATTERNS):
        return 'names'
    if _matches_any_pattern(column_name, EMAIL_PATTERNS):
        return 'emails'
    if _matches_any_pattern(column_name, PHONE_PATTERNS):
        return 'phones'
    if _matches_any_pattern(column_name, ID_PATTERNS):
        return 'ids'
    if _matches_any_pattern(column_name, ADDRESS_PATTERNS):
        return 'addresses'
    return None


class PIIDetector:
    """
    PII Detector - Schema-only detection (no raw data sent to LLM)
    Uses LLM as primary method if callback provided; falls back to rule-based patterns
    """

    def __init__(
        self,
        llm_callback: Optional[Callable[..., PIIDetectionResult]] = None
    ):
        """
        Args:
            llm_callback: Optional. If provided, called with full context:
                          (column_names, column_types, schema_result, data_analysis_result, introspection_result)
                          to get LLM-assisted detection. Falls back to rule-based if None or if LLM fails.
                          Supports both old signature (column_names, column_types) and new signature with full context.
        """
        self.llm_callback = llm_callback

    def detect_pii(
        self,
        column_names: List[str],
        column_types: Dict[str, str],
        schema_result: Optional[SchemaDetectionResult] = None,
        data_analysis_result: Optional[DataAnalysisResult] = None,
        introspection_result: Optional[Dict[str, Any]] = None
    ) -> PIIDetectionResult:
        """
        Detect PII fields using schema-only (column names + types).
        No actual data values are used.

        Args:
            column_names: List of column names from schema
            column_types: Dict mapping column name -> data type
            schema_result: Optional schema detection result for context
            data_analysis_result: Optional data analysis result for context (patterns, distributions, etc.)
            introspection_result: Optional file introspection result for context (format hints, etc.)

        Returns:
            PIIDetectionResult with detected PII fields by category and anonymization methods
        """
        # SECURITY CHECK: Ensure NO DataFrame values reach LLM - schema metadata only
        assert isinstance(column_names, list), "column_names must be a list, not DataFrame"
        assert isinstance(column_types, dict), "column_types must be a dict, not DataFrame"
        assert not any(isinstance(x, (pd.DataFrame, pd.Series)) for x in [column_names, column_types]), \
            "SECURITY VIOLATION: DataFrames/Series detected in PII detection inputs"
        
        if self.llm_callback:
            try:
                # Try new signature with full context first
                import inspect
                sig = inspect.signature(self.llm_callback)
                param_count = len(sig.parameters)
                
                if param_count >= 5:
                    # New signature with full context
                    result = self.llm_callback(
                        column_names, 
                        column_types, 
                        schema_result, 
                        data_analysis_result, 
                        introspection_result
                    )
                elif param_count == 2:
                    # Old signature (backward compatibility)
                    result = self.llm_callback(column_names, column_types)
                else:
                    # Try with available parameters
                    result = self.llm_callback(
                        column_names, 
                        column_types, 
                        schema_result, 
                        data_analysis_result, 
                        introspection_result
                    )
                
                if result and isinstance(result, PIIDetectionResult):
                    logger.info("LLM PII detection succeeded")
                    return result
            except TypeError as e:
                # Signature mismatch - try old signature
                try:
                    result = self.llm_callback(column_names, column_types)
                    if result and isinstance(result, PIIDetectionResult):
                        logger.info("LLM PII detection succeeded (using old signature)")
                        return result
                except Exception:
                    logger.warning(f"LLM PII detection failed with both signatures, falling back to rules: {e}")
            except Exception as e:
                logger.warning(f"LLM PII detection failed, falling back to rules: {e}")

        return self._rule_based_detect(column_names, column_types)

    def _rule_based_detect(
        self,
        column_names: List[str],
        column_types: Dict[str, str]
    ) -> PIIDetectionResult:
        """
        Rule-based PII detection from column names and types.
        Also suggests anonymization methods based on PII category.
        """
        result = PIIDetectionResult()
        anonymization_methods: Dict[str, str] = {}

        for col in column_names:
            col_type = column_types.get(col, 'string')
            category = _categorize_column(col, col_type)

            if category == 'names':
                result.names.append(col)
                anonymization_methods[col] = "tokenize"  # Preserve relationships
            elif category == 'emails':
                result.emails.append(col)
                anonymization_methods[col] = "hash"  # Exact matching may be needed
            elif category == 'phones':
                result.phones.append(col)
                anonymization_methods[col] = "hash"  # Exact matching may be needed
            elif category == 'ids':
                result.ids.append(col)
                anonymization_methods[col] = "hash"  # IDs need exact matching
            elif category == 'addresses':
                result.addresses.append(col)
                anonymization_methods[col] = "generalize"  # Reduce specificity

        result.anonymization_methods = anonymization_methods
        return result

    def get_all_pii_columns(self, pii_result: PIIDetectionResult) -> List[str]:
        """Get flat list of all PII column names"""
        return (
            pii_result.names + pii_result.emails + pii_result.phones +
            pii_result.ids + pii_result.addresses + pii_result.other
        )
