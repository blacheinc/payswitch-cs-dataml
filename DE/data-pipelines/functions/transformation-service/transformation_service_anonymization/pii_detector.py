"""Lightweight PII column classification from header names (regex heuristics)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from transformation_service_anonymization.system_interfaces import PIIDetectionResult

NAME_PATTERNS = [r"\bname\b", r"\bfirst_name\b", r"\blast_name\b", r"\bfull_name\b"]
EMAIL_PATTERNS = [r"\bemail\b", r"\bemail_address\b"]
PHONE_PATTERNS = [r"\bphone\b", r"\bmobile\b", r"\btelephone\b"]
ID_PATTERNS = [r"\bnational_id\b", r"\bpassport\b", r"\bssn\b", r"\bcustomer_id\b"]
ADDRESS_PATTERNS = [r"\baddress\b", r"\bstreet\b", r"\bcity\b", r"\bpostal\b", r"\bzip\b"]


def _matches_any_pattern(column_name: str, patterns: List[str]) -> bool:
    name = column_name.lower().strip()
    return any(re.search(pattern, name, re.IGNORECASE) for pattern in patterns)


def _categorize_column(column_name: str) -> Optional[str]:
    if _matches_any_pattern(column_name, NAME_PATTERNS):
        return "names"
    if _matches_any_pattern(column_name, EMAIL_PATTERNS):
        return "emails"
    if _matches_any_pattern(column_name, PHONE_PATTERNS):
        return "phones"
    if _matches_any_pattern(column_name, ID_PATTERNS):
        return "ids"
    if _matches_any_pattern(column_name, ADDRESS_PATTERNS):
        return "addresses"
    return None


class PIIDetector:
    """Assigns columns to PII categories and suggests anonymization methods."""

    def detect_pii(self, column_names: List[str], column_types: Dict[str, str]) -> PIIDetectionResult:
        result = PIIDetectionResult()
        anonymization_methods: Dict[str, str] = {}

        for col in column_names:
            _ = column_types.get(col, "string")
            category = _categorize_column(col)
            if category == "names":
                result.names.append(col)
                anonymization_methods[col] = "tokenize"
            elif category == "emails":
                result.emails.append(col)
                anonymization_methods[col] = "hash"
            elif category == "phones":
                result.phones.append(col)
                anonymization_methods[col] = "hash"
            elif category == "ids":
                result.ids.append(col)
                anonymization_methods[col] = "hash"
            elif category == "addresses":
                result.addresses.append(col)
                anonymization_methods[col] = "generalize"

        result.anonymization_methods = anonymization_methods
        return result

