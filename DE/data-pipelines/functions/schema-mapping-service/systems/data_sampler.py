"""
Data Sampling System
Loads and samples data from Bronze Layer after format is known
Implements resampling strategy:
- If total rows ≤ 10k: use entire dataset (no resampling)
- If total rows > 10k: sample 10k rows, create 3 resamples
"""

import io
import logging
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

try:
    import openpyxl
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False

try:
    from system_interfaces import (
        IDataSamplingSystem,
        DataSamplingResult,
        SchemaDetectionResult
    )
    from utils.service_bus_parser import parse_data_ingested_message
except ImportError:
    from ..system_interfaces import (
        IDataSamplingSystem,
        DataSamplingResult,
        SchemaDetectionResult
    )
    from ..utils.service_bus_parser import parse_data_ingested_message

from .format_detectors.common import read_file_sample, decode_text
import traceback

try:
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
except ImportError:
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError


class DataSampler(IDataSamplingSystem):
    """
    Data Sampling System
    Loads and samples data from Data Lake Gen2 Bronze Layer
    """
    
    # Maximum file size for Excel (10MB)
    MAX_EXCEL_FILE_SIZE = 10 * 1024 * 1024
    
    # Default sampling parameters
    DEFAULT_MAX_SAMPLE_SIZE = 10000
    DEFAULT_N_RESAMPLES = 3
    
    def __init__(
        self, 
        datalake_client, 
        blob_client=None,
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None,
        run_id: Optional[str] = None,
        state_tracker = None
    ):
        """
        Initialize Data Sampler
        
        Args:
            datalake_client: Azure Data Lake Gen2 client (FileSystemClient)
            blob_client: Optional Azure Blob Storage client for fallback
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
            run_id: Run ID for tracking and filtering
            state_tracker: Optional PipelineStateTracker instance
        """
        self.datalake_client = datalake_client
        self.blob_client = blob_client
        self.service_bus_writer = service_bus_writer
        self.key_vault_url = key_vault_url
        self.run_id = run_id
        self.state_tracker = state_tracker
        self._message_context: Optional[Dict[str, Any]] = None
    
    def _get_service_bus_writer(self) -> Optional[ServiceBusWriter]:
        """Get or create Service Bus writer"""
        if self.service_bus_writer:
            return self.service_bus_writer
        
        if self.key_vault_url:
            try:
                return ServiceBusWriter(key_vault_url=self.key_vault_url)
            except Exception as e:
                logger.warning(f"Failed to create Service Bus writer: {e}")
                return None
        
        return None
    
    def load_and_sample_from_datalake(
        self,
        bronze_path: str,
        format: str,
        encoding: str,
        max_sample_size: int = DEFAULT_MAX_SAMPLE_SIZE,
        n_resamples: int = DEFAULT_N_RESAMPLES,
        schema_result: Optional[SchemaDetectionResult] = None,
        parsed_message: Optional[Dict[str, Any]] = None,
        introspection_result: Optional[Any] = None
    ) -> DataSamplingResult:
        """
        Load and sample data from Data Lake Gen2 Bronze Layer
        
        Args:
            bronze_path: Path to file in Bronze Layer (or use parsed_message.bronze_blob_path)
            format: Detected format (csv, json, parquet, excel, tsv, txt)
            encoding: Detected encoding (utf-8, latin-1, etc.)
            max_sample_size: Maximum rows per sample (default: 10000)
            n_resamples: Number of resamples to create (default: 3)
            schema_result: Optional SchemaDetectionResult with additional metadata
            parsed_message: Optional parsed Service Bus message dict with bronze_blob_path
            
        Returns:
            DataSamplingResult with samples, metadata, and sampling strategy
        """
        system_name = "System 2: Data Sampling"
        
        # Extract bronze_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            bronze_path = parsed_message.get('bronze_blob_path', bronze_path)
            # Get run_id from parsed_message if not set in __init__
            if not self.run_id:
                self.run_id = parsed_message.get('run_id')
            # Store context for potential future use (e.g., logging, metadata)
            self._message_context = {
                'run_id': self.run_id,
                'training_upload_id': parsed_message.get('training_upload_id'),
                'upload_id': parsed_message.get('upload_id'),  # Backward compatibility
                'bank_id': parsed_message.get('bank_id'),
                'date': parsed_message.get('date'),
                'bronze_blob_path': bronze_path
            }
        else:
            self._message_context = None
        
        # Check deduplication before processing
        system_name_short = "sampling"
        if self.state_tracker and self.run_id and self._message_context:
            try:
                if self.state_tracker.check_system_already_completed(self.run_id, system_name_short):
                    logger.warning(f"[run_id={self.run_id}] System {system_name_short} already completed. Skipping.")
            except Exception as e:
                logger.warning(f"[run_id={self.run_id}] Failed to check deduplication: {e}. Continuing.")
        
        # Record system start in state tracker
        if self.state_tracker and self.run_id and self._message_context:
            try:
                training_upload_id = self._message_context.get('training_upload_id') or self._message_context.get('upload_id')
                self.state_tracker.start_system(
                    run_id=self.run_id,
                    training_upload_id=training_upload_id,
                    system_name=system_name_short
                )
                logger.debug(f"[run_id={self.run_id}] Recorded system start: {system_name_short}")
            except Exception as e:
                logger.warning(f"[run_id={self.run_id}] Failed to record system start: {e}")
        
        # Publish system starting
        writer = self._get_service_bus_writer()
        if writer and self._message_context:
            try:
                writer.publish_system_starting(
                    training_upload_id=self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown'),
                    bank_id=self._message_context.get('bank_id', 'unknown'),
                    system_name=system_name,
                    run_id=self.run_id
                )
            except Exception as e:
                logger.warning(f"[run_id={self.run_id}] Failed to publish system starting message: {e}")
        
        try:
            metadata = {
                'file_path': bronze_path,
                'format': format,
                'encoding': encoding,
                'max_sample_size': max_sample_size,
                'n_resamples': n_resamples
            }
            
            # Load the full DataFrame (or sample if too large)
            df = None
            total_rows = 0
            load_error = None
            detected_format = format
            
            # Check for format conflict
            format_conflict = getattr(schema_result, 'format_conflict', False) if schema_result else False
            fallback_format = getattr(schema_result, 'fallback_format', None) if schema_result else None
            
            if format_conflict and fallback_format:
                logger.info(f"Format conflict detected. Attempting primary format '{format}' first.")
                df, total_rows, load_error, detected_format = self._load_dataframe(
                    bronze_path, format, encoding, schema_result, introspection_result
                )
                
                if load_error or df is None or len(df) == 0:
                    logger.warning(f"Primary format '{format}' failed to load correctly: {load_error}. Attempting fallback format '{fallback_format}'.")
                    # Try fallback format
                    df, total_rows, load_error, detected_format = self._load_dataframe(
                        bronze_path, fallback_format, encoding, schema_result, introspection_result
                    )
                    if not load_error and df is not None and len(df) > 0:
                        logger.info(f"Successfully loaded using fallback format '{fallback_format}'.")
                        format = fallback_format
            else:
                # Normal loading path
                df, total_rows, load_error, detected_format = self._load_dataframe(
                    bronze_path, format, encoding, schema_result, introspection_result
                )
            
            # Use detected format if it fell back successfully from 'unknown'
            if format.lower() == 'unknown' and detected_format != 'unknown':
                logger.info(f"Format updated from 'unknown' to '{detected_format}' during loading.")
                format = detected_format
            
            if load_error:
                logger.error(f"Failed to load DataFrame: {load_error}")
                return DataSamplingResult(
                    samples=[],
                    metadata={**metadata, 'error': load_error},
                    format=format,
                    encoding=encoding,
                    total_row_count=0,
                    column_count=0,
                    sampling_strategy='error'
                )
            
            if df is None or len(df) == 0:
                error_msg = 'Empty DataFrame loaded' if df is not None else 'DataFrame is None'
                logger.warning(f"DataFrame is empty or None: {error_msg}. df is None: {df is None}, df length: {len(df) if df is not None else 'N/A'}")
                return DataSamplingResult(
                    samples=[],
                    metadata={**metadata, 'error': error_msg},
                    format=format,
                    encoding=encoding,
                    total_row_count=0,
                    column_count=len(df.columns) if df is not None else 0,
                    sampling_strategy='empty'
                )
            
            # Determine sampling strategy
            sampling_strategy = self._determine_sampling_strategy(
                total_rows, max_sample_size
            )
            metadata['sampling_strategy'] = sampling_strategy
            metadata['total_rows'] = total_rows
            metadata['column_count'] = len(df.columns)
            
            # Apply sampling strategy
            if sampling_strategy == 'full_dataset':
                # Use entire dataset, no resampling
                samples = [df]
                metadata['sample_count'] = 1
                metadata['sample_sizes'] = [len(df)]
            else:
                # Create multiple resamples
                samples = self.resample_data(df, n_resamples, max_sample_size)
                metadata['sample_count'] = len(samples)
                metadata['sample_sizes'] = [len(s) for s in samples]
            
            result = DataSamplingResult(
                samples=samples,
                metadata=metadata,
                format=format,
                encoding=encoding,
                total_row_count=total_rows,
                column_count=len(df.columns),
                sampling_strategy=sampling_strategy
            )
            
            # Record system completion in state tracker
            if self.state_tracker and self.run_id:
                try:
                    self.state_tracker.complete_system(
                        run_id=self.run_id,
                        system_name=system_name_short,
                        metadata={
                            "format": format,
                            "total_row_count": total_rows,
                            "column_count": len(df.columns),
                            "sampling_strategy": sampling_strategy,
                            "sample_count": len(samples)
                        }
                    )
                    logger.debug(f"[run_id={self.run_id}] Recorded system completion: {system_name_short}")
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to record system completion: {e}")
            
            # Publish system complete
            if writer and self._message_context:
                try:
                    writer.publish_system_complete(
                        training_upload_id=self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        status=InternalStatus.SAMPLING_COMPLETE,
                        result={
                            "format": format,
                            "total_row_count": total_rows,
                            "column_count": len(df.columns),
                            "sampling_strategy": sampling_strategy,
                            "sample_count": len(samples)
                        },
                        run_id=self.run_id
                    )
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to publish system complete message: {e}")
            
            return result
            
        except Exception as e:
            # Record system failure in state tracker
            if self.state_tracker and self.run_id:
                try:
                    self.state_tracker.fail_system(
                        run_id=self.run_id,
                        system_name=system_name_short,
                        error_message=str(e)
                    )
                    logger.debug(f"[run_id={self.run_id}] Recorded system failure: {system_name_short}")
                except Exception as state_error:
                    logger.warning(f"[run_id={self.run_id}] Failed to record system failure: {state_error}")
            
            # Publish error (both internal and backend)
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            if writer and self._message_context:
                try:
                    # Internal error (detailed)
                    writer.publish_system_failed(
                        training_upload_id=self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        error={
                            "message": error_message,
                            "type": error_type,
                            "stack_trace": stack_trace,
                            "bronze_path": bronze_path
                        },
                        run_id=self.run_id
                    )
                    
                    # Backend error (user-friendly)
                    training_upload_id = self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')
                    writer.publish_backend_error(
                        training_upload_id=training_upload_id,
                        error_type=error_type,
                        error_message=error_message,
                        system_name=system_name,
                        stack_trace=stack_trace,
                        run_id=self.run_id
                    )
                except Exception as pub_error:
                    logger.error(f"[run_id={self.run_id}] Failed to publish error messages: {pub_error}")
            
            logger.error(f"[run_id={self.run_id}] Error in data sampling: {error_message}", exc_info=True)
            
            # Return error result
            return DataSamplingResult(
                samples=[],
                metadata={**metadata, 'error': error_message, 'error_type': error_type},
                format=format,
                encoding=encoding,
                total_row_count=0,
                column_count=0,
                sampling_strategy='error'
            )
    
    def _load_dataframe(
        self,
        file_path: str,
        format: str,
        encoding: str,
        schema_result: Optional[SchemaDetectionResult] = None,
        introspection_result: Optional[Any] = None
    ) -> Tuple[Optional[pd.DataFrame], int, Optional[str], str]:
        """
        Load DataFrame from Data Lake based on format
        
        Args:
            file_path: Path to file in Data Lake
            format: Detected format (csv, json, parquet, excel, tsv, txt, unknown)
            encoding: Detected encoding
            schema_result: Optional SchemaDetectionResult with additional metadata
            introspection_result: Optional FileIntrospectionResult with format_hints
        
        Returns:
            Tuple of (DataFrame, total_row_count, error, final_detected_format)
        """
        format_lower = format.lower()
        
        if format_lower in ['csv', 'tsv']:
            df, rows, err = self._load_csv_tsv(file_path, format_lower, encoding, schema_result)
            return df, rows, err, format_lower
        elif format_lower == 'json' or format_lower == 'jsonl':
            df, rows, err = self._load_json(file_path, encoding, schema_result)
            return df, rows, err, format_lower
        elif format_lower == 'parquet':
            df, rows, err = self._load_parquet(file_path, schema_result)
            return df, rows, err, format_lower
        elif format_lower in ['excel', 'xlsx', 'xls']:
            df, rows, err = self._load_excel(file_path, schema_result)
            return df, rows, err, format_lower
        elif format_lower == 'txt':
            df, rows, err = self._load_txt(file_path, encoding, schema_result)
            return df, rows, err, format_lower
        elif format_lower == 'unknown':
            # Fallback: Use introspection format_hints first, then file extension
            format_hints = None
            if introspection_result and hasattr(introspection_result, 'format_hints'):
                format_hints = introspection_result.format_hints
            
            # Check introspection format hints first (most reliable)
            if format_hints:
                if format_hints.get('possible_csv'):
                    logger.info("Format is 'unknown', but introspection suggests CSV. Attempting CSV load.")
                    df, rows, err = self._load_csv_tsv(file_path, 'csv', encoding, schema_result)
                    return df, rows, err, 'csv'
                elif format_hints.get('possible_tsv'):
                    logger.info("Format is 'unknown', but introspection suggests TSV. Attempting TSV load.")
                    df, rows, err = self._load_csv_tsv(file_path, 'tsv', encoding, schema_result)
                    return df, rows, err, 'tsv'
                elif format_hints.get('possible_json'):
                    logger.info("Format is 'unknown', but introspection suggests JSON. Attempting JSON load.")
                    df, rows, err = self._load_json(file_path, encoding, schema_result)
                    return df, rows, err, 'json'
                elif format_hints.get('possible_parquet'):
                    logger.info("Format is 'unknown', but introspection suggests Parquet. Attempting Parquet load.")
                    df, rows, err = self._load_parquet(file_path, schema_result)
                    return df, rows, err, 'parquet'
                elif format_hints.get('possible_excel'):
                    logger.info("Format is 'unknown', but introspection suggests Excel. Attempting Excel load.")
                    df, rows, err = self._load_excel(file_path, schema_result)
                    return df, rows, err, 'excel'
            
            # Fallback to file extension if introspection hints don't help
            file_path_lower = file_path.lower()
            if file_path_lower.endswith('.csv'):
                logger.info("Format is 'unknown', but file extension is .csv. Attempting CSV load.")
                df, rows, err = self._load_csv_tsv(file_path, 'csv', encoding, schema_result)
                return df, rows, err, 'csv'
            elif file_path_lower.endswith('.tsv'):
                logger.info("Format is 'unknown', but file extension is .tsv. Attempting TSV load.")
                df, rows, err = self._load_csv_tsv(file_path, 'tsv', encoding, schema_result)
                return df, rows, err, 'tsv'
            elif file_path_lower.endswith(('.xlsx', '.xls')):
                logger.info("Format is 'unknown', but file extension is Excel. Attempting Excel load.")
                df, rows, err = self._load_excel(file_path, schema_result)
                return df, rows, err, 'excel'
            elif file_path_lower.endswith('.json') or file_path_lower.endswith('.jsonl'):
                logger.info("Format is 'unknown', but file extension is JSON. Attempting JSON load.")
                df, rows, err = self._load_json(file_path, encoding, schema_result)
                return df, rows, err, 'json'
            elif file_path_lower.endswith('.parquet'):
                logger.info("Format is 'unknown', but file extension is Parquet. Attempting Parquet load.")
                df, rows, err = self._load_parquet(file_path, schema_result)
                return df, rows, err, 'parquet'
            else:
                # Last resort: Try TXT (which will attempt delimiter detection)
                logger.info("Format is 'unknown' and no introspection hints or recognized extension. Attempting TXT load with delimiter detection.")
                df, rows, err = self._load_txt(file_path, encoding, schema_result)
                return df, rows, err, 'txt'
        else:
            return None, 0, f"Unsupported format: {format}", format
    
    def _load_csv_tsv(
        self,
        file_path: str,
        format: str,
        encoding: str,
        schema_result: Optional[SchemaDetectionResult] = None
    ) -> Tuple[Optional[pd.DataFrame], int, Optional[str]]:
        """Load CSV or TSV file"""
        try:
            # Get delimiter from schema_result or default
            delimiter = ','
            if schema_result and schema_result.delimiter:
                delimiter = schema_result.delimiter
            elif format == 'tsv':
                delimiter = '\t'
            
            # Get header setting from schema_result
            header = 0 if (schema_result is None or schema_result.has_header) else None
            
            logger.info(f"Loading CSV/TSV: file_path={file_path}, delimiter={repr(delimiter)}, encoding={encoding}, header={header}")
            
            # Read file from Data Lake
            file_client = self.datalake_client.get_file_client(file_path)
            file_data = file_client.download_file().readall()
            logger.info(f"Downloaded {len(file_data)} bytes from Data Lake")
            
            # Decode text
            text_data, encoding_used, decode_error = decode_text(file_data, encoding)
            if decode_error:
                logger.error(f"Failed to decode text with encoding {encoding}: {decode_error}")
                return None, 0, f"Failed to decode text: {decode_error}"
            
            logger.info(f"Decoded text: {len(text_data)} characters (first 200 chars: {text_data[:200]}) using encoding: {encoding_used}")
            
            # Read into DataFrame
            # For pandas 2.x, on_bad_lines parameter still exists but behavior may differ
            # Use engine='python' for more lenient parsing if needed
            try:
                df = pd.read_csv(
                    io.StringIO(text_data),
                    delimiter=delimiter,
                    encoding=encoding,
                    header=header,
                    low_memory=False,
                    on_bad_lines='skip'  # Skip malformed lines (pandas 1.x/2.x compatible)
                )
            except TypeError:
                # pandas 2.2+ may have changed parameter name
                logger.warning("on_bad_lines parameter failed, trying without it")
                df = pd.read_csv(
                    io.StringIO(text_data),
                    delimiter=delimiter,
                    encoding=encoding,
                    header=header,
                    low_memory=False,
                    engine='python'  # Python engine is more lenient
                )
            
            total_rows = len(df)
            logger.info(f"Successfully loaded CSV/TSV: {total_rows} rows, {len(df.columns)} columns. Columns: {list(df.columns)[:10]}")
            return df, total_rows, None
            
        except Exception as e:
            logger.error(f"Failed to load CSV/TSV from {file_path}: {str(e)}", exc_info=True)
            return None, 0, f"Failed to load CSV/TSV: {str(e)}"
    
    def _load_json(
        self,
        file_path: str,
        encoding: str,
        schema_result: Optional[SchemaDetectionResult] = None
    ) -> Tuple[Optional[pd.DataFrame], int, Optional[str]]:
        """Load JSON or JSONL file"""
        try:
            import json
            
            # Read file from Data Lake
            file_client = self.datalake_client.get_file_client(file_path)
            file_data = file_client.download_file().readall()
            
            # Decode text
            text_data, encoding_used, decode_error = decode_text(file_data, encoding)
            if decode_error:
                return None, 0, f"Failed to decode text: {decode_error}"
            
            # Try to detect JSONL (newline-delimited JSON)
            is_jsonl = text_data.strip().startswith('{') and '\n' in text_data[:1000]
            
            if is_jsonl:
                # JSONL: one JSON object per line
                lines = text_data.strip().split('\n')
                records = []
                for line in lines:
                    if line.strip():
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue  # Skip invalid lines
                
                if not records:
                    return None, 0, "No valid JSON records found in JSONL file"
                
                df = pd.json_normalize(records)
            else:
                # Regular JSON: array of objects or single object
                data = json.loads(text_data)
                
                if isinstance(data, list):
                    # Array of objects
                    df = pd.json_normalize(data)
                elif isinstance(data, dict):
                    # Single object - wrap in list
                    df = pd.json_normalize([data])
                else:
                    return None, 0, "JSON must be an object or array of objects"
            
            total_rows = len(df)
            return df, total_rows, None
            
        except Exception as e:
            return None, 0, f"Failed to load JSON: {str(e)}"
    
    def _load_parquet(
        self,
        file_path: str,
        schema_result: Optional[SchemaDetectionResult] = None
    ) -> Tuple[Optional[pd.DataFrame], int, Optional[str]]:
        """Load Parquet file"""
        if not PARQUET_AVAILABLE:
            return None, 0, "PyArrow not available for Parquet loading"
        
        try:
            # Read file from Data Lake
            file_client = self.datalake_client.get_file_client(file_path)
            file_data = file_client.download_file().readall()
            
            # Read Parquet from bytes
            parquet_file = io.BytesIO(file_data)
            df = pd.read_parquet(parquet_file, engine='pyarrow')
            
            total_rows = len(df)
            return df, total_rows, None
            
        except Exception as e:
            return None, 0, f"Failed to load Parquet: {str(e)}"
    
    def _load_excel(
        self,
        file_path: str,
        schema_result: Optional[SchemaDetectionResult] = None
    ) -> Tuple[Optional[pd.DataFrame], int, Optional[str]]:
        """Load Excel file"""
        if not EXCEL_AVAILABLE:
            return None, 0, "openpyxl not available for Excel loading"
        
        try:
            # Check file size first
            file_client = self.datalake_client.get_file_client(file_path)
            file_properties = file_client.get_file_properties()
            file_size = file_properties.size
            
            if file_size > self.MAX_EXCEL_FILE_SIZE:
                return None, 0, f"Excel file too large ({file_size} bytes > {self.MAX_EXCEL_FILE_SIZE} bytes)"
            
            # Read file from Data Lake
            file_data = file_client.download_file().readall()
            
            # Determine sheet to read
            sheet_name = 0  # Default to first sheet
            if schema_result and schema_result.sheets:
                # Use first sheet from schema detection
                sheet_name = schema_result.sheets[0] if isinstance(schema_result.sheets, list) else schema_result.sheets
            
            # Read Excel from bytes
            excel_file = io.BytesIO(file_data)
            df = pd.read_excel(
                excel_file,
                engine='openpyxl',
                sheet_name=sheet_name,
                header=0 if (schema_result is None or schema_result.has_header) else None
            )
            
            total_rows = len(df)
            return df, total_rows, None
            
        except Exception as e:
            return None, 0, f"Failed to load Excel: {str(e)}"
    
    def _load_txt(
        self,
        file_path: str,
        encoding: str,
        schema_result: Optional[SchemaDetectionResult] = None
    ) -> Tuple[Optional[pd.DataFrame], int, Optional[str]]:
        """Load TXT file (fallback for unknown text formats)"""
        try:
            # Read file from Data Lake
            file_client = self.datalake_client.get_file_client(file_path)
            file_data = file_client.download_file().readall()
            
            # Decode text
            text_data, encoding_used, decode_error = decode_text(file_data, encoding)
            if decode_error:
                return None, 0, f"Failed to decode text: {decode_error}"
            
            # Try to detect delimiter from schema_result
            delimiter = None
            if schema_result and schema_result.delimiter:
                delimiter = schema_result.delimiter
            else:
                # Try common delimiters
                for delim in [',', '\t', '|', ';']:
                    if delim in text_data[:1000]:
                        delimiter = delim
                        break
            
            # Read into DataFrame
            if delimiter:
                df = pd.read_csv(
                    io.StringIO(text_data),
                    delimiter=delimiter,
                    encoding=encoding,
                    header=0 if (schema_result is None or schema_result.has_header) else None,
                    low_memory=False,
                    on_bad_lines='skip'
                )
            else:
                # No delimiter found - treat as single column
                lines = text_data.split('\n')
                df = pd.DataFrame({'text': lines})
            
            total_rows = len(df)
            return df, total_rows, None
            
        except Exception as e:
            return None, 0, f"Failed to load TXT: {str(e)}"
    
    def _determine_sampling_strategy(
        self,
        total_rows: int,
        max_sample_size: int = DEFAULT_MAX_SAMPLE_SIZE
    ) -> str:
        """
        Determine sampling strategy based on row count
        
        Returns:
            - "full_dataset" if total_rows <= max_sample_size
            - "reservoir" if total_rows > max_sample_size
        """
        if total_rows <= max_sample_size:
            return 'full_dataset'
        else:
            return 'reservoir'
    
    def resample_data(
        self,
        df: pd.DataFrame,
        n_samples: int = DEFAULT_N_RESAMPLES,
        sample_size: int = DEFAULT_MAX_SAMPLE_SIZE
    ) -> List[pd.DataFrame]:
        """
        Create multiple random resamples from DataFrame
        
        Args:
            df: Source DataFrame
            n_samples: Number of resamples to create
            sample_size: Size of each sample
            
        Returns:
            List of resampled DataFrames
        """
        samples = []
        
        # If DataFrame is smaller than sample_size, return copies
        if len(df) <= sample_size:
            for i in range(n_samples):
                samples.append(df.copy())
            return samples
        
        # Create n_samples independent resamples
        for i in range(n_samples):
            # Use different random_state for each sample to ensure independence
            sample = df.sample(
                n=min(sample_size, len(df)),
                random_state=i,  # Different seed for each sample
                replace=False  # Without replacement
            ).reset_index(drop=True)
            samples.append(sample)
        
        return samples
    
    def aggregate_insights(
        self,
        samples: List[pd.DataFrame]
    ) -> Dict[str, Any]:
        """
        Aggregate insights from multiple resamples
        
        Args:
            samples: List of resampled DataFrames
            
        Returns:
            Dict with aggregated metadata (averages, unions, most common patterns)
        """
        if not samples:
            return {}
        
        aggregated = {
            'sample_count': len(samples),
            'sample_sizes': [len(s) for s in samples],
            'avg_sample_size': np.mean([len(s) for s in samples]) if samples else 0,
            'total_unique_columns': set(),
            'common_columns': [],
            'column_types_union': {}
        }
        
        # Collect all column names
        all_columns = set()
        for sample in samples:
            all_columns.update(sample.columns.tolist())
        
        aggregated['total_unique_columns'] = list(all_columns)
        
        # Find columns present in all samples
        if samples:
            common_cols = set(samples[0].columns)
            for sample in samples[1:]:
                common_cols &= set(sample.columns)
            aggregated['common_columns'] = list(common_cols)
        
        # Aggregate column types (union of all types found)
        for sample in samples:
            for col in sample.columns:
                dtype = str(sample[col].dtype)
                if col not in aggregated['column_types_union']:
                    aggregated['column_types_union'][col] = []
                if dtype not in aggregated['column_types_union'][col]:
                    aggregated['column_types_union'][col].append(dtype)
        
        # Calculate data completeness across samples
        completeness_stats = {}
        for col in all_columns:
            non_null_counts = []
            for sample in samples:
                if col in sample.columns:
                    non_null_counts.append(sample[col].notna().sum())
                else:
                    non_null_counts.append(0)
            
            completeness_stats[col] = {
                'avg_non_null_count': np.mean(non_null_counts) if non_null_counts else 0,
                'min_non_null_count': min(non_null_counts) if non_null_counts else 0,
                'max_non_null_count': max(non_null_counts) if non_null_counts else 0
            }
        
        aggregated['completeness_stats'] = completeness_stats
        
        return aggregated
