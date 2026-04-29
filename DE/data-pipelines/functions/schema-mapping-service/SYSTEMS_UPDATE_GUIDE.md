# Systems 1-4 Update Guide

This document provides exact code changes needed to add status publishing to Systems 1-4.

**Reference:** System 0 (FileIntrospector) is already complete and can be used as a template.

---

## System 1: SchemaDetector

### File: `systems/schema_detector.py`

#### 1. Update `__init__` method (around line 93)

**FIND:**
```python
    def __init__(self, datalake_client, blob_client=None):
        """
        Initialize Schema Detector
        
        Args:
            datalake_client: Azure Data Lake Gen2 client (FileSystemClient)
            blob_client: Optional Azure Blob Storage client for fallback
        """
        self.datalake_client = datalake_client
        self.blob_client = blob_client
```

**REPLACE WITH:**
```python
    def __init__(
        self, 
        datalake_client, 
        blob_client=None,
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None
    ):
        """
        Initialize Schema Detector
        
        Args:
            datalake_client: Azure Data Lake Gen2 client (FileSystemClient)
            blob_client: Optional Azure Blob Storage client for fallback
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
        """
        self.datalake_client = datalake_client
        self.blob_client = blob_client
        self.service_bus_writer = service_bus_writer
        self.key_vault_url = key_vault_url
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
```

#### 2. Update `detect_schema` method (around line 210)

**FIND:**
```python
        # Extract file_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            file_path = parsed_message.get('bronze_blob_path', file_path)
            # Store context for potential future use (e.g., schema registry lookups)
            self._message_context = {
                'upload_id': parsed_message.get('upload_id'),
                'bank_id': parsed_message.get('bank_id'),
                'date': parsed_message.get('date')
            }
        else:
            self._message_context = None
        evidence = []
        metadata = {}
```

**REPLACE WITH:**
```python
        system_name = "System 1: Schema Detection"
        
        # Extract file_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            file_path = parsed_message.get('bronze_blob_path', file_path)
            # Store context for potential future use (e.g., schema registry lookups)
            self._message_context = {
                'upload_id': parsed_message.get('upload_id'),
                'bank_id': parsed_message.get('bank_id'),
                'date': parsed_message.get('date'),
                'bronze_blob_path': file_path
            }
        else:
            self._message_context = None
        
        # Publish system starting
        writer = self._get_service_bus_writer()
        if writer and self._message_context:
            try:
                writer.publish_system_starting(
                    upload_id=self._message_context.get('upload_id', 'unknown'),
                    bank_id=self._message_context.get('bank_id', 'unknown'),
                    system_name=system_name
                )
            except Exception as e:
                logger.warning(f"Failed to publish system starting message: {e}")
        
        try:
            evidence = []
            metadata = {}
```

#### 3. Update artifact reuse section and add completion publishing (around line 343)

**FIND:**
```python
        # Option B: Always perform full detection, then calculate hash and check/store cache
        if column_names and column_types:
            try:
                # Calculate schema hash
                schema_hash = calculate_schema_hash(column_names, column_types)
                
                # Check cache (Redis then PostgreSQL)
                cached_result = SchemaDetectionStore.get(bank_id, schema_hash)
                if cached_result:
                    logger.info(f"Returning cached SchemaDetectionResult for bank_id: {bank_id}, schema_hash: {schema_hash}")
                    return cached_result
                
                # Store result in cache
                try:
                    SchemaDetectionStore.store(bank_id, schema_hash, result)
                    logger.info(f"Stored SchemaDetectionResult for bank_id: {bank_id}, schema_hash: {schema_hash}")
                except Exception as e:
                    logger.warning(f"Failed to store SchemaDetectionResult in cache: {e}. Continuing with result.")
            except Exception as e:
                logger.warning(f"Error during artifact reuse check for SchemaDetectionResult: {e}. Continuing with result.")
        
        return result
```

