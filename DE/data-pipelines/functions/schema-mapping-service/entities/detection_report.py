"""
DetectionReport entity class
Represents schema detection results
"""

from typing import Optional, List, Dict, Any
from datetime import datetime


class DetectionReport:
    """
    Represents schema detection results
    
    Attributes:
        format: Detected file format (csv, json, parquet, etc.)
        encoding: Detected encoding
        delimiter: Delimiter if applicable (for CSV/TSV)
        has_header: Whether file has header row
        column_count: Number of columns
        row_count: Number of rows
        nested_structure: Whether data has nested structures
        sheets: List of sheet names (for Excel)
        column_names: List of column names
        column_types: Dictionary mapping column names to types
        confidence: Confidence score (0.0 to 1.0)
        evidence: List of evidence strings for format detection
        metadata: Additional metadata
        detected_at: Timestamp when detection was performed
    """
    
    def __init__(
        self,
        format: str,
        encoding: str,
        delimiter: Optional[str] = None,
        has_header: bool = True,
        column_count: int = 0,
        row_count: int = 0,
        nested_structure: bool = False,
        sheets: Optional[List[str]] = None,
        column_names: Optional[List[str]] = None,
        column_types: Optional[Dict[str, str]] = None,
        confidence: float = 0.0,
        evidence: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        detected_at: Optional[datetime] = None
    ):
        self.format = format
        self.encoding = encoding
        self.delimiter = delimiter
        self.has_header = has_header
        self.column_count = column_count
        self.row_count = row_count
        self.nested_structure = nested_structure
        self.sheets = sheets or []
        self.column_names = column_names or []
        self.column_types = column_types or {}
        self.confidence = confidence
        self.evidence = evidence or []
        self.metadata = metadata or {}
        self.detected_at = detected_at or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "format": self.format,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "has_header": self.has_header,
            "column_count": self.column_count,
            "row_count": self.row_count,
            "nested_structure": self.nested_structure,
            "sheets": self.sheets,
            "column_names": self.column_names,
            "column_types": self.column_types,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "metadata": self.metadata,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None
        }
