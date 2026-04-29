"""
JSON format detector
Detects JSON structure: nested objects, arrays, schema
"""

import json
from typing import Dict, Any, Optional, Tuple, List

try:
    from system_interfaces import FileIntrospectionResult
except ImportError:
    from ..system_interfaces import FileIntrospectionResult

from .base import BaseFormatDetector
from .common import decode_text, infer_column_types_from_samples, collect_evidence


class JSONDetector(BaseFormatDetector):
    """
    JSON format detector
    Detects JSON/JSONL structure with nested object support
    """
    
    def detect_format_signature(
        self,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[bool, float, List[str]]:
        """
        Detect if data matches JSON format
        
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
            if introspection_result.format_hints.get('possible_json'):
                confidence += 0.3
                evidence.append("JSON format hints detected in introspection")
        
        # Decode sample data
        text_sample, encoding, decode_error = self.decode_text(sample_data, introspection_result=introspection_result)
        if decode_error:
            return False, 0.0, [f"Failed to decode sample: {decode_error}"]
        
        # Check for JSON magic bytes/patterns
        text_sample_stripped = text_sample.strip()
        
        # Check if starts with { or [
        if text_sample_stripped.startswith('{') or text_sample_stripped.startswith('['):
            confidence += 0.4
            evidence.append(collect_evidence(
                f"Starts with JSON structure marker",
                additional_info={'first_char': text_sample_stripped[0]}
            ))
        
        # Try to parse as JSON
        try:
            json.loads(text_sample_stripped)
            confidence += 0.3
            evidence.append("Successfully parsed as JSON")
        except json.JSONDecodeError:
            # Try first line (for JSONL)
            lines = text_sample.split('\n')
            if len(lines) > 1:
                try:
                    json.loads(lines[0])
                    confidence += 0.2
                    evidence.append("First line parses as JSON (possible JSONL)")
                except json.JSONDecodeError:
                    pass
        
        # Check file extension
        if introspection_result and hasattr(introspection_result, 'file_path'):
            file_path = introspection_result.file_path
            if file_path and (file_path.lower().endswith('.json') or file_path.lower().endswith('.jsonl')):
                confidence += 0.2
                evidence.append(f"File extension indicates JSON format")
        
        is_match = confidence >= 0.5
        return is_match, min(confidence, 1.0), evidence
    
    def parse_structure(
        self,
        file_path: str,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse JSON structure
        
        Args:
            file_path: Path to JSON file in Data Lake
            sample_data: Sample bytes from file
            introspection_result: Result from File Introspection System
            
        Returns:
            Tuple of (structure_info, error)
        """
        evidence = []
        metadata = {}
        
        # Decode sample data
        text_sample, encoding, decode_error = self.decode_text(sample_data, introspection_result=introspection_result)
        if decode_error:
            return {}, f"Failed to decode sample: {decode_error}"
        
        evidence.append(collect_evidence(
            f"Decoded sample using encoding: {encoding}",
            additional_info={'sample_size': len(sample_data)}
        ))
        
        # Detect if JSONL (newline-delimited JSON)
        is_jsonl, jsonl_evidence = self._detect_jsonl(text_sample)
        evidence.extend(jsonl_evidence)
        
        # Parse JSON structure
        parse_result, parse_error = self._parse_json_structure(text_sample, is_jsonl)
        
        if parse_error:
            evidence.append(collect_evidence(
                f"JSON parsing error: {parse_error}",
                additional_info={'is_jsonl': is_jsonl}
            ))
            if not parse_result:
                return {}, parse_error
        
        # Merge evidence from parsing
        if parse_result and parse_result.get('evidence'):
            evidence.extend(parse_result['evidence'])
        
        # Extract structure information
        column_names = parse_result.get('column_names')
        column_types = parse_result.get('column_types', {})
        nested_structure = parse_result.get('nested_structure', False)
        row_count = parse_result.get('row_count', 0)
        
        # Use common type inference if we have sample rows
        if parse_result.get('sample_rows'):
            inferred_types, type_evidence = infer_column_types_from_samples(
                parse_result['sample_rows'], format='json'
            )
            # Merge with existing types
            column_types.update(inferred_types)
            evidence.extend(type_evidence)
        
        column_count = len(column_names) if column_names else 0
        
        metadata.update({
            'is_jsonl': is_jsonl,
            'sample_size': len(sample_data),
            'nested_depth': parse_result.get('nested_depth', 0)
        })
        
        return {
            'encoding': encoding,
            'delimiter': None,
            'has_header': False,  # JSON doesn't have headers
            'column_count': column_count,
            'row_count': row_count,
            'nested_structure': nested_structure,
            'sheets': None,
            'column_names': column_names,
            'column_types': column_types,
            'evidence': evidence,
            'metadata': metadata
        }, None
    
    # ============================================================
    # Helper Methods (JSON-Specific)
    # ============================================================
    
    def _detect_jsonl(self, text_sample: str) -> Tuple[bool, List[str]]:
        """
        Detect if JSONL format (newline-delimited JSON)
        
        Returns:
            Tuple of (is_jsonl, evidence)
        """
        evidence = []
        lines = text_sample.split('\n')
        
        if len(lines) <= 1:
            return False, [collect_evidence("Single line or no newlines, not JSONL")]
        
        # Try to parse first 3-5 lines as JSON
        jsonl_confidence = 0.0
        parsed_lines = 0
        
        for i, line in enumerate(lines[:5], start=1):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            
            try:
                json.loads(line_stripped)
                parsed_lines += 1
                jsonl_confidence += 0.2
                evidence.append(collect_evidence(
                    f"Line {i} parses as JSON",
                    line_number=i
                ))
            except json.JSONDecodeError:
                evidence.append(collect_evidence(
                    f"Line {i} does not parse as JSON",
                    line_number=i
                ))
                break
        
        is_jsonl = jsonl_confidence >= 0.4 and parsed_lines >= 2
        
        if is_jsonl:
            evidence.append(collect_evidence(
                f"Detected JSONL format (newline-delimited JSON)",
                additional_info={'parsed_lines': parsed_lines, 'total_lines_checked': min(5, len(lines))}
            ))
        else:
            evidence.append(collect_evidence(
                f"Not JSONL format (regular JSON)",
                additional_info={'parsed_lines': parsed_lines}
            ))
        
        return is_jsonl, evidence
    
    def _parse_json_structure(
        self,
        text_sample: str,
        is_jsonl: bool
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse JSON structure
        
        Returns:
            Tuple of (structure_info, error)
        """
        nested_structure = False
        column_names = None
        column_types = {}
        row_count = 0
        sample_rows = []
        nested_depth = 0
        
        try:
            if is_jsonl:
                # JSONL format - parse multiple records
                structure_info, error = self._parse_jsonl_structure(text_sample)
                return structure_info, error
            else:
                # Regular JSON - parse entire sample
                structure_info, error = self._parse_regular_json_structure(text_sample)
                return structure_info, error
                
        except Exception as e:
            return {}, f"Failed to parse JSON structure: {str(e)}"
    
    def _parse_jsonl_structure(self, text_sample: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse JSONL structure
        
        Returns:
            Tuple of (structure_info, error)
        """
        evidence = []
        lines = text_sample.split('\n')
        records = []
        
        # Parse first 100 records
        for i, line in enumerate(lines[:100], start=1):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            
            try:
                record = json.loads(line_stripped)
                records.append(record)
            except json.JSONDecodeError as e:
                evidence.append(collect_evidence(
                    f"Failed to parse line {i} as JSON",
                    line_number=i,
                    additional_info={'error': str(e)}
                ))
                break
        
        if not records:
            return {}, "No valid JSON records found in JSONL format"
        
        # Analyze structure from first record
        first_record = records[0]
        
        if not isinstance(first_record, dict):
            return {}, f"First record is not a dictionary (type: {type(first_record).__name__})"
        
        column_names = list(first_record.keys())
        nested_structure = any(
            isinstance(v, (dict, list)) for v in first_record.values()
        )
        
        # Calculate nested depth
        nested_depth = self._calculate_nested_depth(first_record)
        
        # Convert records to sample rows for type inference
        sample_rows = records[:10]  # Use first 10 for type inference
        
        # Estimate row count from line count
        row_count = len([l for l in lines if l.strip()])
        
        evidence.append(collect_evidence(
            f"JSONL: {len(records)} records analyzed",
            additional_info={'total_lines': len(lines), 'valid_records': len(records)}
        ))
        
        return {
            'column_names': column_names,
            'nested_structure': nested_structure,
            'nested_depth': nested_depth,
            'row_count': row_count,
            'sample_rows': sample_rows,
            'column_types': {},  # Will be inferred by common function
            'evidence': evidence
        }, None
    
    def _parse_regular_json_structure(self, text_sample: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse regular JSON structure (single object or array)
        
        Returns:
            Tuple of (structure_info, error)
        """
        evidence = []
        
        try:
            data = json.loads(text_sample)
        except json.JSONDecodeError as e:
            return {}, f"Failed to parse JSON: {str(e)}"
        
        column_names = None
        nested_structure = False
        nested_depth = 0
        row_count = 0
        sample_rows = []
        
        if isinstance(data, list):
            # Array of objects
            if len(data) > 0:
                if isinstance(data[0], dict):
                    column_names = list(data[0].keys())
                    nested_structure = any(
                        isinstance(v, (dict, list)) for v in data[0].values()
                    )
                    nested_depth = self._calculate_nested_depth(data[0])
                    sample_rows = data[:10]  # Use first 10 for type inference
                    row_count = len(data)
                    
                    evidence.append(collect_evidence(
                        f"JSON array: {len(data)} objects",
                        additional_info={'columns': len(column_names)}
                    ))
                else:
                    return {}, f"JSON array contains non-dict objects (type: {type(data[0]).__name__})"
            else:
                return {}, "JSON array is empty"
                
        elif isinstance(data, dict):
            # Single object
            column_names = list(data.keys())
            nested_structure = any(
                isinstance(v, (dict, list)) for v in data.values()
            )
            nested_depth = self._calculate_nested_depth(data)
            sample_rows = [data]  # Single record
            row_count = 1
            
            evidence.append(collect_evidence(
                f"JSON object (single record)",
                additional_info={'columns': len(column_names)}
            ))
        else:
            return {}, f"JSON root is not an object or array (type: {type(data).__name__})"
        
        if nested_structure:
            evidence.append(collect_evidence(
                f"Detected nested structures (objects/arrays)",
                additional_info={'nested_depth': nested_depth}
            ))
        
        return {
            'column_names': column_names,
            'nested_structure': nested_structure,
            'nested_depth': nested_depth,
            'row_count': row_count,
            'sample_rows': sample_rows,
            'column_types': {},  # Will be inferred by common function
            'evidence': evidence
        }, None
    
    def _calculate_nested_depth(self, obj: Any, current_depth: int = 0) -> int:
        """
        Calculate maximum nesting depth of JSON structure
        
        Returns:
            Maximum nesting depth
        """
        if isinstance(obj, dict):
            if not obj:
                return current_depth
            return max(
                self._calculate_nested_depth(v, current_depth + 1) for v in obj.values()
            )
        elif isinstance(obj, list):
            if not obj:
                return current_depth
            return max(
                self._calculate_nested_depth(item, current_depth + 1) for item in obj
            )
        else:
            return current_depth


# Wrapper function for backward compatibility
def detect_json_structure(
    file_path: str,
    datalake_client,
    blob_client=None,
    introspection_result: Optional[FileIntrospectionResult] = None
) -> Dict[str, Any]:
    """
    Detect JSON structure (wrapper function for backward compatibility)
    
    Args:
        file_path: Path to JSON file in Data Lake
        datalake_client: Azure Data Lake Gen2 client
        blob_client: Optional Azure Blob Storage client for fallback
        introspection_result: Result from File Introspection System
        
    Returns:
        Dict with structure information
    """
    detector = JSONDetector(datalake_client, blob_client)
    return detector.detect_structure(file_path, introspection_result)
