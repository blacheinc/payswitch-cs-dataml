"""
Schema Detection System
Detects file format and schema structure using hints from File Introspection
"""

import os
import logging
import traceback
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

# Use absolute imports for better compatibility
try:
    from system_interfaces import (
        ISchemaDetectionSystem,
        SchemaDetectionResult,
        FileIntrospectionResult
    )
    from utils.service_bus_parser import parse_data_ingested_message
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from systems.schema_hash import calculate_schema_hash
    from schema_registry.schema_detection_store import SchemaDetectionStore
except ImportError:
    # Fallback for relative import
    from ..system_interfaces import (
        ISchemaDetectionSystem,
        SchemaDetectionResult,
        FileIntrospectionResult
    )
    from ..utils.service_bus_parser import parse_data_ingested_message
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from ..systems.schema_hash import calculate_schema_hash
    from ..schema_registry.schema_detection_store import SchemaDetectionStore

logger = logging.getLogger(__name__)

# Import format-specific detectors
try:
    from systems.format_detectors import (
        detect_csv_structure,
        detect_json_structure,
        detect_parquet_structure,
        detect_excel_structure,
        detect_tsv_structure
    )
except ImportError:
    # Fallback for relative import
    try:
        from .format_detectors import (
            detect_csv_structure,
            detect_json_structure,
            detect_parquet_structure,
            detect_excel_structure,
            detect_tsv_structure
        )
    except ImportError:
        # Format detectors not yet implemented
        detect_csv_structure = None
        detect_json_structure = None
        detect_parquet_structure = None
        detect_excel_structure = None
        detect_tsv_structure = None


