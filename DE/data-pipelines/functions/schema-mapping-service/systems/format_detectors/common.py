"""
Common utilities for format detectors
Shared I/O, encoding, type inference, and analysis functions
"""

from typing import Dict, Any, Optional, Tuple, List
import io

try:
    from system_interfaces import FileIntrospectionResult
except ImportError:
    from ..system_interfaces import FileIntrospectionResult


def read_file_sample(
    file_path: str,
    datalake_client,
    blob_client=None,
    sample_size: int = 65536,
    offset: int = 0
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Read sample data from file (Data Lake or Blob Storage)
    
    Args:
        file_path: Path to file in Data Lake
        datalake_client: Azure Data Lake Gen2 client
        blob_client: Optional Azure Blob Storage client for fallback
        sample_size: Size of sample to read in bytes
        offset: Byte offset to start reading from
        
    Returns:
        Tuple of (sample_data, error)
        - sample_data: Optional[bytes] - Sample data or None if error
        - error: Optional[str] - Error message if reading failed
    """
    try:
        # Try Data Lake client first
        file_client = datalake_client.get_file_client(file_path)
        file_properties = file_client.get_file_properties()
        file_size = file_properties.size
        
        # Validate offset
        if offset >= file_size:
            return None, f"Offset {offset} is beyond file size {file_size}"
        
        # Calculate read size
        read_size = min(sample_size, file_size - offset)
        if read_size <= 0:
            return None, f"Cannot read {sample_size} bytes from offset {offset} (file size: {file_size})"
        
        sample_data = file_client.download_file(offset=offset, length=read_size).readall()
        return sample_data, None
        
    except Exception as dl_error:
        # Fallback to Blob client
        if blob_client:
            try:
                # Parse container and blob path
                parts = file_path.split('/', 1)
                if len(parts) == 2:
                    container_name, blob_path = parts
                else:
                    container_name = None
                    blob_path = file_path
                
                blob_client_instance = blob_client.get_blob_client(
                    container=container_name,
                    blob=blob_path
                )
                sample_data = blob_client_instance.download_blob(
                    offset=offset, length=sample_size
                ).readall()
                return sample_data, None
            except Exception as blob_error:
                return None, f"Failed to read sample (Data Lake: {str(dl_error)}, Blob: {str(blob_error)})"
        else:
            return None, f"Failed to read sample: {str(dl_error)}"


def read_multi_location_samples(
    file_path: str,
    datalake_client,
    blob_client=None,
    sample_size: int = 65536
) -> Tuple[Optional[Dict[str, bytes]], Optional[str]]:
    """
    Read samples from multiple locations (beginning, middle, end)
    
    Args:
        file_path: Path to file in Data Lake
        datalake_client: Azure Data Lake Gen2 client
        blob_client: Optional Azure Blob Storage client for fallback
        sample_size: Size of sample to read from each location
        
    Returns:
        Tuple of (samples_dict, error)
        - samples_dict: Dict with keys 'beginning', 'middle', 'end'
        - error: Optional[str] - Error message if reading failed
    """
    try:
        # Get file size first
        file_client = datalake_client.get_file_client(file_path)
        file_properties = file_client.get_file_properties()
        file_size = file_properties.size
    except Exception as e:
        # Fallback to blob client for file size
        if blob_client:
            try:
                parts = file_path.split('/', 1)
                if len(parts) == 2:
                    container_name, blob_path = parts
                else:
                    container_name = None
                    blob_path = file_path
                blob_client_instance = blob_client.get_blob_client(
                    container=container_name,
                    blob=blob_path
                )
                blob_properties = blob_client_instance.get_blob_properties()
                file_size = blob_properties.size
            except Exception:
                return None, f"Failed to get file size: {str(e)}"
        else:
            return None, f"Failed to get file size: {str(e)}"
    
    samples = {}
    
    # Beginning sample (always read)
    beg_data, beg_error = read_file_sample(
        file_path, datalake_client, blob_client, sample_size, offset=0
    )
    if beg_error:
        return None, f"Failed to read beginning sample: {beg_error}"
    samples['beginning'] = beg_data
    
    # Middle sample (if file is large enough)
    if file_size > sample_size * 2:
        mid_offset = (file_size - sample_size) // 2
        mid_data, mid_error = read_file_sample(
            file_path, datalake_client, blob_client, sample_size, offset=mid_offset
        )
        if mid_error:
            # Use beginning sample if middle fails
            samples['middle'] = beg_data
        else:
            samples['middle'] = mid_data
    else:
        # File too small, use beginning sample
        samples['middle'] = beg_data
    
    # End sample (if file is large enough)
    if file_size > sample_size:
        end_offset = max(0, file_size - sample_size)
        end_data, end_error = read_file_sample(
            file_path, datalake_client, blob_client, sample_size, offset=end_offset
        )
        if end_error:
            # Use beginning sample if end fails
            samples['end'] = beg_data
        else:
            samples['end'] = end_data
    else:
        # File too small, use beginning sample
        samples['end'] = beg_data
    
    return samples, None


def decode_text(
    data: bytes,
    encoding: Optional[str] = None,
    introspection_result: Optional[FileIntrospectionResult] = None
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Decode bytes to text with fallback handling
    
    Args:
        data: Bytes to decode
        encoding: Encoding to use (if None, uses introspection_result or defaults to utf-8)
        introspection_result: Result from File Introspection System
        
    Returns:
        Tuple of (text, encoding_used, error)
        - text: Optional[str] - Decoded text or None if error
        - encoding_used: Optional[str] - Encoding that was used
        - error: Optional[str] - Error message if decoding failed
    """
    # Determine encoding
    if encoding is None:
        if introspection_result and introspection_result.encoding:
            encoding = introspection_result.encoding
        else:
            encoding = 'utf-8'
    
    # Try primary encoding
    try:
        text = data.decode(encoding)
        return text, encoding, None
    except UnicodeDecodeError as e:
        # Fallback to UTF-8 with error replacement
        try:
            text = data.decode('utf-8', errors='replace')
            return text, 'utf-8', f"Fell back to UTF-8 (original encoding '{encoding}' failed: {str(e)})"
        except Exception as fallback_error:
            return None, None, f"Failed to decode text with '{encoding}' and UTF-8 fallback: {str(fallback_error)}"
    except Exception as e:
        return None, None, f"Failed to decode text: {str(e)}"


def estimate_row_count_from_samples(
    samples: Dict[str, bytes],
    file_size: int,
    format: str
) -> Tuple[int, List[str]]:
    """
    Estimate row count from multiple samples
    
    Args:
        samples: Dict of samples from different locations (keys: 'beginning', 'middle', 'end')
        file_size: Total file size in bytes
        format: File format (for format-specific estimation)
        
    Returns:
        Tuple of (row_count, evidence)
        - row_count: int - Estimated row count
        - evidence: List[str] - Evidence for the estimation
    """
    evidence = []
    total_newlines = 0
    total_sample_size = 0
    
    # Count newlines in each sample
    for location, sample_data in samples.items():
        newlines = sample_data.count(b'\n')
        total_newlines += newlines
        total_sample_size += len(sample_data)
        evidence.append(f"{location.capitalize()} sample: {newlines} newlines in {len(sample_data)} bytes")
    
    # Estimate based on sample ratio
    if total_sample_size > 0 and file_size > 0:
        sample_ratio = total_sample_size / file_size
        if sample_ratio > 0:
            estimated_rows = int(total_newlines / sample_ratio)
            evidence.append(
                f"Estimated {estimated_rows} rows based on {sample_ratio:.2%} sample coverage "
                f"({total_newlines} newlines across {len(samples)} samples)"
            )
        else:
            estimated_rows = total_newlines
            evidence.append(f"Estimated {estimated_rows} rows (simple count, sample_ratio too small)")
    else:
        estimated_rows = total_newlines
        evidence.append(f"Estimated {estimated_rows} rows (simple count, no file size available)")
    
    return estimated_rows, evidence


def infer_column_types_from_samples(
    sample_rows: List[Dict[str, Any]],
    format: str
) -> Tuple[Dict[str, str], List[str]]:
    """
    Infer column types from sample rows using hybrid approach (Python types)
    
    Args:
        sample_rows: List of sample row dictionaries
        format: File format (for format-specific inference)
        
    Returns:
        Tuple of (column_types, evidence)
        - column_types: Dict mapping column names to Python type names
        - evidence: List[str] - Evidence for type inference
    """
    evidence = []
    column_types = {}
    
    if not sample_rows:
        evidence.append("No sample rows available for type inference")
        return column_types, evidence
    
    # Get all column names from first row
    first_row = sample_rows[0]
    column_names = list(first_row.keys())
    evidence.append(f"Inferring types for {len(column_names)} columns from {len(sample_rows)} sample rows")
    
    # Infer type for each column
    for col_name in column_names:
        # Collect non-null values for this column
        sample_values = [
            row.get(col_name) for row in sample_rows
            if col_name in row and row[col_name] is not None
        ]
        
        if not sample_values:
            # All null values - can't infer type
            column_types[col_name] = 'NoneType'
            evidence.append(f"Column '{col_name}': all null values, type set to NoneType")
            continue
        
        # Determine type from first non-null value
        first_value = sample_values[0]
        first_type = type(first_value).__name__
        
        # Check if all values are same type
        all_same_type = all(type(v).__name__ == first_type for v in sample_values)
        
        if all_same_type:
            column_types[col_name] = first_type
            evidence.append(
                f"Column '{col_name}': type '{first_type}' inferred from {len(sample_values)} values "
                f"(all same type)"
            )
        else:
            # Mixed types - use most common type or first type
            type_counts = {}
            for v in sample_values:
                t = type(v).__name__
                type_counts[t] = type_counts.get(t, 0) + 1
            
            most_common_type = max(type_counts.items(), key=lambda x: x[1])[0]
            column_types[col_name] = most_common_type
            evidence.append(
                f"Column '{col_name}': type '{most_common_type}' inferred from {len(sample_values)} values "
                f"(mixed types: {dict(type_counts)})"
            )
    
    return column_types, evidence


def collect_evidence(
    message: str,
    line_number: Optional[int] = None,
    row_number: Optional[int] = None,
    byte_offset: Optional[int] = None,
    additional_info: Optional[Dict[str, Any]] = None
) -> str:
    """
    Format evidence message with location information
    
    Args:
        message: Evidence message
        line_number: Line number (for text formats)
        row_number: Row number (for binary formats or structured data)
        byte_offset: Byte offset (for binary formats)
        additional_info: Additional information to include
        
    Returns:
        Formatted evidence string
    """
    parts = [message]
    
    location_parts = []
    if line_number is not None:
        location_parts.append(f"line {line_number}")
    if row_number is not None:
        location_parts.append(f"row {row_number}")
    if byte_offset is not None:
        location_parts.append(f"offset {byte_offset}")
    
    if location_parts:
        parts.append(f"({', '.join(location_parts)})")
    
    if additional_info:
        info_str = ", ".join(f"{k}={v}" for k, v in additional_info.items())
        parts.append(f"[{info_str}]")
    
    return " ".join(parts)
