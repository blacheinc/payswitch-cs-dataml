"""
Quality Report Aggregator
Aggregates quality information from Systems 0-4 into a comprehensive quality report
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import logging

try:
    from .quality_score_calculator import calculate_overall_quality_score
except ImportError:
    from utils.quality_score_calculator import calculate_overall_quality_score

logger = logging.getLogger(__name__)


def aggregate_quality_report(
    introspection_result: Optional[Dict[str, Any]] = None,
    schema_result: Optional[Dict[str, Any]] = None,
    sampling_result: Optional[Dict[str, Any]] = None,
    analysis_result: Optional[Dict[str, Any]] = None,
    pii_result: Optional[Dict[str, Any]] = None,
    quality_score_method: str = "weighted",
    critical_columns: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Aggregate quality information from Systems 0-4 into comprehensive quality report
    
    Args:
        introspection_result: System 0 result (FileIntrospectionResult)
        schema_result: System 1 result (SchemaDetectionResult)
        sampling_result: System 2 result (DataSamplingResult)
        analysis_result: System 3 result (DataAnalysisResult)
        pii_result: System 4 result (PIIDetectionResult)
        quality_score_method: Method for calculating quality score ("average", "weighted", "minimum")
        critical_columns: Optional list of critical column names for weighted scoring
        
    Returns:
        Comprehensive quality report dictionary
    """
    quality_report = {
        "file_quality": {},
        "schema_quality": {},
        "data_quality": {},
        "pii_quality": {},
        "quality_score": 0.0,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # System 0: File Quality
    if introspection_result:
        quality_report["file_quality"] = {
            "file_size_bytes": introspection_result.get("file_size_bytes"),
            "encoding": introspection_result.get("encoding"),
            "compression_type": introspection_result.get("compression_type"),
            "has_bom": introspection_result.get("has_bom", False)
        }
    
    # System 1: Schema Quality
    if schema_result:
        # schema_result may be a dict produced from Pydantic model_dump().
        # Some optional fields may be present but set to None; guard against len(None).
        columns = schema_result.get("columns") if isinstance(schema_result, dict) else None
        if columns is None:
            # Fall back to column_names if present, else empty list
            columns = schema_result.get("column_names") if isinstance(schema_result, dict) else None
        if columns is None:
            columns = []

        column_types = schema_result.get("column_types") if isinstance(schema_result, dict) else None
        if column_types is None:
            column_types = {}

        quality_report["schema_quality"] = {
            "format": schema_result.get("format"),
            "format_detection_confidence": schema_result.get("confidence_scores", {}).get("format_confidence", 0.0),
            "column_count": len(columns) if isinstance(columns, list) else 0,
            "column_names_detected": len(columns) if isinstance(columns, list) else 0,
            "data_types_detected": len(column_types) if isinstance(column_types, dict) else 0,
        }
    
    # System 2: Sampling Quality (metadata)
    if sampling_result:
        metadata = sampling_result.get("metadata", {}) if isinstance(sampling_result, dict) else getattr(sampling_result, "metadata", {})
        samples = sampling_result.get("samples", []) if isinstance(sampling_result, dict) else getattr(sampling_result, "samples", [])
        quality_report["file_quality"].update({
            "row_count": metadata.get("row_count") if isinstance(metadata, dict) else getattr(metadata, "row_count", None),
            "sample_count": len(samples) if samples else 0
        })
    
    # System 3: Data Quality
    if analysis_result:
        missing_data = analysis_result.get("missing_data", {})
        
        # Calculate overall completeness score
        overall_completeness = calculate_overall_quality_score(
            missing_data=missing_data,
            method=quality_score_method,
            critical_columns=critical_columns
        )
        
        # Per-column completeness
        column_completeness = {
            col: stats.get("completeness_pct", 0.0)
            for col, stats in missing_data.items()
            if isinstance(stats, dict)
        }
        
        # Identify columns with outliers
        distributions = analysis_result.get("distributions", {})
        columns_with_outliers = [
            col for col, dist in distributions.items()
            if isinstance(dist, dict) and dist.get("outliers", [])
        ]
        
        # Identify columns with format issues
        formats = analysis_result.get("formats", {})
        columns_with_format_issues = [
            col for col, fmt in formats.items()
            if isinstance(fmt, dict) and fmt.get("pattern") == "unknown"
        ]
        
        # Data type consistency check
        data_types = analysis_result.get("data_types", {})
        data_type_consistency = "consistent" if data_types else "unknown"
        
        quality_report["data_quality"] = {
            "overall_completeness_score": overall_completeness,
            "column_completeness": column_completeness,
            "columns_with_outliers": columns_with_outliers,
            "columns_with_format_issues": columns_with_format_issues,
            "data_type_consistency": data_type_consistency,
            "total_columns": len(missing_data)
        }
    
    # System 4: PII Quality
    if pii_result:
        pii_fields = []
        if isinstance(pii_result, dict):
            pii_fields.extend(pii_result.get("names", []))
            pii_fields.extend(pii_result.get("emails", []))
            pii_fields.extend(pii_result.get("phones", []))
            pii_fields.extend(pii_result.get("ids", []))
        elif hasattr(pii_result, "names"):
            # PIIDetectionResult object
            pii_fields.extend(pii_result.names)
            pii_fields.extend(pii_result.emails)
            pii_fields.extend(pii_result.phones)
            pii_fields.extend(pii_result.ids)
        
        quality_report["pii_quality"] = {
            "pii_fields_detected": len(set(pii_fields)),
            "anonymization_applied": len(pii_fields) > 0,
            "pii_detection_confidence": pii_result.get("confidence", 0.0) if isinstance(pii_result, dict) else getattr(pii_result, "confidence", 0.0)
        }
    
    # Calculate overall quality score
    # Weighted combination of different quality aspects
    scores = []
    weights = []
    
    # Schema quality (20%)
    if quality_report["schema_quality"].get("format_detection_confidence"):
        scores.append(quality_report["schema_quality"]["format_detection_confidence"])
        weights.append(0.2)
    
    # Data completeness (50%)
    if quality_report["data_quality"].get("overall_completeness_score"):
        scores.append(quality_report["data_quality"]["overall_completeness_score"])
        weights.append(0.5)
    
    # PII handling (20%)
    if quality_report["pii_quality"].get("pii_detection_confidence"):
        scores.append(quality_report["pii_quality"]["pii_detection_confidence"])
        weights.append(0.2)
    
    # File quality (10%) - simple check if file was readable
    if quality_report["file_quality"].get("encoding"):
        scores.append(1.0)  # File was readable
        weights.append(0.1)
    
    # Calculate weighted average
    if scores and weights:
        total_weight = sum(weights)
        if total_weight > 0:
            quality_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
            quality_report["quality_score"] = round(quality_score, 4)
    
    return quality_report