**REPLACE WITH:**
```python
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
        
        # Publish system complete
        if writer and self._message_context:
            try:
                writer.publish_system_complete(
                    upload_id=self._message_context.get('upload_id', 'unknown'),
                    bank_id=self._message_context.get('bank_id', 'unknown'),
                    system_name=system_name,
                    status=InternalStatus.SCHEMA_DETECTED,
                    result={
                        "format": result.format,
                        "column_count": result.column_count,
                        "row_count": result.row_count,
                        "confidence": result.confidence
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to publish system complete message: {e}")
        
        return result
        
        except Exception as e:
            # Publish error (both internal and backend)
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            if writer and self._message_context:
                try:
                    # Internal error (detailed)
                    writer.publish_system_failed(
                        upload_id=self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        error={
                            "message": error_message,
                            "type": error_type,
                            "stack_trace": stack_trace,
                            "file_path": file_path
                        }
                    )
                    
                    # Backend error (user-friendly)
                    training_upload_id = self._message_context.get('upload_id', 'unknown')
                    writer.publish_backend_error(
                        training_upload_id=training_upload_id,
                        error_type=error_type,
                        error_message=error_message,
                        system_name=system_name,
                        stack_trace=stack_trace
                    )
                except Exception as pub_error:
                    logger.error(f"Failed to publish error messages: {pub_error}")
            
            logger.error(f"Error in schema detection: {error_message}", exc_info=True)
            raise
```

---

## System 2: DataSampler

### File: `systems/data_sampler.py`

#### 1. Add imports at the top (after existing imports)

**FIND:**
```python
from .format_detectors.common import read_file_sample, decode_text
```

**ADD AFTER:**
```python
import traceback

try:
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
except ImportError:
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
```

#### 2. Update `__init__` method (around line 58)

**FIND:**
```python
    def __init__(self, datalake_client, blob_client=None):
        """
        Initialize Data Sampler
        
        Args:
            datalake_client: Azure Data Lake Gen2 client (FileSystemClient)
            blob_client: Optional Azure Blob Storage client for fallback
        """
        self.datalake_client = datalake_client
        self.blob_client = blob_client
```

**REPLACE WITH:**
```python
    def __init__(
        self, 
        datalake_client, 
        blob_client=None,
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None
    ):
        """
        Initialize Data Sampler
        
        Args:
            datalake_client: Azure Data Lake Gen2 client (FileSystemClient)
            blob_client: Optional Azure Blob Storage client for fallback
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
        """
        self.datalake_client = datalake_client
        self.blob_client = blob_client
        self.service_bus_writer = service_bus_writer
        self.key_vault_url = key_vault_url
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
```

#### 3. Update `load_and_sample_from_datalake` method (around line 69)

**FIND:**
```python
        # Extract bronze_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            bronze_path = parsed_message.get('bronze_blob_path', bronze_path)
            # Store context for potential future use (e.g., logging, metadata)
            self._message_context = {
                'upload_id': parsed_message.get('upload_id'),
                'bank_id': parsed_message.get('bank_id'),
                'date': parsed_message.get('date')
            }
        else:
            self._message_context = None
        metadata = {
```

**REPLACE WITH:**
```python
        system_name = "System 2: Data Sampling"
        
        # Extract bronze_path from parsed_message if provided (overrides parameter)
        if parsed_message:
            bronze_path = parsed_message.get('bronze_blob_path', bronze_path)
            # Store context for potential future use (e.g., logging, metadata)
            self._message_context = {
                'upload_id': parsed_message.get('upload_id'),
                'bank_id': parsed_message.get('bank_id'),
                'date': parsed_message.get('date'),
                'bronze_blob_path': bronze_path
            }
        else:
            self._message_context = None
        
        # Publish system starting
        writer = self._get_service_bus_writer()
        if writer and self._message_context:
            try:
                writer.publish_system_starting(
                    upload_id=self._message_context.get('upload_id', 'unknown'),
                    bank_id=self._message_context.get('bank_id', 'unknown'),
                    system_name=system_name
                )
            except Exception as e:
                logger.warning(f"Failed to publish system starting message: {e}")
        
        try:
            metadata = {
```

#### 4. Find the return statement at the end of `load_and_sample_from_datalake` and add completion publishing

