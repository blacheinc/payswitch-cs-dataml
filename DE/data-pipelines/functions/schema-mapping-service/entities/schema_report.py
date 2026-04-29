"""
SchemaReport entity class
Represents schema analysis results
"""

from typing import Optional, Dict, Any, List
from datetime import datetime


class SchemaReport:
    """
    Represents schema analysis results
    
    Attributes:
        column_names: List of column names
        column_types: Dictionary mapping column names to types
        nullable_columns: List of nullable column names
        required_columns: List of required column names
        completeness_score: Overall completeness score (0.0 to 1.0)
        field_mappings: Dictionary mapping source columns to target schema fields
        confidence_scores: Dictionary of confidence scores per field
        metadata: Additional metadata
        created_at: Timestamp when report was created
    """
    
    def __init__(
        self,
        column_names: List[str],
        column_types: Dict[str, str],
        nullable_columns: Optional[List[str]] = None,
        required_columns: Optional[List[str]] = None,
        completeness_score: float = 0.0,
        field_mappings: Optional[Dict[str, str]] = None,
        confidence_scores: Optional[Dict[str, float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None
    ):
        self.column_names = column_names
        self.column_types = column_types
        self.nullable_columns = nullable_columns or []
        self.required_columns = required_columns or []
        self.completeness_score = completeness_score
        self.field_mappings = field_mappings or {}
        self.confidence_scores = confidence_scores or {}
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "column_names": self.column_names,
            "column_types": self.column_types,
            "nullable_columns": self.nullable_columns,
            "required_columns": self.required_columns,
            "completeness_score": self.completeness_score,
            "field_mappings": self.field_mappings,
            "confidence_scores": self.confidence_scores,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
