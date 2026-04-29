"""
System 4: Dataset Anonymizer System
Orchestrates PII detection (schema-only) and anonymization
"""

import logging
from typing import Dict, Optional, Any

import pandas as pd

try:
    from system_interfaces import (
        IDatasetAnonymizerSystem,
        PIIDetectionResult,
        AnonymizationResult,
        SchemaDetectionResult,
        DataAnalysisResult,
    )
    from systems.schema_hash import calculate_schema_hash
    from schema_registry.anonymization_mapping_store import AnonymizationMappingStore
except ImportError:
    from ..system_interfaces import (
        IDatasetAnonymizerSystem,
        PIIDetectionResult,
        AnonymizationResult,
        SchemaDetectionResult,
        DataAnalysisResult,
    )
    from ..systems.schema_hash import calculate_schema_hash
    from ..schema_registry.anonymization_mapping_store import AnonymizationMappingStore

from .pii_detector import PIIDetector
from .pii_anonymizer import PIIAnonymizer
import traceback
import os

try:
    from systems.llm_pii_detector import create_llm_pii_detector_with_full_context
except ImportError:
    from ..systems.llm_pii_detector import create_llm_pii_detector_with_full_context

def _resolve_llm_keyvault_env() -> str:
    """
    Credential mode for Azure OpenAI secrets in Key Vault.

    Explicit ENVIRONMENT=local|production wins. Otherwise treat Azure-hosted
    workers (WEBSITE_INSTANCE_ID) as production and `func start` / plain
    Python as local so DefaultAzureCredential is not used without CLI login.
    """
    v = os.getenv("ENVIRONMENT", "").strip().lower()
    if v in ("local", "production"):
        return v
    return "production" if os.getenv("WEBSITE_INSTANCE_ID") else "local"


try:
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from utils.quality_report_aggregator import aggregate_quality_report
except ImportError:
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from ..utils.quality_report_aggregator import aggregate_quality_report

logger = logging.getLogger(__name__)


