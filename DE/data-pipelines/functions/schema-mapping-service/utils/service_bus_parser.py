"""
Service Bus Message Parser
Parses and validates Service Bus messages for schema mapping pipeline
"""

import re
from typing import Dict, Any, Optional, Tuple
from pathlib import Path


class ServiceBusMessageError(Exception):
    """Exception raised for Service Bus message parsing errors"""
    pass


def normalize_bronze_blob_path_for_datalake(bronze_blob_path: str) -> str:
    """
    Path for FileSystemClient('bronze').get_file_client(path) must be relative to that
    filesystem (no leading container segment).

    training-data-ingestion writes to filesystem 'bronze' at paths like
    ``training/{bank_id}/{date}/{filename}`` and publishes that as bronze_blob_path.
    Older messages and scripts often use a logical prefix ``bronze/training/...``; strip
    ``bronze/`` so the client resolves the same blob as ingestion.
    """
    if not bronze_blob_path or not isinstance(bronze_blob_path, str):
        return bronze_blob_path
    p = bronze_blob_path.strip().replace("\\", "/")
    while p.startswith("bronze/"):
        p = p[len("bronze/") :]
    return p


def align_bronze_blob_path_extension_with_file_format(message: dict, bronze_blob_path: str) -> str:
    """
    Ingestion publishes ``bronze_blob_path`` and ``file_format`` together. If the path suffix
    disagrees with ``file_format`` (wrong extension in the message only), rewrite the suffix
    so downstream reads the same blob the pipeline recorded in Postgres.
    """
    ff = message.get("file_format")
    if not bronze_blob_path or not isinstance(bronze_blob_path, str):
        return bronze_blob_path
    if not ff or not isinstance(ff, str):
        return bronze_blob_path
    fmt = ff.strip().lower().lstrip(".")
    if not fmt:
        return bronze_blob_path
    p = Path(bronze_blob_path.replace("\\", "/"))
    desired = f".{fmt}"
    if p.suffix.lower() == desired:
        return bronze_blob_path
    aligned = str(p.with_suffix(desired))
    return normalize_bronze_blob_path_for_datalake(aligned)


def parse_data_ingested_message(message: dict) -> Dict[str, Any]:
    """
    Parse and validate Service Bus message from 'data-ingested' topic
    
    Expected message structure:
    {
        "training_upload_id": "c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b",
        "bank_id": "bank-digital-001",
        "bronze_blob_path": "bronze/training/bank-digital-001/2026-02-16/c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b.csv",
        "file_format": "csv",  # optional; if present and suffix on bronze_blob_path disagrees, suffix is corrected
        "source_blob_path": "bank-id/raw.json",  # optional metadata; not used to rewrite bronze_blob_path
        ... (other optional fields)
    }
    
    Args:
        message: Service Bus message dictionary (JSON parsed)
        
    Returns:
        Dict with parsed and validated fields:
        {
            "training_upload_id": str,
            "upload_id": str,  # Alias for training_upload_id (for backward compatibility)
            "bank_id": str,
            "bronze_blob_path": str,
            "date": str,  # Extracted from path (YYYY-MM-DD)
            "file_format": str,  # Extracted from path extension
            "original_message": dict  # Full original message for reference
        }
        
    Raises:
        ServiceBusMessageError: If required fields are missing or invalid
    """
    # Validate message structure
    is_valid, error_msg = validate_message_structure(message)
    if not is_valid:
        raise ServiceBusMessageError(f"Invalid message structure: {error_msg}")
    
    # Extract required fields (support both training_upload_id and upload_id for backward compatibility)
    # Trim whitespace from string fields
    training_upload_id = (message.get('training_upload_id') or message.get('upload_id'))
    if training_upload_id and isinstance(training_upload_id, str):
        training_upload_id = training_upload_id.strip()
    bank_id = message.get('bank_id')
    if bank_id and isinstance(bank_id, str):
        bank_id = bank_id.strip()
    bronze_blob_path = message.get('bronze_blob_path')
    if bronze_blob_path and isinstance(bronze_blob_path, str):
        bronze_blob_path = bronze_blob_path.strip()
    bronze_blob_path = normalize_bronze_blob_path_for_datalake(bronze_blob_path)
    bronze_blob_path = align_bronze_blob_path_extension_with_file_format(message, bronze_blob_path)

    # Extract date from bronze_blob_path
    # Pattern: training/{bank_id}/{date}/{filename}.{ext}
    date = extract_date_from_bronze_path(bronze_blob_path)
    if not date:
        raise ServiceBusMessageError(
            f"Could not extract date from bronze_blob_path: {bronze_blob_path}. "
            f"Expected pattern: training/{{bank_id}}/{{date}}/{{filename}}.{{ext}} "
            f"(optional legacy prefix bronze/ is stripped before lookup)"
        )
    
    # Extract file format from path extension
    file_format = None
    try:
        path_obj = Path(bronze_blob_path)
        file_format = path_obj.suffix.lstrip('.').lower() if path_obj.suffix else None
    except Exception:
        pass  # Will be None if extraction fails
    
    # Build parsed result
    parsed = {
        'training_upload_id': training_upload_id,
        'upload_id': training_upload_id,  # Alias for backward compatibility
        'bank_id': bank_id,
        'bronze_blob_path': bronze_blob_path,
        'date': date,
        'file_format': file_format,  # Optional hint, will be detected by Schema Detection
        'original_message': message  # Keep full message for reference
    }
    
    # Add optional fields if present (for reference, not required)
    optional_fields = [
        'run_id',  # orchestrator handoff / silver paths (data-ingested messages include this)
        'source_blob_path',
        'row_count',
        'column_count',
        'ingestion_timestamp',
        'status',
    ]
    
    for field in optional_fields:
        if field in message:
            parsed[field] = message[field]
    
    return parsed


