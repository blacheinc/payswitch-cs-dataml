"""
Base Format Detector Abstract Class
Defines interface and shared implementations for all format detectors
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List
import io

try:
    from system_interfaces import FileIntrospectionResult
except ImportError:
    from ..system_interfaces import FileIntrospectionResult

# Import common utilities
try:
    from .common import (
        read_file_sample,
        read_multi_location_samples,
        decode_text,
        estimate_row_count_from_samples,
        infer_column_types_from_samples,
        collect_evidence
    )
except ImportError:
    # Fallback if common not yet available
    read_file_sample = None
    read_multi_location_samples = None
    decode_text = None
    estimate_row_count_from_samples = None
    infer_column_types_from_samples = None
    collect_evidence = None


class BaseFormatDetector(ABC):
    """
    Abstract base class for all format detectors
    
    Provides:
    - Abstract methods that must be implemented by each format
    - Shared implementations for common operations
    - Structured error handling
    - Multi-dimensional confidence scoring
    - Evidence collection
    """
    
    def __init__(self, datalake_client, blob_client=None):
        """
        Initialize format detector
        
        Args:
            datalake_client: Azure Data Lake Gen2 client
            blob_client: Optional Azure Blob Storage client for fallback
        """
        self.datalake_client = datalake_client
        self.blob_client = blob_client
        self.sample_size_per_location = 65536  # 64KB per location
    
    # ============================================================
    # Abstract Methods (Must Implement)
    # ============================================================
    
    @abstractmethod
    def detect_format_signature(
        self,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[bool, float, List[str]]:
        """
        Detect if this format matches the data
        
        Args:
            sample_data: Sample bytes from file
            introspection_result: Result from File Introspection System
            
        Returns:
            Tuple of (is_match, confidence, evidence)
            - is_match: bool - Whether this format matches
            - confidence: float (0.0-1.0) - Confidence in format detection
            - evidence: List[str] - Evidence for the detection
        """
        pass
    
    @abstractmethod
    def parse_structure(
        self,
        file_path: str,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse the structure of the file
        
        Args:
            file_path: Path to file in Data Lake
            sample_data: Sample bytes from file
            introspection_result: Result from File Introspection System
            
        Returns:
            Tuple of (structure_info, error)
            - structure_info: Dict with format-specific structure details
            - error: Optional[str] - Error message if parsing failed
        """
        pass
    
    # ============================================================
    # Shared Implementations (Can Override)
    # ============================================================
    
    def read_file_sample(
        self,
        file_path: str,
        sample_size: int = None,
        offset: int = 0
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Read sample data from file
        
        Args:
            file_path: Path to file in Data Lake
            sample_size: Size of sample to read (default: self.sample_size_per_location)
            offset: Byte offset to start reading from
            
        Returns:
            Tuple of (sample_data, error)
            - sample_data: Optional[bytes] - Sample data or None if error
            - error: Optional[str] - Error message if reading failed
        """
        if sample_size is None:
            sample_size = self.sample_size_per_location
        
        if read_file_sample:
            return read_file_sample(
                file_path=file_path,
                datalake_client=self.datalake_client,
                blob_client=self.blob_client,
                sample_size=sample_size,
                offset=offset
            )
        else:
            # Fallback implementation
            try:
                file_client = self.datalake_client.get_file_client(file_path)
                file_properties = file_client.get_file_properties()
                read_size = min(sample_size, file_properties.size - offset)
                if read_size <= 0:
                    return None, "Offset beyond file size"
                sample_data = file_client.download_file(offset=offset, length=read_size).readall()
                return sample_data, None
            except Exception as e:
                if self.blob_client:
                    try:
                        container_name = file_path.split('/')[0] if '/' in file_path else None
                        blob_path = '/'.join(file_path.split('/')[1:]) if '/' in file_path else file_path
                        blob_client_instance = self.blob_client.get_blob_client(
                            container=container_name,
                            blob=blob_path
                        )
                        sample_data = blob_client_instance.download_blob(
                            offset=offset, length=sample_size
                        ).readall()
                        return sample_data, None
                    except Exception as blob_error:
                        return None, f"Failed to read sample: {str(e)}, {str(blob_error)}"
                return None, f"Failed to read sample: {str(e)}"
    
    def read_multi_location_samples(
        self,
        file_path: str
    ) -> Tuple[Dict[str, bytes], Optional[str]]:
        """
        Read samples from multiple locations (beginning, middle, end)
        
        Args:
            file_path: Path to file in Data Lake
            
        Returns:
            Tuple of (samples_dict, error)
            - samples_dict: Dict with keys 'beginning', 'middle', 'end'
            - error: Optional[str] - Error message if reading failed
        """
        if read_multi_location_samples:
            return read_multi_location_samples(
                file_path=file_path,
                datalake_client=self.datalake_client,
                blob_client=self.blob_client,
                sample_size=self.sample_size_per_location
            )
        else:
            # Fallback implementation
            try:
                file_client = self.datalake_client.get_file_client(file_path)
                file_properties = file_client.get_file_properties()
                file_size = file_properties.size
                
                samples = {}
                
                # Beginning sample
                beg_data, beg_error = self.read_file_sample(file_path, offset=0)
                if beg_error:
                    return None, f"Failed to read beginning sample: {beg_error}"
                samples['beginning'] = beg_data
                
                # Middle sample
                if file_size > self.sample_size_per_location * 2:
                    mid_offset = (file_size - self.sample_size_per_location) // 2
                    mid_data, mid_error = self.read_file_sample(file_path, offset=mid_offset)
                    if mid_error:
                        return None, f"Failed to read middle sample: {mid_error}"
                    samples['middle'] = mid_data
                else:
                    samples['middle'] = beg_data  # Use beginning if file too small
                
                # End sample
                if file_size > self.sample_size_per_location:
                    end_offset = max(0, file_size - self.sample_size_per_location)
                    end_data, end_error = self.read_file_sample(file_path, offset=end_offset)
                    if end_error:
                        return None, f"Failed to read end sample: {end_error}"
                    samples['end'] = end_data
                else:
                    samples['end'] = beg_data  # Use beginning if file too small
                
                return samples, None
            except Exception as e:
                return None, f"Failed to read multi-location samples: {str(e)}"
    
    def decode_text(
        self,
        data: bytes,
        encoding: Optional[str] = None,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Decode bytes to text
        
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
        if decode_text:
            return decode_text(
                data=data,
                encoding=encoding,
                introspection_result=introspection_result
            )
        else:
            # Fallback implementation
            if encoding is None:
                if introspection_result and introspection_result.encoding:
                    encoding = introspection_result.encoding
                else:
                    encoding = 'utf-8'
            
            try:
                text = data.decode(encoding)
                return text, encoding, None
            except UnicodeDecodeError:
                try:
                    text = data.decode('utf-8', errors='replace')
                    return text, 'utf-8', None
                except Exception as e:
                    return None, None, f"Failed to decode text: {str(e)}"
    
    def estimate_row_count(
        self,
        samples: Dict[str, bytes],
        file_size: int,
        format: str
    ) -> Tuple[int, List[str]]:
        """
        Estimate row count from multiple samples
        
        Args:
            samples: Dict of samples from different locations
            file_size: Total file size in bytes
            format: File format (for format-specific estimation)
            
        Returns:
            Tuple of (row_count, evidence)
            - row_count: int - Estimated row count
            - evidence: List[str] - Evidence for the estimation
        """
        if estimate_row_count_from_samples:
            return estimate_row_count_from_samples(
                samples=samples,
                file_size=file_size,
                format=format
            )
        else:
            # Fallback: simple estimation
            evidence = []
            total_newlines = 0
            total_sample_size = 0
            
            for location, sample_data in samples.items():
                newlines = sample_data.count(b'\n')
                total_newlines += newlines
                total_sample_size += len(sample_data)
                evidence.append(f"{location.capitalize()} sample: {newlines} newlines in {len(sample_data)} bytes")
            
            if total_sample_size > 0 and file_size > 0:
                sample_ratio = total_sample_size / file_size
                estimated_rows = int(total_newlines / sample_ratio) if sample_ratio > 0 else total_newlines
                evidence.append(f"Estimated {estimated_rows} rows based on {sample_ratio:.2%} sample coverage")
            else:
                estimated_rows = total_newlines
                evidence.append(f"Estimated {estimated_rows} rows (simple count)")
            
            return estimated_rows, evidence
    
    def infer_column_types(
        self,
        sample_rows: List[Dict[str, Any]],
        format: str
    ) -> Tuple[Dict[str, str], List[str]]:
        """
        Infer column types from sample rows
        
        Args:
            sample_rows: List of sample row dictionaries
            format: File format (for format-specific inference)
            
        Returns:
            Tuple of (column_types, evidence)
            - column_types: Dict mapping column names to types
            - evidence: List[str] - Evidence for type inference
        """
        if infer_column_types_from_samples:
            return infer_column_types_from_samples(
                sample_rows=sample_rows,
                format=format
            )
        else:
            # Fallback: basic type inference
            evidence = []
            column_types = {}
            
            if not sample_rows:
                return column_types, evidence
            
            # Get all column names from first row
            first_row = sample_rows[0]
            for col_name in first_row.keys():
                sample_values = [row.get(col_name) for row in sample_rows if col_name in row and row[col_name] is not None]
                if sample_values:
                    first_type = type(sample_values[0]).__name__
                    column_types[col_name] = first_type
                    evidence.append(f"Column '{col_name}': inferred type '{first_type}' from {len(sample_values)} non-null values")
            
            return column_types, evidence
    
    # ============================================================
    # Main Detection Method (Orchestrator)
    # ============================================================
    
    def detect_structure(
        self,
        file_path: str,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Dict[str, Any]:
        """
        Main method to detect file structure
        
        This orchestrates the detection process:
        1. Read multi-location samples
        2. Detect format signature
        3. Parse structure
        4. Calculate confidence scores
        5. Collect evidence
        
        Args:
            file_path: Path to file in Data Lake
            introspection_result: Result from File Introspection System
            
        Returns:
            Dict with structure information including:
            - format: str
            - encoding: str
            - column_count: int
            - row_count: int
            - column_names: List[str]
            - column_types: Dict[str, str]
            - confidence_scores: Dict[str, float]
            - evidence: List[str]
            - metadata: Dict[str, Any]
        """
        evidence = []
        metadata = {}
        
        # Step 1: Read multi-location samples
        samples, error = self.read_multi_location_samples(file_path)
        if error:
            evidence.append(f"Error reading samples: {error}")
            return self._create_error_result(error, evidence, metadata)
        
        # Use beginning sample for format detection
        beginning_sample = samples.get('beginning')
        if not beginning_sample:
            error = "No beginning sample available"
            evidence.append(error)
            return self._create_error_result(error, evidence, metadata)
        
        # Step 2: Detect format signature
        is_match, format_confidence, format_evidence = self.detect_format_signature(
            beginning_sample,
            introspection_result
        )
        evidence.extend(format_evidence)
        
        if not is_match:
            error = f"Format signature does not match {self.__class__.__name__}"
            evidence.append(error)
            return self._create_error_result(error, evidence, metadata, format_confidence=format_confidence)
        
        # Step 3: Parse structure
        structure_info, parse_error = self.parse_structure(
            file_path,
            beginning_sample,
            introspection_result
        )
        
        if parse_error:
            evidence.append(f"Parsing error: {parse_error}")
            # Continue with partial results if available
            if not structure_info:
                return self._create_error_result(parse_error, evidence, metadata, format_confidence=format_confidence)
        
        # Step 4: Get file size for row estimation
        try:
            file_client = self.datalake_client.get_file_client(file_path)
            file_properties = file_client.get_file_properties()
            file_size = file_properties.size
        except Exception:
            file_size = sum(len(s) for s in samples.values())
        
        # Step 5: Estimate row count from all samples
        estimated_rows, row_evidence = self.estimate_row_count(
            samples,
            file_size,
            self.__class__.__name__.replace('Detector', '').lower()
        )
        evidence.extend(row_evidence)
        
        # Step 6: Calculate multi-dimensional confidence scores
        confidence_scores = self._calculate_confidence_scores(
            format_confidence=format_confidence,
            structure_info=structure_info,
            parse_error=parse_error
        )
        
        # Step 7: Aggregate results
        result = {
            'encoding': structure_info.get('encoding', 'utf-8'),
            'delimiter': structure_info.get('delimiter'),
            'has_header': structure_info.get('has_header', True),
            'column_count': structure_info.get('column_count', 0),
            'row_count': estimated_rows if estimated_rows > 0 else structure_info.get('row_count', 0),
            'nested_structure': structure_info.get('nested_structure', False),
            'sheets': structure_info.get('sheets'),
            'column_names': structure_info.get('column_names'),
            'column_types': structure_info.get('column_types', {}),
            'confidence': confidence_scores.get('overall', format_confidence),
            'confidence_scores': confidence_scores,
            'evidence': evidence,
            'metadata': {**metadata, **structure_info.get('metadata', {})}
        }
        
        return result
    
    # ============================================================
    # Helper Methods
    # ============================================================
    
    def _calculate_confidence_scores(
        self,
        format_confidence: float,
        structure_info: Dict[str, Any],
        parse_error: Optional[str]
    ) -> Dict[str, float]:
        """
        Calculate multi-dimensional confidence scores
        
        Returns:
            Dict with confidence scores:
            - format_confidence: Confidence in format detection
            - schema_confidence: Confidence in schema structure
            - type_confidence: Confidence in type inference
            - completeness_confidence: Confidence in completeness
            - overall: Weighted overall confidence
        """
        # Format confidence (already calculated)
        format_conf = format_confidence
        
        # Schema confidence (based on structure parsing success)
        if parse_error:
            schema_conf = 0.3
        elif structure_info.get('column_count', 0) > 0:
            schema_conf = 0.9
        else:
            schema_conf = 0.5
        
        # Type confidence (based on type inference)
        column_types = structure_info.get('column_types', {})
        if column_types:
            type_conf = min(0.9, 0.5 + (len(column_types) / max(1, structure_info.get('column_count', 1))) * 0.4)
        else:
            type_conf = 0.3
        
        # Completeness confidence (based on how much we detected)
        column_count = structure_info.get('column_count', 0)
        row_count = structure_info.get('row_count', 0)
        if column_count > 0 and row_count > 0:
            completeness_conf = 0.9
        elif column_count > 0:
            completeness_conf = 0.7
        else:
            completeness_conf = 0.3
        
        # Overall confidence (weighted average)
        weights = {
            'format': 0.3,
            'schema': 0.4,
            'type': 0.2,
            'completeness': 0.1
        }
        overall = (
            format_conf * weights['format'] +
            schema_conf * weights['schema'] +
            type_conf * weights['type'] +
            completeness_conf * weights['completeness']
        )
        
        return {
            'format_confidence': format_conf,
            'schema_confidence': schema_conf,
            'type_confidence': type_conf,
            'completeness_confidence': completeness_conf,
            'overall': overall
        }
    
    def _create_error_result(
        self,
        error: str,
        evidence: List[str],
        metadata: Dict[str, Any],
        format_confidence: float = 0.0
    ) -> Dict[str, Any]:
        """Create error result structure"""
        return {
            'encoding': 'utf-8',
            'delimiter': None,
            'has_header': True,
            'column_count': 0,
            'row_count': 0,
            'nested_structure': False,
            'sheets': None,
            'column_names': None,
            'column_types': None,
            'confidence': format_confidence,
            'confidence_scores': {
                'format_confidence': format_confidence,
                'schema_confidence': 0.0,
                'type_confidence': 0.0,
                'completeness_confidence': 0.0,
                'overall': format_confidence
            },
            'evidence': evidence,
            'metadata': {**metadata, 'error': error}
        }