**FIND:** (Near the end of the method, before the final return)
```python
        return DataSamplingResult(
            samples=samples,
            metadata=metadata,
            format=format,
            encoding=encoding,
            total_row_count=total_rows,
            column_count=column_count,
            sampling_strategy=sampling_strategy
        )
```

**REPLACE WITH:**
```python
        result = DataSamplingResult(
            samples=samples,
            metadata=metadata,
            format=format,
            encoding=encoding,
            total_row_count=total_rows,
            column_count=column_count,
            sampling_strategy=sampling_strategy
        )
        
        # Publish system complete
        if writer and self._message_context:
            try:
                writer.publish_system_complete(
                    upload_id=self._message_context.get('upload_id', 'unknown'),
                    bank_id=self._message_context.get('bank_id', 'unknown'),
                    system_name=system_name,
                    status=InternalStatus.SAMPLING_COMPLETE,
                    result={
                        "format": format,
                        "total_row_count": total_rows,
                        "column_count": column_count,
                        "sampling_strategy": sampling_strategy,
                        "sample_count": len(samples)
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to publish system complete message: {e}")
        
        return result
        
        except Exception as e:
            # Publish error (both internal and backend)
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            if writer and self._message_context:
                try:
                    # Internal error (detailed)
                    writer.publish_system_failed(
                        upload_id=self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        error={
                            "message": error_message,
                            "type": error_type,
                            "stack_trace": stack_trace,
                            "bronze_path": bronze_path
                        }
                    )
                    
                    # Backend error (user-friendly)
                    training_upload_id = self._message_context.get('upload_id', 'unknown')
                    writer.publish_backend_error(
                        training_upload_id=training_upload_id,
                        error_type=error_type,
                        error_message=error_message,
                        system_name=system_name,
                        stack_trace=stack_trace
                    )
                except Exception as pub_error:
                    logger.error(f"Failed to publish error messages: {pub_error}")
            
            logger.error(f"Error in data sampling: {error_message}", exc_info=True)
            raise
```

**NOTE:** Make sure the entire method body (after the try statement) is properly indented, and the except block is at the same indentation level as the try.

---

## System 3: DataAnalyzer

### File: `systems/data_analyzer.py`

#### 1. Update imports (around line 20)

**FIND:**
```python
    from utils.service_bus_client import ServiceBusPublisher, ServiceBusClientError
```

**REPLACE WITH:**
```python
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
```

**ALSO FIND:**
```python
    from ..utils.service_bus_client import ServiceBusPublisher, ServiceBusClientError
```

**REPLACE WITH:**
```python
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
```

#### 2. Update `__init__` method (around line 54)

**FIND:**
```python
    def __init__(
        self,
        service_bus_publisher: Optional[ServiceBusPublisher] = None,
        key_vault_url: Optional[str] = None
    ):
        """
        Initialize Data Analyzer
        
        Args:
            service_bus_publisher: Optional Service Bus publisher (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
        """
        self.service_bus_publisher = service_bus_publisher
        self.key_vault_url = key_vault_url
        self.date_format_detector = DateFormatDetector()
        self._message_context: Optional[Dict[str, Any]] = None
    
    def _get_service_bus_publisher(self) -> Optional[ServiceBusPublisher]:
        """Get or create Service Bus publisher"""
        if self.service_bus_publisher:
            return self.service_bus_publisher
        
        if self.key_vault_url:
            try:
                return ServiceBusPublisher(key_vault_url=self.key_vault_url)
            except Exception as e:
                logger.warning(f"Failed to create Service Bus publisher: {e}")
                return None
        
        return None
```

**REPLACE WITH:**
```python
    def __init__(
        self,
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None
    ):
        """
        Initialize Data Analyzer
        
        Args:
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
        """
        self.service_bus_writer = service_bus_writer
        self.key_vault_url = key_vault_url
        self.date_format_detector = DateFormatDetector()
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
```

#### 3. Update `_publish_error` method (around line 85)

