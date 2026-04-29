"""
FileIntrospector system class
Performs cheap file introspection (reads small bytes only)
"""

import zipfile
import gzip
import tarfile
import bz2
import logging
import traceback
from typing import Dict, Any, Optional

from azure.core.exceptions import ResourceNotFoundError
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from charset_normalizer import detect as detect_encoding

# Use absolute import for better compatibility with pytest
try:
    from system_interfaces import IFileIntrospectionSystem, FileIntrospectionResult
    from utils.service_bus_parser import parse_data_ingested_message
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
except ImportError:
    # Fallback for relative import if running as package
    from ..system_interfaces import IFileIntrospectionSystem, FileIntrospectionResult
    from ..utils.service_bus_parser import parse_data_ingested_message
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError

logger = logging.getLogger(__name__)


class FileIntrospector(IFileIntrospectionSystem):
    """
    File Introspection System
    Performs cheap probes on file metadata before reading significant data
    """
    
    # Magic bytes for format detection
    MAGIC_BYTES = {
        b'PK\x03\x04': 'zip',
        b'PK\x05\x06': 'zip',  # Empty ZIP
        b'PK\x07\x08': 'zip',  # Spanned ZIP
        b'\x1f\x8b': 'gzip',
        b'BZ': 'bz2',
        b'\xfd7zXZ\x00': 'xz',
        b'ustar': 'tar',
        b'GNUtar': 'tar',
    }
    
    # BOM markers for encoding detection
    BOM_MARKERS = {
        b'\xef\xbb\xbf': 'utf-8',
        b'\xff\xfe': 'utf-16-le',
        b'\xfe\xff': 'utf-16-be',
        b'\xff\xfe\x00\x00': 'utf-32-le',
        b'\x00\x00\xfe\xff': 'utf-32-be',
    }
    
    def __init__(
        self, 
        datalake_client,
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None,
        run_id: Optional[str] = None,
        state_tracker = None
    ):
        """
        Initialize File Introspector
        
        Args:
            datalake_client: Azure Data Lake Gen2 client (DataLakeFileClient or similar)
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
            run_id: Run ID for tracking and filtering
            state_tracker: Optional PipelineStateTracker instance
        """
        self.datalake_client = datalake_client
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
    
    def introspect_file(
        self,
        file_path: str,
        sample_bytes: int = 8192,
        parsed_message: Optional[Dict[str, Any]] = None
    ) -> FileIntrospectionResult:
        """
        Perform cheap file introspection (read only small bytes/metadata)
        
        Args:
            file_path: Path to file in Data Lake (or use parsed_message.bronze_blob_path)
            sample_bytes: Number of bytes to sample (default: 8KB)
            parsed_message: Optional parsed Service Bus message dict with bronze_blob_path
        
        Returns:
            FileIntrospectionResult with container, compression, encoding, etc.
        """
        system_name = "System 0: File Introspection"
        
        # Extract file_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            file_path = parsed_message.get('bronze_blob_path', file_path)
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
                'bronze_blob_path': file_path
            }
        else:
            self._message_context = None
        
        # Check deduplication before processing
        system_name_short = "introspection"
        if self.state_tracker and self.run_id and self._message_context:
            try:
                training_upload_id = self._message_context.get('training_upload_id') or self._message_context.get('upload_id')
                # Note: message_id would come from Service Bus message, but we don't have it here
                # For now, we'll check if system was already completed
                if self.state_tracker.check_system_already_completed(self.run_id, system_name_short):
                    logger.warning(f"[run_id={self.run_id}] System {system_name_short} already completed. Skipping.")
                    # Return a cached result or raise an exception - for now, we'll continue
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
            logger.info(f"[FileIntrospector] Getting file client for path='{file_path}'")
            logger.info(f"[FileIntrospector] datalake_client type: {type(self.datalake_client).__name__}")
            
            # Read file metadata and sample bytes
            file_client = self.datalake_client.get_file_client(file_path)
            logger.info(f"[FileIntrospector] Retrieved file client, type: {type(file_client).__name__}")
            logger.info("[FileIntrospector] Fetching file properties (with 15s timeout)...")
            
            # Use ThreadPoolExecutor to add a timeout wrapper around get_file_properties
            # since the Azure SDK may not support timeout parameter directly
            def _get_properties():
                logger.info("[FileIntrospector] Inside _get_properties() - calling get_file_properties()")
                try:
                    props = file_client.get_file_properties()
                    logger.info("[FileIntrospector] get_file_properties() returned successfully")
                    return props
                except Exception as inner_e:
                    logger.error(f"[FileIntrospector] get_file_properties() raised exception: {inner_e}", exc_info=True)
                    raise
            
            try:
                logger.info("[FileIntrospector] Starting ThreadPoolExecutor with 15s timeout")
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_get_properties)
                    logger.info("[FileIntrospector] Submitted task, waiting for result with timeout=15s")
                    file_properties = future.result(timeout=15)  # 15 second timeout
                    logger.info("[FileIntrospector] Successfully got file_properties from executor")
            except FuturesTimeoutError:
                logger.error("[FileIntrospector] get_file_properties timed out after 15 seconds")
                logger.error("[FileIntrospector] This likely indicates a Data Lake connectivity or authentication issue")
                raise TimeoutError("get_file_properties timed out after 15 seconds - check Data Lake connectivity and authentication")
            except Exception as e:
                ctx = self._message_context or {}
                if isinstance(e, ResourceNotFoundError) and getattr(e, "error_code", None) == "BlobNotFound":
                    logger.warning(
                        "[FileIntrospector] Bronze blob not found at path=%r "
                        "(training_upload_id=%s, run_id=%s). "
                        "The Service Bus message may be stale or the file was never written to this account/container.",
                        file_path,
                        ctx.get("training_upload_id") or ctx.get("upload_id"),
                        self.run_id,
                    )
                else:
                    logger.error(f"[FileIntrospector] get_file_properties failed: {e}", exc_info=True)
                raise
            
            file_size = file_properties.size
            logger.info(f"[FileIntrospector] File size bytes={file_size}")
            
            # Read sample bytes (min of sample_bytes or file_size)
            read_size = min(sample_bytes, file_size)
            logger.info(f"[FileIntrospector] Downloading first {read_size} bytes from Data Lake (with 30s timeout)")
            
            # Use ThreadPoolExecutor to add a timeout wrapper around download_file
            def _download_file():
                return file_client.download_file(offset=0, length=read_size).readall()
            
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_download_file)
                    sample_data = future.result(timeout=30)  # 30 second timeout
            except FuturesTimeoutError:
                logger.error("[FileIntrospector] download_file timed out after 30 seconds")
                raise TimeoutError("download_file timed out after 30 seconds - check Data Lake connectivity and authentication")
            except Exception as e:
                logger.error(f"[FileIntrospector] download_file failed: {e}", exc_info=True)
                raise
            
            logger.info(f"[FileIntrospector] Downloaded {len(sample_data)} bytes from Data Lake")
            
            # Extract magic bytes (first 16 bytes for format detection)
            magic_bytes = sample_data[:16] if len(sample_data) >= 16 else sample_data
            logger.info("[FileIntrospector] Extracted magic bytes for format detection")
            
            # Detect container and compression
            container_info = self.detect_container_and_compression_from_bytes(sample_data, file_path)
            logger.info(f"[FileIntrospector] Container/compression info: {container_info}")
            
            # Detect encoding (only for text files)
            encoding_info = self.detect_text_encoding_from_bytes(sample_data)
            logger.info(f"[FileIntrospector] Encoding info: {encoding_info}")
            
            # Estimate record boundaries
            boundary_info = self.estimate_record_boundaries_from_bytes(sample_data)
            logger.info(f"[FileIntrospector] Boundary info: {boundary_info}")
            
            # Determine I/O hints
            io_hints = self._determine_io_hints(
                file_size=file_size,
                container_type=container_info.get('container_type'),
                compression_type=container_info.get('compression_type')
            )
            
            # Format hints (delimiter candidates, etc.)
            format_hints = self._extract_format_hints(sample_data)
            
            result = FileIntrospectionResult(
                container_type=container_info.get('container_type'),
                compression_type=container_info.get('compression_type'),
                encoding=encoding_info.get('encoding'),
                has_bom=encoding_info.get('has_bom', False),
                newline_type=boundary_info.get('newline_type'),
                file_size_bytes=file_size,
                magic_bytes=magic_bytes,
                format_hints=format_hints,
                io_hints=io_hints
            )
            
            # Record system completion in state tracker
            if self.state_tracker and self.run_id:
                try:
                    self.state_tracker.complete_system(
                        run_id=self.run_id,
                        system_name=system_name_short,
                        metadata={
                            "file_size_bytes": file_size,
                            "encoding": result.encoding,
                            "compression_type": result.compression_type,
                            "container_type": result.container_type,
                            "has_bom": result.has_bom
                        }
                    )
                    logger.debug(f"[run_id={self.run_id}] Recorded system completion: {system_name_short}")
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to record system completion: {e}")
            
            # Publish system complete
            if writer and self._message_context:
                try:
                    logger.info(f"[run_id={self.run_id}] Publishing system complete message for {system_name}")
                    writer.publish_system_complete(
                        training_upload_id=self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        status=InternalStatus.INTROSPECTION_COMPLETE,
                        result={
                            "file_size_bytes": file_size,
                            "encoding": result.encoding,
                            "compression_type": result.compression_type,
                            "container_type": result.container_type,
                            "has_bom": result.has_bom
                        },
                        run_id=self.run_id
                    )
                    logger.info(f"[run_id={self.run_id}] Successfully published system complete message for {system_name}")
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to publish system complete message: {e}", exc_info=True)
            
            logger.info(f"[run_id={self.run_id}] File introspection completed successfully, returning result")
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
                    training_upload_id = self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')
                    writer.publish_system_failed(
                        training_upload_id=training_upload_id,
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
            
            logger.error(f"[run_id={self.run_id}] Error in file introspection: {error_message}", exc_info=True)
            raise
    
    def detect_container_and_compression(
        self,
        file_path: str
    ) -> Dict[str, Any]:
        """
        Detect archive/compression wrappers (ZIP/TAR/GZIP/etc.)
        
        Args:
            file_path: Path to file in Data Lake
        
        Returns:
            Dictionary with container_type, compression_type, etc.
        """
        # Read first 512 bytes to detect container/compression
        file_client = self.datalake_client.get_file_client(file_path)
        sample_data = file_client.download_file(offset=0, length=512).readall()
        
        return self.detect_container_and_compression_from_bytes(sample_data, file_path)
    
    def detect_container_and_compression_from_bytes(
        self,
        sample_data: bytes,
        file_path: str
    ) -> Dict[str, Any]:
        """
        Detect container/compression from bytes
        
        Args:
            sample_data: Sample bytes from file
            file_path: File path (for extension-based detection)
        
        Returns:
            Dictionary with container_type, compression_type, etc.
        """
        container_type = None
        compression_type = None
        
        # Check magic bytes
        for magic, format_type in self.MAGIC_BYTES.items():
            if sample_data.startswith(magic):
                if format_type in ['zip', 'tar']:
                    container_type = format_type
                elif format_type in ['gzip', 'bz2', 'xz']:
                    compression_type = format_type
                break
        
        # Additional checks using file extension and content
        if not container_type and not compression_type:
            file_ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
            
            # Check if it's a ZIP file (try to open it)
            if file_ext == 'zip' or sample_data.startswith(b'PK'):
                try:
                    # Try to detect ZIP structure
                    if len(sample_data) >= 30:
                        # ZIP local file header signature
                        if sample_data[0:2] == b'PK' and sample_data[2:4] in [b'\x03\x04', b'\x05\x06', b'\x07\x08']:
                            container_type = 'zip'
                except:
                    pass
            
            # Check if it's a GZIP file
            if file_ext in ['gz', 'gzip'] or sample_data.startswith(b'\x1f\x8b'):
                compression_type = 'gzip'
            
            # Check if it's a TAR file
            if file_ext in ['tar']:
                # TAR files have specific structure at offset 257
                if len(sample_data) > 257:
                    if sample_data[257:262] == b'ustar' or sample_data[257:263] == b'GNUtar':
                        container_type = 'tar'
        
        return {
            'container_type': container_type,
            'compression_type': compression_type,
            'is_compressed': compression_type is not None,
            'is_container': container_type is not None
        }
    
    def detect_text_encoding(
        self,
        file_path: str,
        sample_bytes: int = 8192
    ) -> Dict[str, Any]:
        """
        Identify encoding, BOM presence, and mixed-encoding risk
        
        Args:
            file_path: Path to file in Data Lake
            sample_bytes: Number of bytes to sample
        
        Returns:
            Dictionary with encoding, has_bom, etc.
        """
        file_client = self.datalake_client.get_file_client(file_path)
        file_properties = file_client.get_file_properties()
        read_size = min(sample_bytes, file_properties.size)
        sample_data = file_client.download_file(offset=0, length=read_size).readall()
        
        return self.detect_text_encoding_from_bytes(sample_data)
    
    def detect_text_encoding_from_bytes(
        self,
        sample_data: bytes
    ) -> Dict[str, Any]:
        """
        Detect encoding from bytes
        
        Args:
            sample_data: Sample bytes from file
        
        Returns:
            Dictionary with encoding, has_bom, confidence, etc.
        """
        if len(sample_data) == 0:
            return {
                'encoding': None,
                'has_bom': False,
                'confidence': 0.0,
                'is_binary': True
            }
        
        # Check for BOM markers
        has_bom = False
        bom_encoding = None
        
        for bom, encoding in self.BOM_MARKERS.items():
            if sample_data.startswith(bom):
                has_bom = True
                bom_encoding = encoding
                break
        
        # Use charset-normalizer for encoding detection
        # Remove BOM if present for detection
        detection_data = sample_data
        if has_bom:
            bom_bytes = next(bom for bom in self.BOM_MARKERS.keys() if sample_data.startswith(bom))
            detection_data = sample_data[len(bom_bytes):]
        
        # Detect encoding using charset-normalizer
        result = detect_encoding(detection_data)
        
        # charset_normalizer returns a dict-like object or a CharsetMatch object
        if result:
            if isinstance(result, dict):
                detected_encoding = result.get('encoding')
                confidence = result.get('confidence', 0.0)
            else:
                # It's a CharsetMatch object
                detected_encoding = result.encoding if hasattr(result, 'encoding') else None
                confidence = result.percent_confidence / 100.0 if hasattr(result, 'percent_confidence') else (result.confidence if hasattr(result, 'confidence') else 0.0)
        else:
            detected_encoding = None
            confidence = 0.0
        
        # Prefer BOM encoding if present (more reliable)
        final_encoding = bom_encoding if has_bom else detected_encoding
        
        # Check if file is likely binary (high percentage of non-text bytes)
        is_binary = self._is_likely_binary(sample_data)
        
        return {
            'encoding': final_encoding,
            'has_bom': has_bom,
            'confidence': confidence if final_encoding else 0.0,
            'is_binary': is_binary,
            'detected_encoding': detected_encoding,
            'bom_encoding': bom_encoding
        }
    
    def estimate_record_boundaries(
        self,
        file_path: str,
        sample_bytes: int = 8192
    ) -> Dict[str, Any]:
        """
        Determine record boundaries (newline-delimited, fixed-width, etc.)
        
        Args:
            file_path: Path to file in Data Lake
            sample_bytes: Number of bytes to sample
        
        Returns:
            Dictionary with newline_type, record_length_hint, etc.
        """
        file_client = self.datalake_client.get_file_client(file_path)
        file_properties = file_client.get_file_properties()
        read_size = min(sample_bytes, file_properties.size)
        sample_data = file_client.download_file(offset=0, length=read_size).readall()
        
        return self.estimate_record_boundaries_from_bytes(sample_data)
    
    def estimate_record_boundaries_from_bytes(
        self,
        sample_data: bytes
    ) -> Dict[str, Any]:
        """
        Estimate record boundaries from bytes
        
        Args:
            sample_data: Sample bytes from file
        
        Returns:
            Dictionary with newline_type, record_length_hint, delimiter_hints, etc.
        """
        if len(sample_data) == 0:
            return {
                'newline_type': None,
                'record_length_hint': None,
                'delimiter_hints': [],
                'boundary_type': 'unknown'
            }
        
        # Detect newline type
        newline_type = self._detect_newline_type(sample_data)
        
        # Estimate record length (for fixed-width files)
        record_length_hint = self._estimate_record_length(sample_data, newline_type)
        
        # Detect delimiter candidates (for delimited files)
        delimiter_hints = self._detect_delimiter_candidates(sample_data, newline_type)
        
        # Determine boundary type
        boundary_type = self._determine_boundary_type(
            newline_type=newline_type,
            record_length_hint=record_length_hint,
            delimiter_hints=delimiter_hints
        )
        
        return {
            'newline_type': newline_type,
            'record_length_hint': record_length_hint,
            'delimiter_hints': delimiter_hints,
            'boundary_type': boundary_type
        }
    
    def _detect_newline_type(self, sample_data: bytes) -> Optional[str]:
        """Detect newline type (\n, \r\n, \r)"""
        if b'\r\n' in sample_data:
            return '\r\n'
        elif b'\n' in sample_data:
            return '\n'
        elif b'\r' in sample_data:
            return '\r'
        return None
    
    def _estimate_record_length(self, sample_data: bytes, newline_type: Optional[str]) -> Optional[int]:
        """Estimate record length for fixed-width files"""
        if not newline_type:
            return None
        
        # Split by newline and check if lengths are consistent
        try:
            text = sample_data.decode('utf-8', errors='ignore')
            lines = text.split(newline_type)
            if len(lines) < 3:
                return None
            
            # Get lengths of first few lines (skip empty lines)
            line_lengths = [len(line) for line in lines[:10] if line.strip()]
            if len(line_lengths) < 3:
                return None
            
            # Check if lengths are consistent (within 5% variance)
            avg_length = sum(line_lengths) / len(line_lengths)
            variances = [abs(len(line) - avg_length) / avg_length for line in lines[:10] if line.strip()]
            
            if all(v < 0.05 for v in variances[:5]):  # First 5 lines are consistent
                return int(avg_length)
        except:
            pass
        
        return None
    
    def _detect_delimiter_candidates(self, sample_data: bytes, newline_type: Optional[str]) -> list:
        """Detect delimiter candidates (comma, tab, pipe, semicolon)"""
        if not newline_type:
            return []
        
        try:
            text = sample_data.decode('utf-8', errors='ignore')
            lines = [line for line in text.split(newline_type)[:10] if line.strip()]
            
            if len(lines) < 2:
                return []
            
            # Count delimiter frequency in first few lines
            delimiters = [',', '\t', '|', ';', ' ']
            delimiter_counts = {delim: 0 for delim in delimiters}
            
            for line in lines[:5]:
                for delim in delimiters:
                    delimiter_counts[delim] += line.count(delim)
            
            # Return delimiters that appear consistently
            candidates = []
            for delim, count in delimiter_counts.items():
                if count > 0 and count >= len(lines) * 0.8:  # Appears in 80%+ of lines
                    candidates.append(delim)
            
            return sorted(candidates, key=lambda x: delimiter_counts[x], reverse=True)
        except:
            return []
    
    def _determine_boundary_type(
        self,
        newline_type: Optional[str],
        record_length_hint: Optional[int],
        delimiter_hints: list
    ) -> str:
        """Determine boundary type (newline-delimited, fixed-width, etc.)"""
        # Prioritize delimiter detection over fixed-width (delimiters are more common)
        if newline_type and delimiter_hints:
            return 'delimited'
        elif record_length_hint:
            return 'fixed-width'
        elif newline_type:
            return 'newline-delimited'
        else:
            return 'unknown'
    
    def _is_likely_binary(self, sample_data: bytes) -> bool:
        """Check if file is likely binary (high percentage of non-text bytes)"""
        if len(sample_data) == 0:
            return True
        
        # Count null bytes and control characters (excluding common whitespace)
        null_count = sample_data.count(b'\x00')
        control_chars = sum(1 for b in sample_data if b < 32 and b not in [9, 10, 13])  # Exclude tab, LF, CR
        
        # If more than 5% null bytes or 10% control chars, likely binary
        null_ratio = null_count / len(sample_data)
        control_ratio = control_chars / len(sample_data)
        
        return null_ratio > 0.05 or control_ratio > 0.10
    
    def _determine_io_hints(
        self,
        file_size: int,
        container_type: Optional[str],
        compression_type: Optional[str]
    ) -> Dict[str, Any]:
        """Determine I/O hints (streaming vs random access, chunk sizes)"""
        # Large files should use streaming
        use_streaming = file_size > 10 * 1024 * 1024  # 10MB
        
        # Compressed files should use streaming
        if compression_type:
            use_streaming = True
        
        # Container files (ZIP, TAR) need random access for directory reading
        if container_type:
            use_streaming = False
        
        # Recommended chunk size
        if use_streaming:
            chunk_size = 1024 * 1024  # 1MB chunks for streaming
        else:
            chunk_size = file_size  # Read entire file for random access
        
        return {
            'use_streaming': use_streaming,
            'chunk_size': chunk_size,
            'random_access': not use_streaming,
            'recommended_reader': 'streaming' if use_streaming else 'random_access'
        }
    
    def _extract_format_hints(self, sample_data: bytes) -> Dict[str, Any]:
        """Extract format-specific hints (delimiter candidates, etc.)"""
        hints = {}
        
        # Check for common file format signatures
        if sample_data.startswith(b'{') or sample_data.startswith(b'['):
            hints['possible_json'] = True
        elif sample_data.startswith(b'<?xml') or sample_data.startswith(b'<'):
            hints['possible_xml'] = True
        elif b'<?xml' in sample_data[:100]:
            hints['possible_xml'] = True
        
        # Check for CSV-like patterns
        if b',' in sample_data[:100]:
            hints['possible_csv'] = True
        
        # Check for Excel-like patterns (ZIP structure with specific files)
        if sample_data.startswith(b'PK') and b'[Content_Types].xml' in sample_data[:1024]:
            hints['possible_excel'] = True
        
        return hints
