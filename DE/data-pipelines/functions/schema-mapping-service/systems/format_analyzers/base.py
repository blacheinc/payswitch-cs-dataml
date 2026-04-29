"""
Base Analyzer for Format-Specific Analysis
Abstract base class for format-specific data analyzers
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import pandas as pd


class BaseDataAnalyzer(ABC):
    """
    Abstract base class for format-specific data analyzers
    
    All format-specific analyzers must implement:
    - analyze_format_specific(): Format-specific analysis
    - get_format_name(): Return format name (e.g., "csv", "json")
    """
    
    @abstractmethod
    def analyze_format_specific(
        self,
        df: pd.DataFrame,
        schema_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform format-specific analysis
        
        Args:
            df: DataFrame to analyze
            schema_result: Optional schema detection result for context
            
        Returns:
            Dict with format-specific analysis results
        """
        pass
    
    @abstractmethod
    def get_format_name(self) -> str:
        """
        Get format name (e.g., "csv", "json", "parquet")
        
        Returns:
            Format name string
        """
        pass
    
    def analyze_common(
        self,
        df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Common analysis that applies to all formats
        
        Args:
            df: DataFrame to analyze
            
        Returns:
            Dict with common analysis results
        """
        return {
            "row_count": len(df),
            "column_count": len(df.columns),
            "column_names": list(df.columns),
            "memory_usage_bytes": df.memory_usage(deep=True).sum()
        }