**FIND:**
```python
    def _publish_error(
        self,
        error: Exception,
        system_name: str = "System 3: Data Analysis"
    ) -> None:
        """Publish error to Service Bus"""
        publisher = self._get_service_bus_publisher()
        if not publisher:
            return
        
        try:
            upload_id = self._message_context.get('upload_id', 'unknown') if self._message_context else 'unknown'
            bank_id = self._message_context.get('bank_id', 'unknown') if self._message_context else 'unknown'
            bronze_path = self._message_context.get('bronze_blob_path') if self._message_context else None
            
            publisher.publish_failure(
                upload_id=upload_id,
                bank_id=bank_id,
                system_name=system_name,
                error_message=str(error),
                error_type=type(error).__name__,
                stack_trace=traceback.format_exc(),
                bronze_blob_path=bronze_path
            )
        except Exception as e:
            logger.error(f"Failed to publish error to Service Bus: {e}")
```

**REPLACE WITH:**
```python
    def _publish_error(
        self,
        error: Exception,
        system_name: str = "System 3: Data Analysis"
    ) -> None:
        """Publish error to Service Bus (both internal and backend)"""
        writer = self._get_service_bus_writer()
        if not writer or not self._message_context:
            return
        
        try:
            upload_id = self._message_context.get('upload_id', 'unknown')
            bank_id = self._message_context.get('bank_id', 'unknown')
            error_type = type(error).__name__
            error_message = str(error)
            stack_trace = traceback.format_exc()
            
            # Internal error (detailed)
            writer.publish_system_failed(
                upload_id=upload_id,
                bank_id=bank_id,
                system_name=system_name,
                error={
                    "message": error_message,
                    "type": error_type,
                    "stack_trace": stack_trace,
                    "bronze_blob_path": self._message_context.get('bronze_blob_path')
                }
            )
            
            # Backend error (user-friendly)
            writer.publish_backend_error(
                training_upload_id=upload_id,
                error_type=error_type,
                error_message=error_message,
                system_name=system_name,
                stack_trace=stack_trace
            )
        except Exception as e:
            logger.error(f"Failed to publish error to Service Bus: {e}")
```

#### 4. Update `analyze` method (around line 112)

**FIND:**
```python
        try:
            # Store message context
            bank_id = None
            if parsed_message:
                self._message_context = parsed_message
                bank_id = parsed_message.get('bank_id')
```

**REPLACE WITH:**
```python
        system_name = "System 3: Data Analysis"
        
        try:
            # Store message context
            bank_id = None
            if parsed_message:
                self._message_context = parsed_message
                bank_id = parsed_message.get('bank_id')
            
            # Publish system starting
            writer = self._get_service_bus_writer()
            if writer and self._message_context:
                try:
                    writer.publish_system_starting(
                        upload_id=self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name
                    )
                except Exception as e:
                    logger.warning(f"Failed to publish system starting message: {e}")
```

#### 5. Find the return statement at the end of `analyze` method and add completion publishing

**FIND:** (Near the end, before `return result`)
```python
            return result
            
        except Exception as e:
            logger.error(f"Error in comprehensive analysis: {e}")
            self._publish_error(e)
            raise
```

**REPLACE WITH:**
```python
            # Publish system complete
            if writer and self._message_context:
                try:
                    writer.publish_system_complete(
                        upload_id=self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        status=InternalStatus.ANALYSIS_COMPLETE,
                        result={
                            "column_count": len(result.data_types),
                            "total_columns_analyzed": len(result.missing_data),
                            "has_distributions": bool(result.distributions),
                            "has_formats": bool(result.formats)
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to publish system complete message: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in comprehensive analysis: {e}")
            self._publish_error(e, system_name)
            raise
```

---

## System 4: DatasetAnonymizer

### File: `systems/dataset_anonymizer.py`

#### 1. Add imports at the top (after existing imports)

**FIND:**
```python
from .pii_detector import PIIDetector
from .pii_anonymizer import PIIAnonymizer

logger = logging.getLogger(__name__)
```

