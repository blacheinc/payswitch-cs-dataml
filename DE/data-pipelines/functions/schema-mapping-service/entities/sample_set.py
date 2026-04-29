"""
SampleSet entity class
Represents a set of data samples
"""

from typing import List, Dict, Any, Optional
import pandas as pd
from datetime import datetime


class SampleSet:
    """
    Represents a set of data samples for analysis
    
    Attributes:
        samples: List of DataFrames (resampled data)
        total_row_count: Total number of rows in original dataset
        column_count: Number of columns
        sampling_strategy: Strategy used for sampling ("full_dataset", "reservoir", "stratified")
        format: File format
        encoding: File encoding
        metadata: Additional metadata
        created_at: Timestamp when samples were created
    """
    
    def __init__(
        self,
        samples: List[pd.DataFrame],
        total_row_count: int,
        column_count: int,
        sampling_strategy: str,
        format: str,
        encoding: str,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None
    ):
        self.samples = samples
        self.total_row_count = total_row_count
        self.column_count = column_count
        self.sampling_strategy = sampling_strategy
        self.format = format
        self.encoding = encoding
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.utcnow()
    
    @property
    def sample_count(self) -> int:
        """Get number of samples"""
        return len(self.samples)
    
    @property
    def is_full_dataset(self) -> bool:
        """Check if using full dataset (no resampling)"""
        return self.sampling_strategy == "full_dataset"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excludes DataFrames)"""
        return {
            "sample_count": self.sample_count,
            "total_row_count": self.total_row_count,
            "column_count": self.column_count,
            "sampling_strategy": self.sampling_strategy,
            "format": self.format,
            "encoding": self.encoding,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
