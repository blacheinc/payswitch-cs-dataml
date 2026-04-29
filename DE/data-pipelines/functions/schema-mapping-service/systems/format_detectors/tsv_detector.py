"""
TSV (Tab-Separated Values) format detector
Similar to CSV but uses tab delimiter
"""

import io
import csv
from typing import Dict, Any, Optional, Tuple, List
import pandas as pd

try:
    from system_interfaces import FileIntrospectionResult
except ImportError:
    from ..system_interfaces import FileIntrospectionResult

from .base import BaseFormatDetector
from .common import decode_text, infer_column_types_from_samples, collect_evidence


class TSVDetector(BaseFormatDetector):
    """
    TSV format detector
    Detects TSV structure (tab-delimited, similar to CSV)
    """
    
    def detect_format_signature(
        self,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[bool, float, List[str]]:
        """
        Detect if data matches TSV format
        
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
            delimiter_hints = introspection_result.format_hints.get('delimiter_hints', [])
            if '\t' in delimiter_hints:
                confidence += 0.4
                evidence.append("Tab delimiter hints detected in introspection")
        
        # Decode sample data
        text_sample, encoding, decode_error = self.decode_text(sample_data, introspection_result=introspection_result)
        if decode_error:
            return False, 0.0, [f"Failed to decode sample: {decode_error}"]
        
        # Check for tab delimiter
        tab_count = text_sample.count('\t')
        newline_count = text_sample.count('\n')
        
        if tab_count > 0 and newline_count > 0:
            confidence += 0.5
            evidence.append(collect_evidence(
                f"Found {tab_count} tabs and {newline_count} newlines in sample",
                additional_info={'tab_count': tab_count, 'newline_count': newline_count}
            ))
        
        # Check file extension
        if introspection_result and hasattr(introspection_result, 'file_path'):
            file_path = introspection_result.file_path
            if file_path and file_path.lower().endswith('.tsv'):
                confidence += 0.2
                evidence.append("File extension is .tsv")
        
        is_match = confidence >= 0.5
        return is_match, min(confidence, 1.0), evidence
    
    def parse_structure(
        self,
        file_path: str,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse TSV structure (similar to CSV but with tab delimiter)
        
        Args:
            file_path: Path to TSV file in Data Lake
            sample_data: Sample bytes from file
            introspection_result: Result from File Introspection System
            
        Returns:
            Tuple of (structure_info, error)
        """
        evidence = []
        metadata = {}
        
        # TSV uses tab delimiter
        delimiter = '\t'
        quote_char = '"'  # TSV typically doesn't use quotes, but check
        
        # Decode sample data
        text_sample, encoding, decode_error = self.decode_text(sample_data, introspection_result=introspection_result)
        if decode_error:
            return {}, f"Failed to decode sample: {decode_error}"
        
        evidence.append(collect_evidence(
            f"Decoded sample using encoding: {encoding}",
            additional_info={'delimiter': 'tab', 'sample_size': len(sample_data)}
        ))
        
        # Read first few lines for analysis
        lines = text_sample.split('\n')[:100]
        evidence.append(collect_evidence(
            f"Analyzing first {len(lines)} lines",
            additional_info={'lines_analyzed': len(lines)}
        ))
        
        # Detect header
        has_header, header_evidence = self._detect_header(lines, delimiter, quote_char)
        evidence.extend(header_evidence)
        
        # Get column names
        column_names, column_evidence = self._extract_column_names(
            lines, delimiter, quote_char, has_header
        )
        evidence.extend(column_evidence)
        
        column_count = len(column_names) if column_names else 0
        
        # Infer column types from sample data
        column_types = {}
        if column_names and has_header:
            sample_rows, type_evidence = self._extract_sample_rows(
                text_sample, delimiter, quote_char, encoding, nrows=100
            )
            evidence.extend(type_evidence)
            
            if sample_rows:
                inferred_types, type_inference_evidence = infer_column_types_from_samples(
                    sample_rows, format='tsv'
                )
                column_types = inferred_types
                evidence.extend(type_inference_evidence)
        
        metadata.update({
            'delimiter': delimiter,
            'quote_char': quote_char,
            'sample_size': len(sample_data),
            'lines_analyzed': len(lines)
        })
        
        return {
            'encoding': encoding,
            'delimiter': delimiter,
            'has_header': has_header,
            'column_count': column_count,
            'row_count': 0,  # Will be estimated by base class
            'nested_structure': False,
            'sheets': None,
            'column_names': column_names,
            'column_types': column_types,
            'evidence': evidence,
            'metadata': metadata
        }, None
    
    # ============================================================
    # Helper Methods (TSV-Specific, similar to CSV)
    # ============================================================
    
    def _detect_header(
        self,
        lines: List[str],
        delimiter: str,
        quote_char: str
    ) -> Tuple[bool, List[str]]:
        """Detect if first line is a header (same logic as CSV)"""
        evidence = []
        
        if not lines:
            return True, [collect_evidence("No lines available, assuming header exists")]
        
        try:
            reader = csv.reader(io.StringIO(lines[0]), delimiter=delimiter, quotechar=quote_char)
            first_row = list(reader)[0] if reader else []
            
            if not first_row:
                return True, [collect_evidence("First row is empty, assuming header exists")]
            
            non_numeric_count = sum(
                1 for cell in first_row
                if cell and not cell.replace('.', '').replace('-', '').replace('+', '').lstrip().isdigit()
            )
            
            ratio = non_numeric_count / len(first_row) if first_row else 0
            
            if ratio > 0.7:
                has_header = True
                evidence.append(collect_evidence(
                    f"First row appears to be headers",
                    line_number=1,
                    additional_info={'non_numeric_ratio': f"{ratio:.2%}", 'columns': len(first_row)}
                ))
            else:
                has_header = False
                evidence.append(collect_evidence(
                    f"First row appears to be data",
                    line_number=1,
                    additional_info={'non_numeric_ratio': f"{ratio:.2%}", 'columns': len(first_row)}
                ))
            
            return has_header, evidence
            
        except Exception as e:
            evidence.append(collect_evidence(
                f"Could not determine header, assuming header exists",
                additional_info={'error': str(e)}
            ))
            return True, evidence
    
    def _extract_column_names(
        self,
        lines: List[str],
        delimiter: str,
        quote_char: str,
        has_header: bool
    ) -> Tuple[Optional[List[str]], List[str]]:
        """Extract column names from header row"""
        evidence = []
        
        if not has_header or not lines:
            return None, [collect_evidence("No header row available")]
        
        try:
            reader = csv.reader(io.StringIO(lines[0]), delimiter=delimiter, quotechar=quote_char)
            column_names = list(reader)[0] if reader else []
            column_names = [name.strip() for name in column_names if name]
            
            if column_names:
                evidence.append(collect_evidence(
                    f"Extracted {len(column_names)} column names",
                    line_number=1,
                    additional_info={
                        'columns': column_names[:5] if len(column_names) > 5 else column_names
                    }
                ))
            else:
                evidence.append(collect_evidence("No column names found in header row", line_number=1))
            
            return column_names if column_names else None, evidence
            
        except Exception as e:
            evidence.append(collect_evidence(
                f"Failed to extract column names",
                line_number=1,
                additional_info={'error': str(e)}
            ))
            return None, evidence
    
    def _extract_sample_rows(
        self,
        text_sample: str,
        delimiter: str,
        quote_char: str,
        encoding: str,
        nrows: int = 100
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Extract sample rows as dictionaries"""
        evidence = []
        
        try:
            sample_df = pd.read_csv(
                io.StringIO(text_sample),
                delimiter=delimiter,
                quotechar=quote_char,
                nrows=nrows,
                encoding=encoding
            )
            sample_rows = sample_df.to_dict('records')
            
            evidence.append(collect_evidence(
                f"Extracted {len(sample_rows)} sample rows for type inference",
                additional_info={'nrows': len(sample_rows)}
            ))
            
            return sample_rows, evidence
            
        except Exception as e:
            evidence.append(collect_evidence(
                f"Failed to extract sample rows using pandas",
                additional_info={'error': str(e)}
            ))
            return [], evidence


# Wrapper function for backward compatibility
def detect_tsv_structure(
    file_path: str,
    datalake_client,
    blob_client=None,
    introspection_result: Optional[FileIntrospectionResult] = None
) -> Dict[str, Any]:
    """
    Detect TSV structure (wrapper function for backward compatibility)
    
    Args:
        file_path: Path to TSV file in Data Lake
        datalake_client: Azure Data Lake Gen2 client
        blob_client: Optional Azure Blob Storage client for fallback
        introspection_result: Result from File Introspection System
        
    Returns:
        Dict with structure information
    """
    detector = TSVDetector(datalake_client, blob_client)
    return detector.detect_structure(file_path, introspection_result)
