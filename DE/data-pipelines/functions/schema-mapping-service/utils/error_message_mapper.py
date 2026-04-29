"""
Error Message Mapper
Maps technical error messages to user-friendly messages for backend display
"""

import re
from typing import Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


# Error code to user message mapping
ERROR_CODE_MESSAGES: Dict[str, Dict[str, str]] = {
    "INTROSPECTION_FAILED": {
        "user_message": "Unable to analyze the uploaded file. Please ensure your file is not corrupted and try uploading again.",
        "technical_summary": "File introspection failed. The file format could not be determined or the file is corrupted."
    },
    "SCHEMA_DETECTION_FAILED": {
        "user_message": "The file format could not be recognized. Please ensure your file is in CSV, JSON, Parquet, Excel, or TSV format.",
        "technical_summary": "Schema detection failed. The file format could not be determined from the file structure."
    },
    "DATA_SAMPLING_FAILED": {
        "user_message": "Unable to read the uploaded file. Please check that the file is not corrupted and contains valid data.",
        "technical_summary": "Data sampling failed. The file could not be read or parsed correctly."
    },
    "DATA_ANALYSIS_FAILED": {
        "user_message": "Unable to analyze the data in your file. Please ensure the file contains valid data in the expected format.",
        "technical_summary": "Data analysis failed. The file structure or content could not be analyzed."
    },
    "PII_DETECTION_FAILED": {
        "user_message": "Unable to process the file for privacy protection. Please contact support if this issue persists.",
        "technical_summary": "PII detection failed. The system could not identify sensitive information in the file."
    },
    "ANONYMIZATION_FAILED": {
        "user_message": "Unable to process the file for privacy protection. Please contact support if this issue persists.",
        "technical_summary": "Anonymization failed. The system could not anonymize sensitive information in the file."
    },
    "SCHEMA_MAPPING_FAILED": {
        "user_message": "Unable to map your file to the required format. Please ensure your file contains the necessary columns and try again.",
        "technical_summary": "Schema mapping failed. The file columns could not be mapped to the internal schema."
    },
    "STORAGE_ERROR": {
        "user_message": "Unable to access the uploaded file. Please try uploading again or contact support if the issue persists.",
        "technical_summary": "Storage access error. The system could not read or write to the data storage."
    },
    "CONNECTION_ERROR": {
        "user_message": "Unable to connect to the service. Please try again in a few moments or contact support if the issue persists.",
        "technical_summary": "Connection error. The system could not establish a connection to required services."
    },
    "VALIDATION_ERROR": {
        "user_message": "The uploaded file is missing required information. Please check that all required fields are present and try again.",
        "technical_summary": "Validation error. The file or message is missing required fields or contains invalid data."
    },
    "UNKNOWN_ERROR": {
        "user_message": "An unexpected error occurred while processing your file. Please contact support with the upload ID for assistance.",
        "technical_summary": "An unexpected error occurred during processing."
    }
}


def extract_error_code(error_type: str, error_message: str, system_name: str) -> str:
    """
    Extract error code from error type, message, and system name
    
    Args:
        error_type: Python exception type (e.g., "ValueError", "KeyError")
        error_message: Error message string
        system_name: Name of the system that failed (e.g., "System 0: File Introspection")
        
    Returns:
        Error code string
    """
    error_message_lower = error_message.lower()
    error_type_lower = error_type.lower()
    system_name_lower = system_name.lower()
    
    # System-specific error codes
    if "introspection" in system_name_lower or "system 0" in system_name_lower:
        if "format" in error_message_lower or "file format" in error_message_lower:
            return "SCHEMA_DETECTION_FAILED"
        return "INTROSPECTION_FAILED"
    
    if "schema detection" in system_name_lower or "system 1" in system_name_lower:
        return "SCHEMA_DETECTION_FAILED"
    
    if "sampling" in system_name_lower or "system 2" in system_name_lower:
        return "DATA_SAMPLING_FAILED"
    
    if "analysis" in system_name_lower or "system 3" in system_name_lower:
        return "DATA_ANALYSIS_FAILED"
    
    if "anonymiz" in system_name_lower or "pii" in system_name_lower or "system 4" in system_name_lower:
        if "detection" in error_message_lower:
            return "PII_DETECTION_FAILED"
        return "ANONYMIZATION_FAILED"
    
    if "mapping" in system_name_lower or "system 5" in system_name_lower:
        return "SCHEMA_MAPPING_FAILED"
    
    # Error type-based codes
    if "connection" in error_type_lower or "connection" in error_message_lower:
        return "CONNECTION_ERROR"
    
    if "storage" in error_type_lower or "blob" in error_message_lower or "adls" in error_message_lower:
        return "STORAGE_ERROR"
    
    if "validation" in error_type_lower or "keyerror" in error_type_lower or "missing" in error_message_lower:
        return "VALIDATION_ERROR"
    
    return "UNKNOWN_ERROR"


def map_error_to_user_message(
    error_type: str,
    error_message: str,
    system_name: str,
    stack_trace: Optional[str] = None
) -> Tuple[str, str, str]:
    """
    Map technical error to user-friendly message
    
    Args:
        error_type: Python exception type (e.g., "ValueError")
        error_message: Error message string
        system_name: Name of the system that failed
        stack_trace: Optional stack trace
        
    Returns:
        Tuple of (error_code, user_message, technical_summary)
    """
    error_code = extract_error_code(error_type, error_message, system_name)
    
    if error_code in ERROR_CODE_MESSAGES:
        mapping = ERROR_CODE_MESSAGES[error_code]
        return error_code, mapping["user_message"], mapping["technical_summary"]
    
    # Fallback to unknown error
    mapping = ERROR_CODE_MESSAGES["UNKNOWN_ERROR"]
    return "UNKNOWN_ERROR", mapping["user_message"], mapping["technical_summary"]


def get_stage_name(system_name: str) -> str:
    """
    Extract user-friendly stage name from system name
    
    Args:
        system_name: System name (e.g., "System 0: File Introspection")
        
    Returns:
        User-friendly stage name (e.g., "File Introspection")
    """
    # Remove "System X: " prefix
    stage_name = re.sub(r'^System \d+:\s*', '', system_name, flags=re.IGNORECASE)
    
    # Map to user-friendly names
    stage_mapping = {
        "file introspection": "File Upload",
        "schema detection": "Schema Detection",
        "data sampling": "Data Sampling",
        "data analysis": "Data Analysis",
        "dataset anonymizer": "Privacy Protection",
        "pii detection": "Privacy Protection",
        "anonymization": "Privacy Protection",
        "schema mapping": "Schema Mapping"
    }
    
    stage_lower = stage_name.lower()
    for key, value in stage_mapping.items():
        if key in stage_lower:
            return value
    
    return stage_name
