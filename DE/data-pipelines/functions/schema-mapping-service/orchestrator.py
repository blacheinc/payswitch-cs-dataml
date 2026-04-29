"""
Schema Mapping Service Orchestrator
Orchestrates Systems 0-4 in sequence for training data transformation
"""

import json
import logging
import os
import traceback
import io
from typing import Dict, Any, Optional
from datetime import datetime
import pandas as pd

import azure.functions as func

# Import systems
from systems.file_introspector import FileIntrospector
from systems.schema_detector import SchemaDetector
from systems.data_sampler import DataSampler
from systems.data_analyzer import DataAnalyzer
from systems.dataset_anonymizer import DatasetAnonymizer

# Import utilities
from utils.service_bus_parser import parse_data_ingested_message, ServiceBusMessageError
from utils.service_bus_writer import ServiceBusWriter, BackendStatus, InternalStatus, ServiceBusClientError
from utils.key_vault_reader import KeyVaultReader
from utils.error_message_mapper import map_error_to_user_message, get_stage_name

# Import Azure clients
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient

logger = logging.getLogger(__name__)


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion for JSON sidecar payloads."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    # Prefer object dict when available.
    if hasattr(value, "__dict__"):
        return {
            k: _to_jsonable(v)
            for k, v in value.__dict__.items()
            if not k.startswith("_")
        }
    return str(value)


def _parse_possible_date(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    token = raw.split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(token, fmt)
        except ValueError:
            continue
    return None


def _latest_by_date(items: list[dict]) -> dict:
    date_keys = ("dateRequested", "dateAccountOpened", "closedDate", "updatedAt", "createdAt")
    scored = []
    for idx, item in enumerate(items):
        dt = None
        for key in date_keys:
            dt = _parse_possible_date(item.get(key))
            if dt:
                break
        scored.append((dt, idx, item))
    dated = [x for x in scored if x[0] is not None]
    if dated:
        dated.sort(key=lambda x: x[0], reverse=True)
        return dated[0][2]
    # fallback: last item order when no parseable date
    return scored[-1][2]


def _flatten_xds_json_rows(df: pd.DataFrame) -> pd.DataFrame:
    flattened_rows = []
    for record in df.to_dict(orient="records"):
        out: Dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, dict):
                for sk, sv in value.items():
                    out[f"{key}.{sk}"] = sv
            elif isinstance(value, list):
                if value and all(isinstance(v, dict) for v in value):
                    latest = _latest_by_date(value)
                    for sk, sv in latest.items():
                        out[f"{key}.{sk}"] = sv
                else:
                    out[key] = value[-1] if value else None
            else:
                out[key] = value
        flattened_rows.append(out)
    return pd.DataFrame(flattened_rows)


def _validate_flattened_xds_schema_v1(df: pd.DataFrame) -> None:
    required_columns = (
        "consumer_full_report_45.response.statusCode",
        "consumer_full_report_45.creditAgreementSummary.accountStatusCode",
        "consumer_full_report_45.creditAgreementSummary.monthsInArrears",
        "consumer_full_report_45.creditAgreementSummary.openingBalanceAmt",
    )
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(
            "flattened_xds_schema_v1 validation failed. Missing columns: "
            + ", ".join(missing)
        )


