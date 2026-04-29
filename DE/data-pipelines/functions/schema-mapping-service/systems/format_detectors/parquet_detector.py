"""
Parquet format detector
Detects Parquet structure: schema, columns, types, partitions
"""

import io
from typing import Dict, Any, Optional, Tuple, List

try:
    import pyarrow.parquet as pq
    import pyarrow as pa
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

try:
    from system_interfaces import FileIntrospectionResult
except ImportError:
    from ..system_interfaces import FileIntrospectionResult

from .base import BaseFormatDetector
from .common import collect_evidence


class ParquetDetector(BaseFormatDetector):
    """
    Parquet format detector
    Detects Parquet structure using PyArrow metadata reading
    """
    
    def detect_format_signature(
        self,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[bool, float, List[str]]:
        """
        Detect if data matches Parquet format
        
        Args:
            sample_data: Sample bytes from file
            introspection_result: Result from File Introspection System
            
        Returns:
            Tuple of (is_match, confidence, evidence)
        """
        evidence = []
        confidence = 0.0
        
        # Check format hints from introspection
        if introspection_result and introspection_result.format_hints:
            if introspection_result.format_hints.get('possible_parquet'):
                confidence += 0.3
                evidence.append("Parquet format hints detected in introspection")
        
        # Check for Parquet magic bytes (PAR1)
        if sample_data.startswith(b'PAR1'):
            confidence += 0.7
            evidence.append(collect_evidence(
                "Parquet magic bytes (PAR1) detected",
                byte_offset=0,
                additional_info={'magic_bytes': 'PAR1'}
            ))
        
        # Check file extension (if available in introspection_result or as attribute)
        file_path = None
        if introspection_result:
            # Try to get file_path from introspection_result
            if hasattr(introspection_result, 'file_path'):
                file_path = introspection_result.file_path
            elif hasattr(introspection_result, '__dict__') and 'file_path' in introspection_result.__dict__:
                file_path = introspection_result.__dict__.get('file_path')
        
        if file_path and file_path.lower().endswith('.parquet'):
            confidence += 0.2
            evidence.append("File extension is .parquet")
        
        is_match = confidence >= 0.5
        return is_match, min(confidence, 1.0), evidence
    
    def parse_structure(
        self,
        file_path: str,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse Parquet structure
        
        Args:
            file_path: Path to Parquet file in Data Lake
            sample_data: Sample bytes from file (should contain metadata)
            introspection_result: Result from File Introspection System
            
        Returns:
            Tuple of (structure_info, error)
        """
        evidence = []
        metadata = {}
        
        if not PARQUET_AVAILABLE:
            error = "PyArrow not available, cannot parse Parquet structure"
            evidence.append(collect_evidence(error))
            return {}, error
        
        # Read Parquet metadata (first 1MB should be enough for schema)
        sample_size = 1048576  # 1MB
        
        try:
            # If sample_data is provided and sufficient, use it; otherwise read from file
            if len(sample_data) < 1024:  # If sample_data is too small, read from file
                sample_data, read_error = self.read_file_sample(file_path, sample_size=sample_size, offset=0)
                if read_error:
                    return {
                        'encoding': 'binary',
                        'delimiter': None,
                        'has_header': False,
                        'column_count': 0,
                        'row_count': 0,
                        'nested_structure': False,
                        'sheets': None,
                        'column_names': None,
                        'column_types': {},
                        'evidence': evidence,
                        'metadata': metadata
                    }, f"Failed to read Parquet file: {read_error}"
            
            # Write to BytesIO for PyArrow
            parquet_file = io.BytesIO(sample_data)
            
            # Read Parquet metadata
            try:
                parquet_file.seek(0)
                parquet_metadata = pq.read_metadata(parquet_file)
            except Exception as e:
                # Check if file is corrupted
                error = f"Failed to read Parquet metadata (possible corruption): {str(e)}"
                evidence.append(collect_evidence(
                    error,
                    additional_info={'error_type': type(e).__name__}
                ))
                return {
                    'encoding': 'binary',
                    'delimiter': None,
                    'has_header': False,
                    'column_count': 0,
                    'row_count': 0,
                    'nested_structure': False,
                    'sheets': None,
                    'column_names': None,
                    'column_types': {},
                    'evidence': evidence,
                    'metadata': metadata
                }, error
            
            # Get schema
            schema = parquet_metadata.schema.to_arrow_schema()
            column_names = [field.name for field in schema]
            column_types = {field.name: str(field.type) for field in schema}
            
            # Get row count
            row_count = parquet_metadata.num_rows
            
            # Check for nested structures
            nested_structure = any(
                pa.types.is_struct(field.type) or pa.types.is_list(field.type)
                for field in schema
            )
            
            # Calculate nested depth
            nested_depth = max(
                self._calculate_arrow_nested_depth(field.type) for field in schema
            ) if nested_structure else 0
            
            evidence.append(collect_evidence(
                f"Parquet schema: {len(column_names)} columns",
                additional_info={'columns': column_names[:5] if len(column_names) > 5 else column_names}
            ))
            evidence.append(collect_evidence(
                f"Row count: {row_count}",
                additional_info={'num_row_groups': parquet_metadata.num_row_groups}
            ))
            
            if nested_structure:
                evidence.append(collect_evidence(
                    "Detected nested structures",
                    additional_info={'nested_depth': nested_depth}
                ))
            
            metadata.update({
                'num_row_groups': parquet_metadata.num_row_groups,
                'created_by': parquet_metadata.created_by,
                'format_version': parquet_metadata.format_version,
                'serialized_size': parquet_metadata.serialized_size,
                'nested_depth': nested_depth
            })
            
            return {
                'encoding': 'binary',
                'delimiter': None,
                'has_header': False,
                'column_count': len(column_names),
                'row_count': row_count,
                'nested_structure': nested_structure,
                'sheets': None,
                'column_names': column_names,
                'column_types': column_types,
                'evidence': evidence,
                'metadata': metadata
            }, None
            
        except Exception as e:
            error = f"Failed to parse Parquet structure: {str(e)}"
            evidence.append(collect_evidence(
                error,
                additional_info={'error_type': type(e).__name__}
            ))
            return {
                'encoding': 'binary',
                'delimiter': None,
                'has_header': False,
                'column_count': 0,
                'row_count': 0,
                'nested_structure': False,
                'sheets': None,
                'column_names': None,
                'column_types': {},
                'evidence': evidence,
                'metadata': metadata
            }, error
    
    # ============================================================
    # Helper Methods (Parquet-Specific)
    # ============================================================
    
    def _calculate_arrow_nested_depth(self, arrow_type, current_depth: int = 0) -> int:
        """
        Calculate maximum nesting depth of Arrow type
        
        Args:
            arrow_type: Can be pa.DataType, pa.Schema, or pa.Field
            
        Returns:
            Maximum nesting depth
        """
        try:
            import pyarrow as pa
            
            # Handle Schema object - iterate over fields
            if isinstance(arrow_type, pa.Schema):
                if len(arrow_type) == 0:
                    return current_depth
                return max(
                    self._calculate_arrow_nested_depth(field.type, current_depth)
                    for field in arrow_type
                )
            
            # Handle Field object - get its type
            if isinstance(arrow_type, pa.Field):
                arrow_type = arrow_type.type
            
            # Handle DataType
            if pa.types.is_struct(arrow_type):
                if len(arrow_type) == 0:
                    return current_depth
                return max(
                    self._calculate_arrow_nested_depth(field.type, current_depth + 1)
                    for field in arrow_type
                )
            elif pa.types.is_list(arrow_type):
                return self._calculate_arrow_nested_depth(arrow_type.value_type, current_depth + 1)
            else:
                return current_depth
        except ImportError:
            return current_depth
        except Exception:
            return current_depth


# Wrapper function for backward compatibility
def detect_parquet_structure(
    file_path: str,
    datalake_client,
    blob_client=None,
    introspection_result: Optional[FileIntrospectionResult] = None
) -> Dict[str, Any]:
    """
    Detect Parquet structure (wrapper function for backward compatibility)
    
    Args:
        file_path: Path to Parquet file in Data Lake
        datalake_client: Azure Data Lake Gen2 client
        blob_client: Optional Azure Blob Storage client for fallback
        introspection_result: Result from File Introspection System
        
    Returns:
        Dict with structure information
    """
    detector = ParquetDetector(datalake_client, blob_client)
    return detector.detect_structure(file_path, introspection_result)