class SchemaDetector(ISchemaDetectionSystem):
    """
    Schema Detection System
    Detects file format and schema structure using hints from File Introspection
    """
    
    # Format detection priority (order matters)
    FORMAT_PRIORITY = [
        'parquet',
        'json',
        'csv',
        'tsv',
        'excel',
        'xlsx',
        'xls',
        'txt'
    ]
    
    # Magic bytes for format detection
    FORMAT_MAGIC_BYTES = {
        b'PAR1': 'parquet',  # Parquet magic bytes
        b'{': 'json',  # JSON typically starts with {
        b'[': 'json',  # JSON array
        b'PK\x03\x04': 'excel',  # Excel/Office files (ZIP-based)
        b'PK\x05\x06': 'excel',
        b'PK\x07\x08': 'excel',
    }
    
    def __init__(self, datalake_client, blob_client=None, service_bus_writer: Optional[ServiceBusWriter] = None, key_vault_url: Optional[str] = None, run_id: Optional[str] = None, state_tracker = None):
        """
        Initialize Schema Detector
        
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
    
    def detect_format(
        self,
        file_path: str,
        introspection_result: FileIntrospectionResult,
        parsed_message: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, bool, Optional[str]]:
        """
        Auto-detect file format using introspection hints
        
        Args:
            file_path: Path to file in Data Lake (or use parsed_message.bronze_blob_path)
            introspection_result: Result from File Introspection System
            parsed_message: Optional parsed Service Bus message dict with bronze_blob_path
            
        Returns:
            Tuple: (detected_format, format_conflict, fallback_format)
        """
        # Extract file_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            file_path = parsed_message.get('bronze_blob_path', file_path)
            # Store context for potential future use (e.g., schema registry lookups)
            self._message_context = {
                'training_upload_id': parsed_message.get('training_upload_id'),
                'upload_id': parsed_message.get('upload_id'),  # Backward compatibility
                'bank_id': parsed_message.get('bank_id'),
                'date': parsed_message.get('date')
            }
        else:
            self._message_context = None
        evidence = []
        format_scores = {}
        
        # Determine buckets based on encoding presence
        # If encoding is None (or 'binary' if explicitly set), it's a binary file. Otherwise, text.
        is_binary = not introspection_result.encoding or introspection_result.encoding.lower() == 'binary'
        
        # Valid extensions/formats per bucket
        binary_formats = {'parquet', 'excel', 'avro'}
        text_formats = {'csv', 'tsv', 'json', 'jsonl', 'txt'}
        
        # 1. Check magic bytes from introspection (Highest weight)
        if introspection_result.magic_bytes:
            magic_bytes = introspection_result.magic_bytes[:16]
            for magic, format_type in self.FORMAT_MAGIC_BYTES.items():
                if magic_bytes.startswith(magic):
                    # Ensure the format matches the binary/text bucket
                    if (is_binary and format_type in binary_formats) or (not is_binary and format_type in text_formats):
                        format_scores[format_type] = format_scores.get(format_type, 0) + 15
                        evidence.append(f"Magic bytes match {format_type} (Bucket: {'Binary' if is_binary else 'Text'})")
        
        # 2. Check file extension
        file_ext = Path(file_path).suffix.lower().lstrip('.')
        ext_to_format = {
            'csv': 'csv',
            'tsv': 'tsv',
            'json': 'json',
            'jsonl': 'jsonl',
            'parquet': 'parquet',
            'xlsx': 'excel',
            'xls': 'excel',
            'txt': 'txt',
            'avro': 'avro'
        }
        
        if file_ext in ext_to_format:
            format_type = ext_to_format[file_ext]
            # Ensure the extension matches the bucket
            if is_binary and format_type in binary_formats:
                format_scores[format_type] = format_scores.get(format_type, 0) + 5
                evidence.append(f"File extension: .{file_ext} (matches Binary bucket)")
            elif not is_binary and format_type in text_formats:
                format_scores[format_type] = format_scores.get(format_type, 0) + 5
                evidence.append(f"File extension: .{file_ext} (matches Text bucket)")
            else:
                evidence.append(f"Ignored extension .{file_ext} because it conflicts with the {'Binary' if is_binary else 'Text'} bucket")
        
        # 3. Check format hints from introspection
        if introspection_result.format_hints:
            if not is_binary:
                if introspection_result.format_hints.get('possible_csv'):
                    format_scores['csv'] = format_scores.get('csv', 0) + 3
                    evidence.append("CSV delimiter hints detected")
                if introspection_result.format_hints.get('possible_json'):
                    format_scores['json'] = format_scores.get('json', 0) + 3
                    evidence.append("JSON format hints detected")
                if introspection_result.format_hints.get('possible_tsv'):
                    format_scores['tsv'] = format_scores.get('tsv', 0) + 3
                    evidence.append("TSV delimiter hints detected")
            if is_binary:
                if introspection_result.format_hints.get('possible_parquet'):
                    format_scores['parquet'] = format_scores.get('parquet', 0) + 3
                    evidence.append("Parquet format hints detected")
                if introspection_result.format_hints.get('possible_excel'):
                    format_scores['excel'] = format_scores.get('excel', 0) + 3
                    evidence.append("Excel structure hints detected")
        
        # 4. Check container/compression (affects how we read)
        if introspection_result.container_type == 'zip':
            # Could be Excel (XLSX is ZIP-based)
            if is_binary:
                format_scores['excel'] = format_scores.get('excel', 0) + 2
                evidence.append("ZIP container detected (could be Excel)")
        
        # 5. Check encoding and boundary type for text formats
        if not is_binary and introspection_result.encoding:
            if introspection_result.newline_type:
                # Text file with newlines - likely CSV/TSV/TXT
                if introspection_result.format_hints.get('delimiter_hints'):
                    delimiters = introspection_result.format_hints.get('delimiter_hints', [])
                    if ',' in delimiters:
                        format_scores['csv'] = format_scores.get('csv', 0) + 2
                        evidence.append("Comma delimiter detected")
                    if '\t' in delimiters:
                        format_scores['tsv'] = format_scores.get('tsv', 0) + 2
                        evidence.append("Tab delimiter detected")
        
        # Select format with highest score
        detected_format = None
        format_conflict = False
        fallback_format = None
        
        if format_scores:
            detected_format = max(format_scores.items(), key=lambda x: x[1])[0]
            logger.info(f"Format scores: {format_scores}, selected: {detected_format}")
            
            # Check for conflict: Does the extension match the detected format?
            if file_ext in ext_to_format and ext_to_format[file_ext] != detected_format:
                format_conflict = True
                fallback_format = ext_to_format[file_ext]
                logger.warning(f"Format conflict detected: Science says {detected_format}, filename says {fallback_format}")
            
            return detected_format, format_conflict, fallback_format
        
        # Safe Fallback respecting buckets
        if is_binary:
            if file_ext in ext_to_format and ext_to_format[file_ext] in binary_formats:
                return ext_to_format[file_ext], False, None
            return 'parquet', True, ext_to_format.get(file_ext) if file_ext in ext_to_format else None
        else:
            if file_ext in ext_to_format and ext_to_format[file_ext] in text_formats:
                return ext_to_format[file_ext], False, None
            return 'txt', True, ext_to_format.get(file_ext) if file_ext in ext_to_format else None
    
    def detect_schema(
        self,
        file_path: str,
        format: str,
        introspection_result: FileIntrospectionResult,
        parsed_message: Optional[Dict[str, Any]] = None,
        format_conflict: bool = False,
        fallback_format: Optional[str] = None
    ) -> SchemaDetectionResult:
        """
        Detect complete schema structure
        
        Args:
            file_path: Path to file in Data Lake (or use parsed_message.bronze_blob_path)
            format: Detected format (from detect_format)
            introspection_result: Result from File Introspection System
            parsed_message: Optional parsed Service Bus message dict with bronze_blob_path
            
        Returns:
            SchemaDetectionResult with format, encoding, columns, types, etc.
        """
        system_name = "System 1: Schema Detection"
        
        # Extract file_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            file_path = parsed_message.get('bronze_blob_path', file_path)
            # Get run_id from parsed_message if not set in __init__
            if not self.run_id:
                self.run_id = parsed_message.get('run_id')
            # Store context for potential future use (e.g., schema registry lookups)
            self._message_context = {
                'run_id': self.run_id,
                'training_upload_id': parsed_message.get('training_upload_id'),
                'upload_id': parsed_message.get('upload_id'),  # Backward compatibility
                'bank_id': parsed_message.get('bank_id'),
                'date': parsed_message.get('date'),
                'bronze_blob_path': file_path
            }
        else:
            self._message_context = None
        
        # Check deduplication before processing
        system_name_short = "schema"
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
            evidence = []
            metadata = {}
            
            # Use format-specific detector if available
            format_detectors = {
                'csv': detect_csv_structure,
                'tsv': detect_tsv_structure,
                'json': detect_json_structure,
                'jsonl': detect_json_structure,
                'parquet': detect_parquet_structure,
                'excel': detect_excel_structure,
                'xlsx': detect_excel_structure,
                'xls': detect_excel_structure,
            }
            
            detector_func = format_detectors.get(format.lower())
            
            if detector_func:
                try:
                    # Call format-specific detector
                    structure_info = detector_func(
                        file_path=file_path,
                        datalake_client=self.datalake_client,
                        blob_client=self.blob_client,
                        introspection_result=introspection_result
                    )
                    
                    # Extract information from structure_info
                    encoding = structure_info.get('encoding', introspection_result.encoding or 'utf-8')
                    delimiter = structure_info.get('delimiter')
                    has_header = structure_info.get('has_header', True)
                    column_count = structure_info.get('column_count', 0)
                    row_count = structure_info.get('row_count', 0)
                    nested_structure = structure_info.get('nested_structure', False)
                    sheets = structure_info.get('sheets')
                    column_names = structure_info.get('column_names', [])
                    column_types = structure_info.get('column_types', {})
                    
                    # Handle confidence scores (new format returns dict, old format returns float)
                    confidence_scores = structure_info.get('confidence_scores', {})
                    if isinstance(confidence_scores, dict) and 'overall' in confidence_scores:
                        confidence = confidence_scores['overall']
                    elif isinstance(confidence_scores, dict):
                        # Calculate overall from individual scores if available
                        format_conf = confidence_scores.get('format_confidence', 0.8)
                        schema_conf = confidence_scores.get('schema_confidence', 0.8)
                        type_conf = confidence_scores.get('type_confidence', 0.7)
                        completeness_conf = confidence_scores.get('completeness_confidence', 0.7)
                        confidence = (format_conf * 0.3) + (schema_conf * 0.4) + (type_conf * 0.2) + (completeness_conf * 0.1)
                    else:
                        # Fallback to old format or default
                        confidence = structure_info.get('confidence', 0.8)
                    
                    evidence.extend(structure_info.get('evidence', []))
                    metadata.update(structure_info.get('metadata', {}))
                    # Store confidence scores in metadata if available
                    if isinstance(confidence_scores, dict):
                        metadata['confidence_scores'] = confidence_scores
                        
                except Exception as e:
                    # Fallback to basic detection
                    evidence.append(f"Format-specific detector failed: {str(e)}")
                    encoding = introspection_result.encoding or 'utf-8'
                    delimiter = None
                    has_header = True
                    column_count = 0
                    row_count = 0
                    nested_structure = False
                    sheets = None
                    column_names = None
                    column_types = None
                    confidence = 0.5
            else:
                # Basic detection for unsupported formats
                evidence.append(f"No format-specific detector for format: {format}")
                encoding = introspection_result.encoding or 'utf-8'
                delimiter = None
                has_header = True
                column_count = 0
                row_count = 0
                nested_structure = False
                sheets = None
                column_names = None
                column_types = None
                confidence = 0.3
            
            # Create the result
            result = SchemaDetectionResult(
                format=format,
                encoding=encoding,
                delimiter=delimiter,
                has_header=has_header,
                column_count=column_count,
                row_count=row_count,
                nested_structure=nested_structure,
                sheets=sheets,
                column_names=column_names,
                column_types=column_types,
                confidence=confidence,
                evidence=evidence,
                metadata=metadata,
                format_conflict=format_conflict,
                fallback_format=fallback_format
            )
            
            # Option B: Always perform full detection, then calculate hash and check/store cache
            bank_id = self._message_context.get('bank_id') if self._message_context else None
            if column_names and column_types and bank_id:
                try:
                    # Calculate schema hash
                    schema_hash = calculate_schema_hash(column_names, column_types)
                    
                    # Check cache (Redis then PostgreSQL)
                    cached_result = SchemaDetectionStore.get(bank_id, schema_hash)
                    if cached_result:
                        logger.info(f"Returning cached SchemaDetectionResult for bank_id: {bank_id}, schema_hash: {schema_hash}")
                        result = cached_result
                    else:
                        # Store result in cache
                        try:
                            SchemaDetectionStore.store(bank_id, schema_hash, result)
                            logger.info(f"Stored SchemaDetectionResult for bank_id: {bank_id}, schema_hash: {schema_hash}")
                        except Exception as e:
                            logger.warning(f"Failed to store SchemaDetectionResult in cache: {e}. Continuing with result.")
                except Exception as e:
                    logger.warning(f"Error during artifact reuse check for SchemaDetectionResult: {e}. Continuing with result.")
            
            # Record system completion in state tracker
            if self.state_tracker and self.run_id:
                try:
                    self.state_tracker.complete_system(
                        run_id=self.run_id,
                        system_name=system_name_short,
                        metadata={
                            "format": result.format,
                            "column_count": result.column_count,
                            "row_count": result.row_count,
                            "confidence": result.confidence
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
                        status=InternalStatus.SCHEMA_DETECTED,
                        result={
                            "format": result.format,
                            "column_count": result.column_count,
                            "row_count": result.row_count,
                            "confidence": result.confidence,
                            "format_conflict": result.format_conflict,
                            "fallback_format": result.fallback_format
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
                            "file_path": file_path
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
            
            logger.error(f"[run_id={self.run_id}] Error in schema detection: {error_message}", exc_info=True)
            raise