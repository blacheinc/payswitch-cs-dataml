"""
PIIReport entity class
Represents PII detection results
"""

from typing import List, Dict, Any, Optional
from datetime import datetime


class PIIReport:
    """
    Represents PII detection results
    
    Attributes:
        pii_columns: List of column names identified as PII
        pii_types: Dictionary mapping column names to PII types (name, email, phone, etc.)
        confidence_scores: Dictionary mapping column names to confidence scores
        anonymization_mappings: Dictionary of anonymization mappings (stored in Redis)
        metadata: Additional metadata
        detected_at: Timestamp when PII was detected
    """
    
    def __init__(
        self,
        pii_columns: List[str],
        pii_types: Dict[str, str],
        confidence_scores: Optional[Dict[str, float]] = None,
        anonymization_mappings: Optional[Dict[str, Dict[str, str]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        detected_at: Optional[datetime] = None
    ):
        self.pii_columns = pii_columns
        self.pii_types = pii_types
        self.confidence_scores = confidence_scores or {}
        self.anonymization_mappings = anonymization_mappings or {}
        self.metadata = metadata or {}
        self.detected_at = detected_at or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "pii_columns": self.pii_columns,
            "pii_types": self.pii_types,
            "confidence_scores": self.confidence_scores,
            "anonymization_mappings": self.anonymization_mappings,
            "metadata": self.metadata,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None
        }
