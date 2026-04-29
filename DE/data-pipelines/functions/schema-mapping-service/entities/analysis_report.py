"""
AnalysisReport entity class
Represents comprehensive data analysis results
"""

from typing import Dict, Any, Optional, List
from datetime import datetime


class AnalysisReport:
    """
    Represents comprehensive data analysis results
    
    Attributes:
        data_types: Dictionary mapping column names to detected types
        missing_data: Dictionary with missing data statistics per column
        distributions: Dictionary with distribution statistics per column
        formats: Dictionary with format information per column (date formats, number formats, etc.)
        nested_structures: Dictionary with nested structure information
        completeness_score: Overall completeness score (0.0 to 1.0)
        aggregated_insights: Dictionary with aggregated insights from multiple resamples
        metadata: Additional metadata
        created_at: Timestamp when analysis was performed
    """
    
    def __init__(
        self,
        data_types: Dict[str, str],
        missing_data: Dict[str, Dict[str, Any]],
        distributions: Dict[str, Dict[str, Any]],
        formats: Dict[str, Dict[str, Any]],
        nested_structures: Dict[str, List[str]],
        completeness_score: float,
        aggregated_insights: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None
    ):
        self.data_types = data_types
        self.missing_data = missing_data
        self.distributions = distributions
        self.formats = formats
        self.nested_structures = nested_structures
        self.completeness_score = completeness_score
        self.aggregated_insights = aggregated_insights or {}
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "data_types": self.data_types,
            "missing_data": self.missing_data,
            "distributions": self.distributions,
            "formats": self.formats,
            "nested_structures": self.nested_structures,
            "completeness_score": self.completeness_score,
            "aggregated_insights": self.aggregated_insights,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