**ADD AFTER:**
```python
import traceback

try:
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from utils.quality_report_aggregator import aggregate_quality_report
except ImportError:
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from ..utils.quality_report_aggregator import aggregate_quality_report
```

#### 2. Update `__init__` method (around line 44)

**FIND:**
```python
    def __init__(
        self,
        pii_detector: Optional[PIIDetector] = None,
        pii_anonymizer: Optional[PIIAnonymizer] = None,
        use_llm: bool = False
    ):
        """
        Args:
            pii_detector: Optional custom PIIDetector
            pii_anonymizer: Optional custom PIIAnonymizer
            use_llm: If True, attempt LLM-assisted detection (requires callback)
        """
        self.pii_detector = pii_detector or PIIDetector()
        self.pii_anonymizer = pii_anonymizer or PIIAnonymizer()
```

**REPLACE WITH:**
```python
    def __init__(
        self,
        pii_detector: Optional[PIIDetector] = None,
        pii_anonymizer: Optional[PIIAnonymizer] = None,
        use_llm: bool = False,
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None
    ):
        """
        Args:
            pii_detector: Optional custom PIIDetector
            pii_anonymizer: Optional custom PIIAnonymizer
            use_llm: If True, attempt LLM-assisted detection (requires callback)
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
        """
        self.pii_detector = pii_detector or PIIDetector()
        self.pii_anonymizer = pii_anonymizer or PIIAnonymizer()
        self.service_bus_writer = service_bus_writer
        self.key_vault_url = key_vault_url
        self._message_context: Optional[Dict[str, Any]] = None
        self._introspection_result: Optional[Dict[str, Any]] = None
        self._schema_result: Optional[Dict[str, Any]] = None
        self._sampling_result: Optional[Dict[str, Any]] = None
        self._analysis_result: Optional[Dict[str, Any]] = None
    
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
```

#### 3. Update `detect_pii` method (around line 59)

**FIND:**
```python
    def detect_pii(
        self,
        schema_result: SchemaDetectionResult,
        data_analysis_result: Optional[DataAnalysisResult] = None,
        bank_id: Optional[str] = None
    ) -> PIIDetectionResult:
```

**ADD AT THE BEGINNING OF THE METHOD (after the docstring):**
```python
        system_name = "System 4: Dataset Anonymizer"
        
        # Store context for quality report aggregation
        self._schema_result = schema_result
        self._analysis_result = data_analysis_result
        
        # Publish system starting
        writer = self._get_service_bus_writer()
        if writer and bank_id:
            try:
                # Try to get upload_id from message context if available
                upload_id = self._message_context.get('upload_id', 'unknown') if self._message_context else 'unknown'
                writer.publish_system_starting(
                    upload_id=upload_id,
                    bank_id=bank_id,
                    system_name=system_name
                )
            except Exception as e:
                logger.warning(f"Failed to publish system starting message: {e}")
        
        try:
```

**NOTE:** You'll need to wrap the existing method body in the try block and add an except block at the end.

#### 4. Find the return statement in `detect_pii` and add completion publishing

**FIND:** (Near the end of `detect_pii`, before `return result`)
```python
        return result
```

**REPLACE WITH:**
```python
        # Publish PII detection complete
        if writer and bank_id:
            try:
                upload_id = self._message_context.get('upload_id', 'unknown') if self._message_context else 'unknown'
                writer.publish_system_complete(
                    upload_id=upload_id,
                    bank_id=bank_id,
                    system_name=system_name,
                    status=InternalStatus.ANONYMIZATION_COMPLETE,
                    result={
                        "pii_fields_detected": len(result.pii_fields),
                        "anonymization_methods": len(result.anonymization_methods)
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to publish system complete message: {e}")
        
        return result
        
        except Exception as e:
            # Publish error (both internal and backend)
            error_type = type(e).__name__
            error_message = str(e)
            stack_trace = traceback.format_exc()
            
            if writer and bank_id:
                try:
                    upload_id = self._message_context.get('upload_id', 'unknown') if self._message_context else 'unknown'
                    # Internal error (detailed)
                    writer.publish_system_failed(
                        upload_id=upload_id,
                        bank_id=bank_id,
                        system_name=system_name,
                        error={
                            "message": error_message,
                            "type": error_type,
                            "stack_trace": stack_trace
                        }
                    )
                    
                    # Backend error (user-friendly)
                    writer.publish_backend_error(
                        training_upload_id=upload_id,
                        error_type=error_type,
                        error_message=error_message,
                        system_name=system_name,
                        stack_trace=stack_trace
                    )
                except Exception as pub_error:
                    logger.error(f"Failed to publish error messages: {pub_error}")
            
            logger.error(f"Error in PII detection: {error_message}", exc_info=True)
            raise
```

