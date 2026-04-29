"""
Format-specific detectors for schema detection
"""

# Import base class
from .base import BaseFormatDetector

# Import detector classes
from .csv_detector import CSVDetector
from .json_detector import JSONDetector
from .tsv_detector import TSVDetector
from .parquet_detector import ParquetDetector
from .excel_detector import ExcelDetector

# Import wrapper functions for backward compatibility
from .csv_detector import detect_csv_structure
from .json_detector import detect_json_structure
from .tsv_detector import detect_tsv_structure
from .parquet_detector import detect_parquet_structure
from .excel_detector import detect_excel_structure

# Import common utilities
from .common import (
    read_file_sample,
    read_multi_location_samples,
    decode_text,
    estimate_row_count_from_samples,
    infer_column_types_from_samples,
    collect_evidence
)

__all__ = [
    # Base class
    'BaseFormatDetector',
    # Detector classes
    'CSVDetector',
    'JSONDetector',
    'TSVDetector',
    'ParquetDetector',
    'ExcelDetector',
    # Wrapper functions (backward compatibility)
    'detect_csv_structure',
    'detect_json_structure',
    'detect_tsv_structure',
    'detect_parquet_structure',
    'detect_excel_structure',
    # Common utilities
    'read_file_sample',
    'read_multi_location_samples',
    'decode_text',
    'estimate_row_count_from_samples',
    'infer_column_types_from_samples',
    'collect_evidence',
]