def extract_date_from_bronze_path(bronze_blob_path: str) -> Optional[str]:
    """
    Extract date from bronze_blob_path
    
    Pattern: bronze/training/{bank_id}/{date}/{upload_id}.{ext}
    Date format: YYYY-MM-DD
    
    Args:
        bronze_blob_path: Path like "bronze/training/bank-digital-001/2026-02-16/upload-id.csv"
        
    Returns:
        Date string in YYYY-MM-DD format, or None if not found
    """
    if not bronze_blob_path:
        return None

    path = normalize_bronze_blob_path_for_datalake(bronze_blob_path)

    # Pattern: training/{bank_id}/{date}/{filename}.{ext}
    # Match: training/anything/YYYY-MM-DD/anything
    pattern = r"training/[^/]+/(\d{4}-\d{2}-\d{2})/"
    match = re.search(pattern, path)
    
    if match:
        date_str = match.group(1)
        # Validate date format (basic check)
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str
    
    # Fallback: Try splitting by '/' and finding date-like pattern
    parts = path.split("/")
    for part in parts:
        if re.match(r'^\d{4}-\d{2}-\d{2}$', part):
            return part
    
    return None


def validate_message_structure(message: dict) -> Tuple[bool, Optional[str]]:
    """
    Validate that Service Bus message has required fields
    
    Args:
        message: Service Bus message dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if message is valid, False otherwise
        - error_message: Error description if invalid, None if valid
    """
    if not isinstance(message, dict):
        return False, "Message must be a dictionary/JSON object"
    
    # Required fields (training_upload_id is primary, upload_id is accepted for backward compatibility)
    required_fields = ['bank_id', 'bronze_blob_path']
    
    # Check for training_upload_id or upload_id
    if 'training_upload_id' not in message and 'upload_id' not in message:
        return False, "Missing required field: training_upload_id (or upload_id for backward compatibility)"
    
    for field in required_fields:
        if field not in message:
            return False, f"Missing required field: {field}"
        
        if not message[field] or not isinstance(message[field], str):
            return False, f"Field '{field}' must be a non-empty string"
        
        # Trim whitespace
        message[field] = message[field].strip()
        if not message[field]:
            return False, f"Field '{field}' cannot be empty or whitespace only"
    
    # Validate bronze_blob_path format (filesystem-relative under container bronze, or legacy bronze/training/...)
    bronze_path = message["bronze_blob_path"]
    normalized = normalize_bronze_blob_path_for_datalake(bronze_path)
    if not normalized.startswith("training/"):
        return (
            False,
            "bronze_blob_path must be under training/ in the bronze filesystem "
            "(e.g. training/{bank_id}/{date}/{filename}.json), or use legacy prefix bronze/training/.... "
            f"Got: {bronze_path}",
        )
    
    # Validate training_upload_id/upload_id format (should be UUID-like, but we'll be lenient)
    training_upload_id = message.get('training_upload_id') or message.get('upload_id')
    if not training_upload_id or len(training_upload_id) < 10:  # Basic length check
        return False, f"training_upload_id appears to be invalid (too short or missing): {training_upload_id}"
    
    return True, None


def build_bronze_path(bank_id: str, date: str, upload_id: str, file_format: Optional[str] = None) -> str:
    """
    Build bronze_blob_path from components (helper function)
    
    Args:
        bank_id: Bank identifier
        date: Date in YYYY-MM-DD format
        upload_id: Upload identifier
        file_format: Optional file format/extension (without dot)
        
    Returns:
        Bronze blob path: bronze/training/{bank_id}/{date}/{upload_id}.{ext}
    """
    if file_format:
        return f"bronze/training/{bank_id}/{date}/{upload_id}.{file_format}"
    else:
        return f"bronze/training/{bank_id}/{date}/{upload_id}"


def extract_file_info_from_path(bronze_blob_path: str) -> Dict[str, Optional[str]]:
    """
    Extract file information from bronze_blob_path
    
    Args:
        bronze_blob_path: Path like "bronze/training/bank-digital-001/2026-02-16/upload-id.csv"
        
    Returns:
        Dict with:
        {
            "bank_id": str or None,
            "date": str or None,
            "upload_id": str or None,
            "file_format": str or None
        }
    """
    result = {
        'bank_id': None,
        'date': None,
        'upload_id': None,
        'file_format': None
    }
    
    if not bronze_blob_path:
        return result

    path = normalize_bronze_blob_path_for_datalake(bronze_blob_path)
    # Pattern: training/{bank_id}/{date}/{filename}.{ext}
    pattern = r"training/([^/]+)/(\d{4}-\d{2}-\d{2})/([^/]+?)(?:\.([^/]+))?$"
    match = re.search(pattern, path)
    
    if match:
        result['bank_id'] = match.group(1)
        result['date'] = match.group(2)
        result['upload_id'] = match.group(3)
        
        # Extract file format (extension without dot)
        if match.group(4):
            result['file_format'] = match.group(4)
        else:
            result['file_format'] = ""
    
    return result