class SchemaMappingOrchestrator:
    """
    Orchestrates the complete schema mapping pipeline (Systems 0-4)
    """
    
    def __init__(self, key_vault_url: str):
        """
        Initialize orchestrator
        
        Args:
            key_vault_url: Key Vault URL for retrieving secrets
        """
        self.key_vault_url = key_vault_url
        self.key_vault_reader = KeyVaultReader(key_vault_url=key_vault_url)
        self.service_bus_writer = ServiceBusWriter(key_vault_url=key_vault_url)
        self.datalake_client = None
        self._credential = None
    
    def _get_credential(self):
        """Get or create Azure credential"""
        if self._credential is None:
            self._credential = DefaultAzureCredential(
                exclude_environment_credential=True,
                exclude_managed_identity_credential=False,
                exclude_shared_token_cache_credential=False,
                exclude_visual_studio_code_credential=False,
                exclude_cli_credential=False,
                exclude_powershell_credential=False,
                exclude_interactive_browser_credential=False,
                exclude_workload_identity_credential=False,
                additionally_allowed_tenants=["*"],
            )
        return self._credential
    
    def _get_datalake_client(self) -> DataLakeServiceClient:
        """Get or create Data Lake client"""
        if self.datalake_client is None:
            conn = (os.getenv("DATALAKE_STORAGE_CONNECTION_STRING") or "").strip()
            if conn:
                self.datalake_client = DataLakeServiceClient.from_connection_string(conn)
                logger.info(
                    "Initialized Data Lake client from DATALAKE_STORAGE_CONNECTION_STRING "
                    "(account key; local dev / bypass AAD data-plane RBAC)"
                )
            else:
                storage_account_name = self.key_vault_reader.get_secret("DataLakeStorageAccountName")
                account_url = f"https://{storage_account_name}.dfs.core.windows.net"
                credential = self._get_credential()
                self.datalake_client = DataLakeServiceClient(
                    account_url=account_url,
                    credential=credential,
                )
                logger.info(f"Initialized Data Lake client for account: {storage_account_name}")

        return self.datalake_client
    
    def _validate_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and parse incoming Service Bus message
        
        Args:
            message_data: Raw message dictionary
            
        Returns:
            Parsed message dictionary
            
        Raises:
            ServiceBusMessageError: If message is invalid
        """
        try:
            parsed = parse_data_ingested_message(message_data)
            logger.info(
                f"Validated message: training_upload_id={parsed['training_upload_id']}, "
                f"bank_id={parsed['bank_id']}, bronze_path={parsed['bronze_blob_path']}"
            )
            return parsed
        except ServiceBusMessageError as e:
            logger.error(f"Message validation failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during message validation: {str(e)}")
            raise ServiceBusMessageError(f"Failed to validate message: {str(e)}") from e
    
    def _handle_error(
        self,
        error: Exception,
        system_name: str,
        training_upload_id: str,
        bank_id: str,
        bronze_path: str
    ) -> None:
        """
        Handle errors by publishing to both internal and backend topics
        
        Args:
            error: Exception that occurred
            system_name: Name of the system that failed
            training_upload_id: Training upload ID
            bank_id: Bank ID
            bronze_path: Bronze blob path
        """
        error_str = str(error)
        error_type = type(error).__name__
        stack_trace = traceback.format_exc()
        
        # Determine error stage
        error_stage = get_stage_name(system_name)
        
        # Map to user-friendly message
        error_code, user_message, technical_summary = map_error_to_user_message(
            error_type=error_type,
            error_message=error_str,
            system_name=system_name,
            stack_trace=stack_trace
        )
        
        # Publish to internal failed topic (with full details)
        try:
            self.service_bus_writer.publish_system_failed(
                training_upload_id=training_upload_id,
                bank_id=bank_id,
                system_name=system_name,
                error={
                    "message": error_str,
                    "type": error_type,
                    "stack_trace": stack_trace,
                    "bronze_path": bronze_path,
                },
            )
        except Exception as e:
            logger.error(f"Failed to publish to internal failed topic: {str(e)}")
        
        # Publish to backend error topic (user-friendly)
        try:
            self.service_bus_writer.publish_backend_error(
                training_upload_id=training_upload_id,
                error_type=error_type,
                error_message=user_message,
                system_name=system_name,
                stack_trace=stack_trace
            )
        except Exception as e:
            logger.error(f"Failed to publish to backend error topic: {str(e)}")
    
    def run_pipeline(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the complete schema mapping pipeline (Systems 0-4)
        
        Args:
            message_data: Service Bus message dictionary
            
        Returns:
            Pipeline result dictionary
            
        Raises:
            Exception: If pipeline fails
        """
        # Validate message
        parsed_message = self._validate_message(message_data)
        
        training_upload_id = parsed_message['training_upload_id']
        bank_id = parsed_message['bank_id']
        bronze_path = parsed_message['bronze_blob_path']
        run_id = parsed_message.get('run_id')
        if not run_id:
            raise ValueError("run_id is required for mapping-complete handoff")
        
        logger.info(
            f"Starting pipeline for training_upload_id={training_upload_id}, "
            f"bank_id={bank_id}, bronze_path={bronze_path}"
        )
        
        # Get Data Lake client
        datalake_client = self._get_datalake_client()
        file_system_client = datalake_client.get_file_system_client("bronze")
        
        # Initialize systems
        introspector = FileIntrospector(
            datalake_client=file_system_client,
            service_bus_writer=self.service_bus_writer,
            key_vault_url=self.key_vault_url
        )
        
        schema_detector = SchemaDetector(
            datalake_client=file_system_client,
            service_bus_writer=self.service_bus_writer,
            key_vault_url=self.key_vault_url
        )
        
        data_sampler = DataSampler(
            datalake_client=file_system_client,
            service_bus_writer=self.service_bus_writer,
            key_vault_url=self.key_vault_url
        )
        
        data_analyzer = DataAnalyzer(
            service_bus_writer=self.service_bus_writer,
            key_vault_url=self.key_vault_url
        )
        
        dataset_anonymizer = DatasetAnonymizer(
            service_bus_writer=self.service_bus_writer,
            key_vault_url=self.key_vault_url
        )
        
        # Run Systems 0-4 in sequence
        try:
            # System 0: File Introspection
            logger.info("Running System 0: File Introspection")
            introspection_result = introspector.introspect_file(
                file_path=bronze_path,
                parsed_message=parsed_message
            )
            
            # System 1: Schema Detection
            logger.info("Running System 1: Schema Detection")
            
            # 1. Detect the format dynamically
            detected_format, format_conflict, fallback_format = schema_detector.detect_format(
                file_path=bronze_path,
                introspection_result=introspection_result,
                parsed_message=parsed_message
            )
            logger.info(f"Dynamically detected format: {detected_format} (Conflict: {format_conflict}, Fallback: {fallback_format})")
            
            # 2. Detect the schema
            schema_result = schema_detector.detect_schema(
                file_path=bronze_path,
                format=detected_format,
                introspection_result=introspection_result,
                parsed_message=parsed_message,
                format_conflict=format_conflict,
                fallback_format=fallback_format
            )
            
            # System 2: Data Sampling
            logger.info("Running System 2: Data Sampling")
            sampling_result = data_sampler.load_and_sample_from_datalake(
                bronze_path=bronze_path,
                format=schema_result.format,
                encoding=schema_result.encoding,
                schema_result=schema_result,
                parsed_message=parsed_message
            )
            
            # System 3: Data Analysis
            logger.info("Running System 3: Data Analysis")
            analysis_result = data_analyzer.analyze(
                sampling_result=sampling_result,
                schema_result=schema_result,
                parsed_message=parsed_message
            )
            
            # System 4: PII Detection & Anonymization
            logger.info("Running System 4: Dataset Anonymizer")
            
            # Set system results for quality report aggregation
            dataset_anonymizer.set_system_results(
                introspection_result=introspection_result,
                schema_result=schema_result,
                sampling_result=sampling_result,
                analysis_result=analysis_result,
                parsed_message=parsed_message
            )
            
            # Detect PII
            pii_result = dataset_anonymizer.detect_pii(
                schema_result=schema_result,
                data_analysis_result=analysis_result,
                bank_id=bank_id
            )
            
            # Anonymize data
            # Get the first sample DataFrame from sampling_result
            if not sampling_result.samples or len(sampling_result.samples) == 0:
                raise ValueError("No samples available from System 2 for anonymization")
            
            sample_df = sampling_result.samples[0]  # Use first sample
            source_format = str(getattr(schema_result, "format", "") or "").lower()

            # New phase: flatten JSON payload rows into strict flat schema prior to anonymization.
            # Applies only to JSON/JSONL source inputs.
            flattening_applied = False
            if source_format in {"json", "jsonl"}:
                sample_df = _flatten_xds_json_rows(sample_df)
                _validate_flattened_xds_schema_v1(sample_df)
                flattening_applied = True
                logger.info(
                    "Applied JSON flattening before anonymization (flattened_xds_schema_v1)."
                )
            
            # Anonymize the DataFrame
            # Note: anonymize_dataframe uses methods from pii_result for each field
            anonymized_result = dataset_anonymizer.anonymize_dataframe(
                df=sample_df,
                pii_fields=pii_result,
                method="hash"  # Default fallback method
            )
            
            # Save anonymized DataFrame to ADLS silver layer (canonical handoff artifact)
            # Path: silver/training/{bank_id}/{date}/{training_upload_id}/{run_id}/{training_upload_id}.parquet
            # Date is extracted from bronze_blob_path by the parser - must be present
            date = parsed_message.get('date')
            if not date:
                raise ValueError(
                    f"Date not found in parsed_message. "
                    f"This should have been extracted from bronze_blob_path: {parsed_message.get('bronze_blob_path')}"
                )
            silver_path = f"training/{bank_id}/{date}/{training_upload_id}/{run_id}/{training_upload_id}.parquet"
            
            # Get file system client for silver layer
            silver_file_system_client = datalake_client.get_file_system_client("silver")
            
            # Save anonymized DataFrame as Parquet
            anonymized_df = anonymized_result.anonymized_data
            file_client = silver_file_system_client.get_file_client(silver_path)
            
            # Convert DataFrame to Parquet bytes
            parquet_buffer = io.BytesIO()
            anonymized_df.to_parquet(parquet_buffer, index=False, engine='pyarrow')
            parquet_buffer.seek(0)
            
            # Upload to ADLS
            file_client.upload_data(
                data=parquet_buffer.read(),
                overwrite=True
            )
            
            anonymized_file_path = silver_path
            logger.info(f"Saved anonymized data to: {anonymized_file_path}")

            # Persist Systems 0-4 sidecar context next to anonymized parquet.
            analysis_context_path = (
                f"training/{bank_id}/{date}/{training_upload_id}/{run_id}/systems04_context.json"
            )
            context_payload = {
                "run_id": run_id,
                "training_upload_id": training_upload_id,
                "bank_id": bank_id,
                "pipeline_timestamp": datetime.utcnow().isoformat(),
                "anonymized_silver_path": anonymized_file_path,
                "bronze_source_path": bronze_path,
                "introspection": _to_jsonable(introspection_result),
                "schema_detection": _to_jsonable(schema_result),
                "data_analysis": _to_jsonable(analysis_result),
                "pii_detection": _to_jsonable(pii_result),
            }
            context_file_client = silver_file_system_client.get_file_client(analysis_context_path)
            context_file_client.upload_data(
                data=json.dumps(context_payload).encode("utf-8"),
                overwrite=True,
            )
            logger.info(f"Saved Systems 0-4 context to: {analysis_context_path}")
            
            # Intentionally do NOT publish backend "transformed" at this stage.
            # "transformed" should represent final curated output from deterministic transformation,
            # not the intermediate anonymized silver artifact.

            # Publish canonical deterministic transformation handoff (fail-fast on error).
            self.service_bus_writer.publish_mapping_complete_handoff(
                training_upload_id=training_upload_id,
                bank_id=bank_id,
                run_id=run_id,
                request_id=training_upload_id,
                anonymized_silver_path=anonymized_file_path,
                analysis_context_path=analysis_context_path,
                source_system=str(parsed_message.get("source_system", "xds")).lower(),
                flow_type="training",
                applicant_context=parsed_message.get("applicant_context") or {},
                systems04_summary={
                    "schema_column_count": (
                        len(schema_result.column_names)
                        if schema_result.column_names
                        else (schema_result.column_count or 0)
                    ),
                    "sample_count": len(sampling_result.samples) if sampling_result.samples else 0,
                    "pii_field_count": (
                        len(pii_result.names)
                        + len(pii_result.emails)
                        + len(pii_result.phones)
                        + len(pii_result.ids)
                        + len(pii_result.addresses)
                    )
                    if hasattr(pii_result, "names")
                    else 0,
                    "silver_row_count": int(len(anonymized_df.index)),
                    "silver_column_count": int(len(anonymized_df.columns)),
                    "schema_format": getattr(schema_result, "format", None),
                    "schema_confidence": getattr(schema_result, "confidence", None),
                    "data_quality_score_hint": (
                        (
                            (analysis_result.metadata or {}).get("quality_score")
                            if hasattr(analysis_result, "metadata")
                            else None
                        )
                    ),
                    "pii_category_counts": {
                        "names": len(getattr(pii_result, "names", []) or []),
                        "emails": len(getattr(pii_result, "emails", []) or []),
                        "phones": len(getattr(pii_result, "phones", []) or []),
                        "ids": len(getattr(pii_result, "ids", []) or []),
                        "addresses": len(getattr(pii_result, "addresses", []) or []),
                        "other": len(getattr(pii_result, "other", []) or []),
                    },
                    "pii_anonymization_method_count": len(
                        (getattr(pii_result, "anonymization_methods", {}) or {}).keys()
                    ),
                    "analysis_null_columns_count": len(
                        (
                            (analysis_result.missing_data if hasattr(analysis_result, "missing_data") else {})
                            or {}
                        ).keys()
                    ),
                    "analysis_numeric_columns_count": len(
                        [
                            k
                            for k, v in (
                                (analysis_result.data_types if hasattr(analysis_result, "data_types") else {})
                                or {}
                            ).items()
                            if str(v).lower() in {"int", "integer", "float", "double", "number", "numeric"}
                        ]
                    ),
                    "analysis_text_columns_count": len(
                        (
                            (analysis_result.text_patterns if hasattr(analysis_result, "text_patterns") else {})
                            or {}
                        ).keys()
                    ),
                    "flattening_applied": flattening_applied,
                    "flattened_schema_version": "flattened_xds_schema_v1" if flattening_applied else None,
                    "source_format": source_format,
                },
            )
            
            logger.info(f"Pipeline completed successfully for training_upload_id={training_upload_id}")
            
            return {
                "training_upload_id": training_upload_id,
                "bank_id": bank_id,
                "status": "completed",
                "anonymized_file_path": anonymized_file_path,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            # Determine which system failed based on where we are in the pipeline
            system_name = "Unknown System"
            if 'introspection_result' not in locals():
                system_name = "System 0: File Introspection"
            elif 'schema_result' not in locals():
                system_name = "System 1: Schema Detection"
            elif 'sampling_result' not in locals():
                system_name = "System 2: Data Sampling"
            elif 'analysis_result' not in locals():
                system_name = "System 3: Data Analysis"
            else:
                system_name = "System 4: Dataset Anonymizer"
            
            # Handle error
            self._handle_error(
                error=e,
                system_name=system_name,
                training_upload_id=training_upload_id,
                bank_id=bank_id,
                bronze_path=bronze_path
            )
            
            # Re-raise to fail the function
            raise


# Global orchestrator instance (reused across invocations)
_orchestrator: Optional[SchemaMappingOrchestrator] = None


def get_orchestrator(key_vault_url: str) -> SchemaMappingOrchestrator:
    """Get or create orchestrator instance"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SchemaMappingOrchestrator(key_vault_url=key_vault_url)
    return _orchestrator
