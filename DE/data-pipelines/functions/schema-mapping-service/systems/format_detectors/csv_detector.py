"""
CSV format detector
Detects CSV structure: delimiter, quoting, escape chars, headers, columns
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


class CSVDetector(BaseFormatDetector):
    """
    CSV format detector
    Detects CSV structure using delimiter detection, header detection, and type inference
    """
    
    def detect_format_signature(
        self,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[bool, float, List[str]]:
        """
        Detect if data matches CSV format
        
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
            if introspection_result.format_hints.get('possible_csv'):
                confidence += 0.3
                evidence.append("CSV delimiter hints detected in introspection")
        
        # Check for common CSV delimiters
        text_sample, encoding, decode_error = self.decode_text(sample_data, introspection_result=introspection_result)
        if decode_error:
            return False, 0.0, [f"Failed to decode sample: {decode_error}"]
        
        # Check for comma delimiter
        comma_count = text_sample.count(',')
        newline_count = text_sample.count('\n')
        
        if comma_count > 0 and newline_count > 0:
            # Likely CSV
            confidence += 0.4
            evidence.append(f"Found {comma_count} commas and {newline_count} newlines in sample")
            
            # Check if rows have consistent column counts
            lines = text_sample.split('\n')[:10]
            if len(lines) > 1:
                try:
                    sniffer = csv.Sniffer()
                    dialect = sniffer.sniff(text_sample[:8192])
                    if dialect.delimiter == ',':
                        confidence += 0.3
                        evidence.append(f"CSV Sniffer detected comma delimiter")
                except Exception:
                    pass
        
        # Check file extension if available
        if introspection_result and hasattr(introspection_result, 'file_path'):
            file_path = introspection_result.file_path
            if file_path and file_path.lower().endswith('.csv'):
                confidence += 0.2
                evidence.append("File extension is .csv")
        
        is_match = confidence >= 0.5
        return is_match, min(confidence, 1.0), evidence
    
    def parse_structure(
        self,
        file_path: str,
        sample_data: bytes,
        introspection_result: Optional[FileIntrospectionResult] = None
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Parse CSV structure
        
        Args:
            file_path: Path to CSV file in Data Lake
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
        
        evidence.append(f"Decoded sample using encoding: {encoding}")
        
        # Detect delimiter
        delimiter, delimiter_evidence = self._detect_delimiter(text_sample, introspection_result)
        evidence.extend(delimiter_evidence)
        
        # Detect quote character
        quote_char, quote_evidence = self._detect_quote_char(text_sample)
        evidence.extend(quote_evidence)
        
        # Read first few lines for analysis
        lines = text_sample.split('\n')[:100]
        evidence.append(f"Analyzing first {len(lines)} lines")
        
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
                    sample_rows, format='csv'
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
    # Helper Methods (CSV-Specific)
    # ============================================================
    
    def _detect_delimiter(self, text_sample: str, introspection_result: Optional[FileIntrospectionResult] = None) -> Tuple[str, List[str]]:
        """
        Detect CSV delimiter
        
        Returns:
            Tuple of (delimiter, evidence)
        """
        evidence = []
        
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(text_sample[:8192])
            delimiter = dialect.delimiter
            evidence.append(collect_evidence(
                f"Detected delimiter: {repr(delimiter)}",
                additional_info={'method': 'csv.Sniffer'}
            ))
            return delimiter, evidence
        except Exception as e:
            # Check introspection hints if sniffer fails
            if introspection_result and introspection_result.format_hints and 'delimiter_hints' in introspection_result.format_hints:
                delimiters = introspection_result.format_hints['delimiter_hints']
                if delimiters:
                    delimiter = delimiters[0]  # Take the most likely delimiter
                    evidence.append(collect_evidence(
                        f"Could not sniff delimiter, using introspection hint: {repr(delimiter)}",
                        additional_info={'error': str(e), 'method': 'introspection_hints'}
                    ))
                    return delimiter, evidence
                    
            # Default to comma
            delimiter = ','
            evidence.append(collect_evidence(
                f"Could not detect delimiter, defaulting to comma",
                additional_info={'error': str(e)}
            ))
            return delimiter, evidence
    
    def _detect_quote_char(self, text_sample: str) -> Tuple[str, List[str]]:
        """
        Detect quote character
        
        Returns:
            Tuple of (quote_char, evidence)
        """
        evidence = []
        
        # Count single and double quotes
        single_quotes = text_sample.count("'")
        double_quotes = text_sample.count('"')
        
        if single_quotes > double_quotes * 1.5:
            quote_char = "'"
            evidence.append(collect_evidence(
                f"Detected quote character: single quote",
                additional_info={'single_quotes': single_quotes, 'double_quotes': double_quotes}
            ))
        else:
            quote_char = '"'
            if double_quotes > 0:
                evidence.append(collect_evidence(
                    f"Detected quote character: double quote",
                    additional_info={'single_quotes': single_quotes, 'double_quotes': double_quotes}
                ))
        
        return quote_char, evidence
    
    def _detect_header(
        self,
        lines: List[str],
        delimiter: str,
        quote_char: str
    ) -> Tuple[bool, List[str]]:
        """
        Detect if first line is a header
        
        Returns:
            Tuple of (has_header, evidence)
        """
        evidence = []
        
        if not lines:
            return True, [collect_evidence("No lines available, assuming header exists")]
        
        try:
            reader = csv.reader(io.StringIO(lines[0]), delimiter=delimiter, quotechar=quote_char)
            first_row = list(reader)[0] if reader else []
            
            if not first_row:
                return True, [collect_evidence("First row is empty, assuming header exists")]
            
            # Check if first row looks like headers (mostly strings, not numbers)
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
                    additional_info={
                        'non_numeric_ratio': f"{ratio:.2%}",
                        'columns': len(first_row)
                    }
                ))
            else:
                has_header = False
                evidence.append(collect_evidence(
                    f"First row appears to be data",
                    line_number=1,
                    additional_info={
                        'non_numeric_ratio': f"{ratio:.2%}",
                        'columns': len(first_row)
                    }
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
        """
        Extract column names from header row
        
        Returns:
            Tuple of (column_names, evidence)
        """
        evidence = []
        
        if not has_header or not lines:
            return None, [collect_evidence("No header row available")]
        
        try:
            reader = csv.reader(io.StringIO(lines[0]), delimiter=delimiter, quotechar=quote_char)
            column_names = list(reader)[0] if reader else []
            
            # Clean column names (strip whitespace)
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
                evidence.append(collect_evidence(
                    "No column names found in header row",
                    line_number=1
                ))
            
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
        """
        Extract sample rows as dictionaries
        
        Returns:
            Tuple of (sample_rows, evidence)
        """
        evidence = []
        
        try:
            # Use pandas to parse CSV (handles edge cases better)
            sample_df = pd.read_csv(
                io.StringIO(text_sample),
                delimiter=delimiter,
                quotechar=quote_char,
                nrows=nrows,
                encoding=encoding
            )
            
            # Convert to list of dictionaries
            sample_rows = sample_df.to_dict('records')
            
            evidence.append(collect_evidence(
                f"Extracted {len(sample_rows)} sample rows for type inference",
                additional_info={'nrows': len(sample_rows)}
            ))
            
            return sample_rows, evidence
            
        except Exception as e:
            evidence.append(collect_evidence(
                f"Failed to extract sample rows using pandas, falling back to manual parsing",
                additional_info={'error': str(e)}
            ))
            
            # Fallback: manual parsing
            try:
                lines = text_sample.split('\n')[:nrows + 1]  # +1 for header
                if len(lines) < 2:
                    return [], evidence
                
                # Get column names from first line
                reader = csv.reader(io.StringIO(lines[0]), delimiter=delimiter, quotechar=quote_char)
                column_names = list(reader)[0] if reader else []
                
                sample_rows = []
                for i, line in enumerate(lines[1:], start=2):
                    try:
                        reader = csv.reader(io.StringIO(line), delimiter=delimiter, quotechar=quote_char)
                        row_values = list(reader)[0] if reader else []
                        if row_values and len(row_values) == len(column_names):
                            row_dict = dict(zip(column_names, row_values))
                            sample_rows.append(row_dict)
                    except Exception:
                        continue
                
                evidence.append(collect_evidence(
                    f"Manually extracted {len(sample_rows)} sample rows",
                    additional_info={'method': 'manual_parsing'}
                ))
                
                return sample_rows, evidence
                
            except Exception as fallback_error:
                evidence.append(collect_evidence(
                    f"Failed to extract sample rows (both pandas and manual parsing failed)",
                    additional_info={'error': str(fallback_error)}
                ))
                return [], evidence


# Wrapper function for backward compatibility
def detect_csv_structure(
    file_path: str,
    datalake_client,
    blob_client=None,
    introspection_result: Optional[FileIntrospectionResult] = None
) -> Dict[str, Any]:
    """
    Detect CSV structure (wrapper function for backward compatibility)
    
    Args:
        file_path: Path to CSV file in Data Lake
        datalake_client: Azure Data Lake Gen2 client
        blob_client: Optional Azure Blob Storage client for fallback
        introspection_result: Result from File Introspection System
        
    Returns:
        Dict with structure information
    """
    detector = CSVDetector(datalake_client, blob_client)
    return detector.detect_structure(file_path, introspection_result)
