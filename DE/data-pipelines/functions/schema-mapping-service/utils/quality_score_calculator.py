"""
Quality Score Calculator
Utility functions for calculating overall data quality scores from per-column metrics
"""

from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


def calculate_average_completeness(
    missing_data: Dict[str, Dict[str, Any]]
) -> float:
    """
    Calculate overall completeness score as simple average of all column completeness percentages
    
    Args:
        missing_data: Dictionary mapping column_name -> {completeness_pct, null_count, total_rows, ...}
        
    Returns:
        Overall completeness score (0.0-1.0)
    """
    if not missing_data:
        return 0.0
    
    completeness_values = [
        stats.get('completeness_pct', 0.0) 
        for stats in missing_data.values()
        if isinstance(stats, dict) and 'completeness_pct' in stats
    ]
    
    if not completeness_values:
        return 0.0
    
    average_pct = sum(completeness_values) / len(completeness_values)
    # Convert from percentage (0-100) to score (0.0-1.0)
    return round(average_pct / 100.0, 4)


def calculate_weighted_completeness(
    missing_data: Dict[str, Dict[str, Any]],
    column_weights: Optional[Dict[str, float]] = None,
    critical_columns: Optional[List[str]] = None,
    critical_weight: float = 2.0
) -> float:
    """
    Calculate overall completeness score as weighted average
    
    Args:
        missing_data: Dictionary mapping column_name -> {completeness_pct, null_count, total_rows, ...}
        column_weights: Optional custom weights per column (default: 1.0 for all)
        critical_columns: Optional list of critical column names (weighted higher)
        critical_weight: Weight multiplier for critical columns (default: 2.0)
        
    Returns:
        Overall completeness score (0.0-1.0)
    """
    if not missing_data:
        return 0.0
    
    # Default weights
    if column_weights is None:
        column_weights = {}
    
    if critical_columns is None:
        critical_columns = []
    
    total_weighted_completeness = 0.0
    total_weight = 0.0
    
    for col_name, stats in missing_data.items():
        if not isinstance(stats, dict) or 'completeness_pct' not in stats:
            continue
        
        completeness_pct = stats.get('completeness_pct', 0.0)
        
        # Determine weight
        if col_name in column_weights:
            weight = column_weights[col_name]
        elif col_name in critical_columns:
            weight = critical_weight
        else:
            weight = 1.0
        
        total_weighted_completeness += (completeness_pct / 100.0) * weight
        total_weight += weight
    
    if total_weight == 0.0:
        return 0.0
    
    return round(total_weighted_completeness / total_weight, 4)


def calculate_minimum_completeness(
    missing_data: Dict[str, Dict[str, Any]]
) -> float:
    """
    Calculate overall completeness score as minimum of all column completeness percentages
    (Most conservative approach - one bad column brings down the entire score)
    
    Args:
        missing_data: Dictionary mapping column_name -> {completeness_pct, null_count, total_rows, ...}
        
    Returns:
        Overall completeness score (0.0-1.0)
    """
    if not missing_data:
        return 0.0
    
    completeness_values = [
        stats.get('completeness_pct', 0.0) 
        for stats in missing_data.values()
        if isinstance(stats, dict) and 'completeness_pct' in stats
    ]
    
    if not completeness_values:
        return 0.0
    
    min_pct = min(completeness_values)
    # Convert from percentage (0-100) to score (0.0-1.0)
    return round(min_pct / 100.0, 4)


def calculate_overall_quality_score(
    missing_data: Dict[str, Dict[str, Any]],
    method: str = "weighted",
    column_weights: Optional[Dict[str, float]] = None,
    critical_columns: Optional[List[str]] = None,
    critical_weight: float = 2.0
) -> float:
    """
    Calculate overall quality score using specified method
    
    Args:
        missing_data: Dictionary mapping column_name -> {completeness_pct, null_count, total_rows, ...}
        method: Calculation method ("average", "weighted", "minimum")
        column_weights: Optional custom weights per column (for weighted method)
        critical_columns: Optional list of critical column names (for weighted method)
        critical_weight: Weight multiplier for critical columns (for weighted method)
        
    Returns:
        Overall quality score (0.0-1.0)
    """
    method = method.lower()
    
    if method == "average":
        return calculate_average_completeness(missing_data)
    elif method == "weighted":
        return calculate_weighted_completeness(
            missing_data, 
            column_weights, 
            critical_columns, 
            critical_weight
        )
    elif method == "minimum":
        return calculate_minimum_completeness(missing_data)
    else:
        logger.warning(f"Unknown method '{method}', defaulting to 'average'")
        return calculate_average_completeness(missing_data)