#### 5. Update `anonymize_dataframe` method to publish quality report after completion

**FIND:** (Near the end of `anonymize_dataframe`, before `return result`)
```python
        return AnonymizationResult(
            anonymized_data=anonymized_df,
            anonymization_mappings=anonymization_mappings,
            pii_fields=pii_fields
        )
```

**REPLACE WITH:**
```python
        result = AnonymizationResult(
            anonymized_data=anonymized_df,
            anonymization_mappings=anonymization_mappings,
            pii_fields=pii_fields
        )
        
        # After both detect_pii and anonymize_dataframe complete, aggregate quality report
        writer = self._get_service_bus_writer()
        if writer and self._message_context and self._schema_result and self._analysis_result:
            try:
                upload_id = self._message_context.get('upload_id', 'unknown')
                bank_id = self._message_context.get('bank_id')
                
                if bank_id:
                    # Aggregate quality report from Systems 0-4
                    quality_report = aggregate_quality_report(
                        introspection_result=self._introspection_result,
                        schema_result=self._schema_result.model_dump() if hasattr(self._schema_result, 'model_dump') else self._schema_result,
                        sampling_result=self._sampling_result,
                        analysis_result=self._analysis_result.model_dump() if hasattr(self._analysis_result, 'model_dump') else self._analysis_result,
                        pii_result=pii_fields.model_dump() if hasattr(pii_fields, 'model_dump') else pii_fields,
                        quality_score_method="weighted"
                    )
                    
                    # Publish quality report to backend
                    writer.publish_quality_report(
                        training_upload_id=upload_id,
                        quality_report=quality_report,
                        quality_score=quality_report.get('quality_score', 0.0)
                    )
                    
                    logger.info(f"Published quality report for upload_id: {upload_id}")
            except Exception as e:
                logger.error(f"Failed to publish quality report: {e}")
        
        return result
```

#### 6. Add method to store results from previous systems (for quality report)

**ADD THIS METHOD TO THE CLASS:**
```python
    def set_system_results(
        self,
        introspection_result: Optional[Dict[str, Any]] = None,
        schema_result: Optional[SchemaDetectionResult] = None,
        sampling_result: Optional[Dict[str, Any]] = None,
        analysis_result: Optional[DataAnalysisResult] = None,
        parsed_message: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Store results from previous systems for quality report aggregation
        
        Args:
            introspection_result: System 0 result
            schema_result: System 1 result
            sampling_result: System 2 result
            analysis_result: System 3 result
            parsed_message: Parsed Service Bus message
        """
        self._introspection_result = introspection_result
        self._schema_result = schema_result
        self._sampling_result = sampling_result
        self._analysis_result = analysis_result
        if parsed_message:
            self._message_context = parsed_message
```

---

## Summary

After applying all changes:

1. **System 1** - Status publishing in `detect_schema()`
2. **System 2** - Status publishing in `load_and_sample_from_datalake()`
3. **System 3** - Replaced ServiceBusPublisher with ServiceBusWriter, status publishing in `analyze()`
4. **System 4** - Status publishing in `detect_pii()` and quality report publishing after `anonymize_dataframe()`

**Important Notes:**
- Make sure all try/except blocks are properly indented
- The `writer` variable should be accessible in the except blocks
- System 4 needs to call `set_system_results()` before `detect_pii()` to store previous system results for quality report
- Quality report is published after both `detect_pii()` and `anonymize_dataframe()` complete