class DatasetAnonymizer(IDatasetAnonymizerSystem):
    """
    System 4: Dataset Anonymizer
    Detects PII (schema-only) and anonymizes DataFrames before LLM processing
    """

    def __init__(
        self,
        pii_detector: Optional[PIIDetector] = None,
        pii_anonymizer: Optional[PIIAnonymizer] = None,
        use_llm: bool = True,  # Default to True - use LLM as primary method
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None,
        run_id: Optional[str] = None,
        state_tracker = None
    ):
        """
        Args:
            pii_detector: Optional custom PIIDetector (if None, will create one with LLM if use_llm=True)
            pii_anonymizer: Optional custom PIIAnonymizer
            use_llm: If True, use LLM-based PII detection as primary method (requires key_vault_url)
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string and Azure OpenAI secrets
            run_id: Run ID for tracking and filtering
            state_tracker: Optional PipelineStateTracker instance
        """
        self.service_bus_writer = service_bus_writer
        self.key_vault_url = key_vault_url
        self.run_id = run_id
        self.state_tracker = state_tracker
        self._message_context: Optional[Dict[str, Any]] = None
        self._introspection_result: Optional[Dict[str, Any]] = None
        self._schema_result: Optional[SchemaDetectionResult] = None
        self._sampling_result: Optional[Dict[str, Any]] = None
        self._analysis_result: Optional[DataAnalysisResult] = None
        
        # Initialize PII detector with LLM if requested
        if pii_detector is not None:
            self.pii_detector = pii_detector
        elif use_llm and key_vault_url:
            try:
                env = _resolve_llm_keyvault_env()
                
                # Create LLM-based PII detector with full context support
                llm_callback = create_llm_pii_detector_with_full_context(
                    key_vault_url=key_vault_url,
                    env=env
                )
                self.pii_detector = PIIDetector(llm_callback=llm_callback)
                logger.info(f"Initialized LLM-based PII detector (env={env})")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM-based PII detector, falling back to rule-based: {e}")
                self.pii_detector = PIIDetector()  # Fallback to rule-based
        else:
            # Use rule-based detector
            self.pii_detector = PIIDetector()
            if use_llm:
                logger.warning("use_llm=True but key_vault_url not provided. Using rule-based PII detection.")
        
        self.pii_anonymizer = pii_anonymizer or PIIAnonymizer()
    
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
            # Get run_id from parsed_message if not set in __init__
            if not self.run_id:
                self.run_id = parsed_message.get('run_id')

    def detect_pii(
        self,
        schema_result: SchemaDetectionResult,
        data_analysis_result: Optional[DataAnalysisResult] = None,
        bank_id: Optional[str] = None
    ) -> PIIDetectionResult:
        """
        Detect PII fields using schema-only metadata (column names + types).
        SECURITY: NO DataFrames passed to LLM - only schema metadata (column names + types).

        Args:
            schema_result: Schema detection result from System 1
            data_analysis_result: Optional data analysis result from System 3 (preferred for types)
            bank_id: Bank identifier (mandatory for artifact reuse)

        Returns:
            PIIDetectionResult with detected PII fields by category and anonymization methods
        """
        system_name = "System 4: Dataset Anonymizer"
        
        # Get run_id from message context if not set in __init__
        if not self.run_id and self._message_context:
            self.run_id = self._message_context.get('run_id')
        
        # Store context for quality report aggregation
        self._schema_result = schema_result
        self._analysis_result = data_analysis_result
        
        # bank_id is mandatory for artifact reuse
        if not bank_id:
            raise ValueError("bank_id is mandatory and cannot be empty or None. Cannot proceed with PII detection without bank_id.")
        
        # Check deduplication before processing
        system_name_short = "anonymization"
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
        if writer and bank_id:
            try:
                # Try to get training_upload_id from message context if available
                training_upload_id = (self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')) if self._message_context else 'unknown'
                writer.publish_system_starting(
                    training_upload_id=training_upload_id,
                    bank_id=bank_id,
                    system_name=system_name,
                    run_id=self.run_id
                )
            except Exception as e:
                logger.warning(f"[run_id={self.run_id}] Failed to publish system starting message: {e}")
        
        try:
            # SECURITY CHECK: Ensure we're working with schema metadata, not DataFrames
            assert isinstance(schema_result, SchemaDetectionResult), \
                "schema_result must be SchemaDetectionResult, not DataFrame"
            if data_analysis_result is not None:
                assert isinstance(data_analysis_result, DataAnalysisResult), \
                    "data_analysis_result must be DataAnalysisResult, not DataFrame"
            
            # Extract column names from schema result, with fallback to sampling result
            if not schema_result.column_names:
                # Fallback: Extract column names from DataFrame in sampling result
                if self._sampling_result and hasattr(self._sampling_result, 'samples') and self._sampling_result.samples:
                    sample_df = self._sampling_result.samples[0]
                    if hasattr(sample_df, 'columns'):
                        column_names = list(sample_df.columns)
                        logger.warning(
                            f"schema_result.column_names is empty. Extracted column names from DataFrame: {column_names}"
                        )
                    else:
                        raise ValueError("schema_result.column_names is empty and cannot extract from sampling_result.samples[0]")
                else:
                    raise ValueError(
                        "schema_result.column_names is empty or None and no sampling_result available to extract column names"
                    )
            else:
                column_names = schema_result.column_names
            
            # Extract column types: prefer data_analysis_result.data_types, fallback to schema_result.column_types
            if data_analysis_result and data_analysis_result.data_types:
                column_types = data_analysis_result.data_types
            elif schema_result.column_types:
                column_types = schema_result.column_types
            else:
                # Fallback: infer types from schema metadata if available
                logger.warning("No column types available in schema_result or data_analysis_result. Using defaults.")
                column_types = {col: 'string' for col in column_names}

            # Option B: Always perform full detection, then calculate hash and check/store cache
            try:
                # Calculate schema hash
                schema_hash = calculate_schema_hash(column_names, column_types)
                
                # Check cache (Redis then PostgreSQL)
                cached_mapping = AnonymizationMappingStore.get(bank_id, schema_hash)
                if cached_mapping:
                    logger.info(f"Found cached anonymization mapping for bank_id: {bank_id}, schema_hash: {schema_hash}")
                    # Create PIIDetectionResult from cached mapping
                    # Categorize PII fields based on column names (simplified - in practice, we'd store categories in cache)
                    names = []
                    emails = []
                    phones = []
                    ids = []
                    addresses = []
                    other = []
                    
                    for col in cached_mapping.keys():
                        # Simple categorization based on column name patterns
                        col_lower = col.lower()
                        if any(term in col_lower for term in ['name', 'first', 'last', 'full']):
                            names.append(col)
                        elif any(term in col_lower for term in ['email', 'mail']):
                            emails.append(col)
                        elif any(term in col_lower for term in ['phone', 'mobile', 'tel']):
                            phones.append(col)
                        elif any(term in col_lower for term in ['address', 'street', 'city', 'postal']):
                            addresses.append(col)
                        elif any(term in col_lower for term in ['id', 'ssn', 'passport', 'national']):
                            ids.append(col)
                        else:
                            other.append(col)
                    
                    cached_result = PIIDetectionResult(
                        names=names,
                        emails=emails,
                        phones=phones,
                        ids=ids,
                        addresses=addresses,
                        other=other,
                        anonymization_methods=cached_mapping
                    )
                    
                    # Record system completion in state tracker (cached)
                    if self.state_tracker and self.run_id:
                        try:
                            self.state_tracker.complete_system(
                                run_id=self.run_id,
                                system_name=system_name_short,
                                metadata={
                                    "pii_fields_detected": len(cached_result.names) + len(cached_result.emails) + len(cached_result.phones) + len(cached_result.ids) + len(cached_result.addresses) + len(cached_result.other),
                                    "anonymization_methods": len(cached_result.anonymization_methods),
                                    "from_cache": True
                                }
                            )
                            logger.debug(f"[run_id={self.run_id}] Recorded system completion (cached): {system_name_short}")
                        except Exception as e:
                            logger.warning(f"[run_id={self.run_id}] Failed to record system completion: {e}")
                    
                    # Publish PII detection complete (cached)
                    if writer and bank_id:
                        try:
                            training_upload_id = (self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')) if self._message_context else 'unknown'
                            writer.publish_system_complete(
                                training_upload_id=training_upload_id,
                                bank_id=bank_id,
                                system_name=system_name,
                                status=InternalStatus.ANONYMIZATION_COMPLETE,
                                result={
                                    "pii_fields_detected": len(cached_result.names) + len(cached_result.emails) + len(cached_result.phones) + len(cached_result.ids) + len(cached_result.addresses) + len(cached_result.other),
                                    "anonymization_methods": len(cached_result.anonymization_methods),
                                    "from_cache": True
                                },
                                run_id=self.run_id
                            )
                        except Exception as e:
                            logger.warning(f"[run_id={self.run_id}] Failed to publish system complete message: {e}")
                    
                    return cached_result
            except Exception as e:
                logger.warning(f"Error during artifact reuse check for anonymization mapping: {e}. Continuing with detection.")

            # Perform detection with full context from previous systems
            # Convert introspection_result to dict if it's a Pydantic model
            introspection_dict = self._introspection_result
            if introspection_dict and hasattr(introspection_dict, 'model_dump'):
                introspection_dict = introspection_dict.model_dump()
            elif introspection_dict and hasattr(introspection_dict, 'dict'):
                introspection_dict = introspection_dict.dict()
            
            result = self.pii_detector.detect_pii(
                column_names=column_names,
                column_types=column_types,
                schema_result=schema_result,
                data_analysis_result=data_analysis_result,
                introspection_result=introspection_dict
            )
            
            # Store result in cache
            if result.anonymization_methods:
                try:
                    schema_hash = calculate_schema_hash(column_names, column_types)
                    AnonymizationMappingStore.store(
                        bank_id=bank_id,
                        schema_hash=schema_hash,
                        anonymization_methods=result.anonymization_methods,
                        current_column_names=column_names,
                        current_column_types=column_types
                    )
                    logger.info(f"Stored anonymization mapping for bank_id: {bank_id}, schema_hash: {schema_hash}")
                except Exception as e:
                    logger.warning(f"Failed to store anonymization mapping in cache: {e}. Continuing with result.")
            
            # Record system completion in state tracker
            if self.state_tracker and self.run_id:
                try:
                    self.state_tracker.complete_system(
                        run_id=self.run_id,
                        system_name=system_name_short,
                        metadata={
                            "pii_fields_detected": len(result.names) + len(result.emails) + len(result.phones) + len(result.ids) + len(result.addresses) + len(result.other),
                            "anonymization_methods": len(result.anonymization_methods) if hasattr(result, 'anonymization_methods') else 0,
                            "from_cache": False
                        }
                    )
                    logger.debug(f"[run_id={self.run_id}] Recorded system completion: {system_name_short}")
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to record system completion: {e}")
            
            # Publish PII detection complete
            if writer and bank_id:
                try:
                    training_upload_id = (self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')) if self._message_context else 'unknown'
                    
                    # Prepare detailed mapping for the payload
                    detailed_mapping = {}
                    if hasattr(result, 'anonymization_methods') and result.anonymization_methods:
                        for col, method in result.anonymization_methods.items():
                            detailed_mapping[col] = {
                                "method": method,
                                "reason": result.reasons.get(col, "Identified as PII") if hasattr(result, 'reasons') else "Identified as PII"
                            }
                            
                    writer.publish_system_complete(
                        training_upload_id=training_upload_id,
                        bank_id=bank_id,
                        system_name=system_name,
                        status=InternalStatus.ANONYMIZATION_COMPLETE,
                        result={
                            "pii_fields_detected": len(result.names) + len(result.emails) + len(result.phones) + len(result.ids) + len(result.addresses) + len(result.other),
                            "anonymization_methods": len(result.anonymization_methods) if hasattr(result, 'anonymization_methods') else 0,
                            "detailed_mapping": detailed_mapping,
                            "from_cache": False
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
            
            if writer and bank_id:
                try:
                    training_upload_id = (self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')) if self._message_context else 'unknown'
                    # Internal error (detailed)
                    writer.publish_system_failed(
                        training_upload_id=training_upload_id,
                        bank_id=bank_id,
                        system_name=system_name,
                        error={
                            "message": error_message,
                            "type": error_type,
                            "stack_trace": stack_trace
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
            
            logger.error(f"[run_id={self.run_id}] Error in PII detection: {error_message}", exc_info=True)
            raise

    def anonymize_dataframe(
        self,
        df: pd.DataFrame,
        pii_fields: PIIDetectionResult,
        method: str = "hash"
    ) -> AnonymizationResult:
        """
        Anonymize PII columns in DataFrame.

        Args:
            df: Source DataFrame
            pii_fields: Detected PII fields from detect_pii()
            method: "hash" | "tokenize" | "generalize"

        Returns:
            AnonymizationResult with anonymized DataFrame and mappings
        """
        self.pii_anonymizer.reset_token_counter()
        result = self.pii_anonymizer.anonymize_dataframe(df, pii_fields, method)
        
        # After both detect_pii and anonymize_dataframe complete, aggregate quality report
        writer = self._get_service_bus_writer()
        if writer and self._message_context and self._schema_result and self._analysis_result:
            try:
                training_upload_id = self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')
                bank_id = self._message_context.get('bank_id')
                
                if bank_id:
                    # Convert Pydantic models to dicts if needed
                    schema_dict = self._schema_result.model_dump() if hasattr(self._schema_result, 'model_dump') else self._schema_result
                    analysis_dict = self._analysis_result.model_dump() if hasattr(self._analysis_result, 'model_dump') else self._analysis_result
                    pii_dict = pii_fields.model_dump() if hasattr(pii_fields, 'model_dump') else pii_fields
                    
                    # Calculate average confidence for the Quality Report
                    conf_scores = getattr(pii_fields, "confidence_scores", {})
                    if isinstance(conf_scores, dict) and conf_scores:
                        avg_conf = sum(conf_scores.values()) / len(conf_scores)
                        pii_dict["confidence"] = avg_conf
                    else:
                        pii_dict["confidence"] = 1.0  # Default if missing but LLM succeeded
                    
                    # Convert introspection_result to dict if it's a Pydantic model
                    introspection_dict = self._introspection_result
                    if introspection_dict and hasattr(introspection_dict, 'model_dump'):
                        introspection_dict = introspection_dict.model_dump()
                    elif introspection_dict and hasattr(introspection_dict, 'dict'):
                        introspection_dict = introspection_dict.dict()
                    
                    # Aggregate quality report from Systems 0-4
                    quality_report = aggregate_quality_report(
                        introspection_result=introspection_dict,
                        schema_result=schema_dict,
                        sampling_result=self._sampling_result,
                        analysis_result=analysis_dict,
                        pii_result=pii_dict,
                        quality_score_method="weighted"
                    )
                    
                    # Publish quality report to backend
                    writer.publish_quality_report(
                        training_upload_id=training_upload_id,
                        quality_report=quality_report,
                        quality_score=quality_report.get('quality_score', 0.0),
                        run_id=self.run_id
                    )
                    
                    logger.info(f"[run_id={self.run_id}] Published quality report for training_upload_id: {training_upload_id}")
            except Exception as e:
                logger.error(f"Failed to publish quality report: {e}")
        
        return result
