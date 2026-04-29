from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SchemaDetectionResult(BaseModel):
    format: str
    encoding: str
    column_count: int = 0
    row_count: int = 0
    column_names: Optional[List[str]] = None
    column_types: Optional[Dict[str, str]] = None
    confidence: float = 0.0


class DataAnalysisResult(BaseModel):
    data_types: Dict[str, str]
    missing_data: Dict[str, Dict[str, Any]]
    distributions: Dict[str, Dict[str, Any]]
    formats: Dict[str, Dict[str, Any]]
    text_patterns: Dict[str, Dict[str, Any]] = {}
    nested_structures: Dict[str, List[str]]
    aggregated_insights: Dict[str, Any]


class PIIDetectionResult(BaseModel):
    names: List[str] = []
    emails: List[str] = []
    phones: List[str] = []
    ids: List[str] = []
    addresses: List[str] = []
    other: List[str] = []
    anonymization_methods: Dict[str, str] = {}


class AnonymizationResult(BaseModel):
    anonymized_data: Any
    anonymization_mappings: Dict[str, Dict[str, str]]
    pii_fields: PIIDetectionResult

    class Config:
        arbitrary_types_allowed = True

