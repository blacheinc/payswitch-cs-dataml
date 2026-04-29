"""
Run full schema-mapping pipeline from a single Service Bus message.

This script is a plain Python entry point used for local, end-to-end
integration testing of Systems 0–4 without Azure Functions runtime.

Behavior:
- Loads configuration from a local `.env` file.
- Connects to Service Bus topic/subscription.
- Receives exactly ONE message.
- Runs Systems 0–4 (File Introspector, Schema Detector, Data Sampler,
  Data Analyzer, Dataset Anonymizer) using the *real* implementations.
- Reads from Bronze and writes anonymized output to Silver.
- Uses Key Vault + DefaultAzureCredential for Data Lake auth, just like
  the orchestrator.

No mocking. All dependencies are real.

CLI:
  --verbose, -v   Force DEBUG logging (sets LOG_LEVEL=DEBUG for this process).
"""

import argparse
import json
import logging
import os
import re
import sys
import traceback
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

# Ensure project root is on sys.path so that `utils` and `systems` imports work
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from azure.servicebus import ServiceBusClient, AutoLockRenewer
from azure.servicebus.exceptions import MessageLockLostError
from azure.identity import DefaultAzureCredential, AzureCliCredential
from azure.storage.filedatalake import DataLakeServiceClient
from azure.core.credentials import AzureNamedKeyCredential

from utils.key_vault_reader import KeyVaultReader, KeyVaultError
from utils.service_bus_parser import parse_data_ingested_message, ServiceBusMessageError
from utils.service_bus_writer import ServiceBusWriter, ServiceBusClientError
from utils.error_message_mapper import map_error_to_user_message, get_stage_name
from utils.pipeline_state_tracker import PipelineStateTracker

from systems.file_introspector import FileIntrospector
from systems.schema_detector import SchemaDetector
from systems.data_sampler import DataSampler
from systems.data_analyzer import DataAnalyzer
from systems.dataset_anonymizer import DatasetAnonymizer


logger = logging.getLogger("run_pipeline_from_service_bus")


# ============================================================
# Configuration helpers
# ============================================================

REQUIRED_ENV_VARS = [
    "AzureWebJobsStorage",
    "ServiceBusConnectionString",
    "KEY_VAULT_URL",
    "SERVICEBUS_TOPIC_NAME",
    "SERVICEBUS_SUBSCRIPTION_NAME",
    "DATALAKE_STORAGE_ACCOUNT_NAME_SECRET",
    "BRONZE_FILE_SYSTEM_NAME",
    "SILVER_FILE_SYSTEM_NAME",
]


def load_dotenv(dotenv_path: str = ".env") -> None:
    """
    Minimal .env loader.

    - Lines starting with '#' are comments.
    - Empty lines are ignored.
    - KEY=VALUE pairs are loaded into os.environ if not already set.
    """
    if not os.path.exists(dotenv_path):
        logger.warning(f".env file not found at {dotenv_path} - relying on existing environment variables only")
        return

    with open(dotenv_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def validate_required_env() -> None:
    missing = [k for k in REQUIRED_ENV_VARS if not os.getenv(k)]
    if missing:
        missing_str = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {missing_str}")


def configure_logging(*, force_debug: bool = False) -> None:
    level_str = (
        "DEBUG" if force_debug else os.getenv("LOG_LEVEL", "WARNING")
    ).upper()
    level = getattr(logging, level_str, logging.DEBUG)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    logger.info("Logging configured. Level=%s", level_str)


# ============================================================
# Azure clients helpers
# ============================================================

def get_default_credential() -> DefaultAzureCredential:
    """
    Get a credential for Data Lake access.

    For local runs, use AzureCliCredential so that `az login` is the
    single source of truth. For non-local, use DefaultAzureCredential.
    """
    env = os.getenv("ENVIRONMENT", "local").lower()

    if env == "local":
        credential = AzureCliCredential()
        logger.info("Using AzureCliCredential for LOCAL environment")
    else:
        # Non-local (e.g., Azure Function App): allow Managed Identity
        credential = DefaultAzureCredential(
            exclude_environment_credential=True,
            exclude_managed_identity_credential=False,
            exclude_shared_token_cache_credential=False,
            exclude_visual_studio_code_credential=False,
            exclude_cli_credential=False,
            exclude_powershell_credential=False,
            exclude_interactive_browser_credential=False,
            exclude_workload_identity_credential=False,
        )
        logger.info("Using DefaultAzureCredential for NON-LOCAL environment (Managed Identity enabled)")

    return credential


def get_datalake_client(
    key_vault_reader: KeyVaultReader,
    storage_account_name_secret: str,
) -> DataLakeServiceClient:
    """
    Create a DataLakeServiceClient using storage account name.
    
    For local testing:
    - Uses account key from AzureWebJobsStorage connection string (same as Azure CLI)
    - Can use DATALAKE_STORAGE_ACCOUNT_NAME env var to bypass Key Vault for account name
    
    In Azure (non-local):
    - Uses Key Vault for account name
    - Uses DefaultAzureCredential (Managed Identity)
    """
    conn = (os.getenv("DATALAKE_STORAGE_CONNECTION_STRING") or "").strip()
    if conn:
        logger.info(
            "Using DATALAKE_STORAGE_CONNECTION_STRING for Data Lake (shared key; "
            "matches schema-mapping orchestrator local dev)"
        )
        return DataLakeServiceClient.from_connection_string(conn)

    env = os.getenv("ENVIRONMENT", "local").lower()
    
    # Check for direct env var first (local testing bypass)
    storage_account_name = os.getenv("DATALAKE_STORAGE_ACCOUNT_NAME")
    
    if storage_account_name:
        logger.info(
            f"Using DATALAKE_STORAGE_ACCOUNT_NAME from environment: '{storage_account_name}' "
            "(bypassing Key Vault for local testing)"
        )
    else:
        logger.info(f"Retrieving storage account name from Key Vault secret '{storage_account_name_secret}'")
        try:
            storage_account_name = key_vault_reader.get_secret(storage_account_name_secret)
        except Exception as e:
            logger.error(
                f"Failed to get storage account name from Key Vault: {e}. "
                "For local testing, you can set DATALAKE_STORAGE_ACCOUNT_NAME in .env to bypass Key Vault."
            )
            raise
    
    account_url = f"https://{storage_account_name}.dfs.core.windows.net"

    # For local testing, use account key from AzureWebJobsStorage (same as Azure CLI)
    # For Azure, use DefaultAzureCredential (Managed Identity)
    if env == "local":
        # Extract account key from AzureWebJobsStorage connection string
        azure_webjobs_storage = os.getenv("AzureWebJobsStorage")
        if azure_webjobs_storage and "AccountKey=" in azure_webjobs_storage:
            # Parse connection string: AccountKey=value;...
            account_key_match = re.search(r"AccountKey=([^;]+)", azure_webjobs_storage)
            if account_key_match:
                account_key = account_key_match.group(1)
                logger.info("Using account key from AzureWebJobsStorage connection string for Data Lake authentication (local testing)")
                credential = AzureNamedKeyCredential(name=storage_account_name, key=account_key)
            else:
                logger.warning("Could not extract AccountKey from AzureWebJobsStorage, falling back to AzureCliCredential")
                credential = AzureCliCredential()
        else:
            logger.warning("AzureWebJobsStorage not found or missing AccountKey, falling back to AzureCliCredential")
            credential = AzureCliCredential()
    else:
        # Non-local: use DefaultAzureCredential (Managed Identity)
        credential = get_default_credential()
    
    logger.info(f"Initializing DataLakeServiceClient for account_url={account_url}")
    client = DataLakeServiceClient(
        account_url=account_url,
        credential=credential,
    )
    logger.info(f"DataLakeServiceClient initialized for storage account '{storage_account_name}'")
    return client


def get_servicebus_client() -> ServiceBusClient:
    connection_str = os.getenv("ServiceBusConnectionString")
    if not connection_str:
        raise RuntimeError("ServiceBusConnectionString environment variable is required")
    # Log a masked version for debugging (show first 30 chars and last 10 chars)
    if len(connection_str) > 40:
        masked = connection_str[:30] + "..." + connection_str[-10:]
    else:
        masked = "***"  # Too short to mask safely
    logger.info(f"Initializing ServiceBusClient from connection string (masked: {masked})")
    return ServiceBusClient.from_connection_string(conn_str=connection_str, logging_enable=True)


# ============================================================
# Core pipeline logic
# ============================================================

def receive_one_message(
    sb_client: ServiceBusClient,
    topic_name: str,
    subscription_name: str,
) -> Any:
    """
    Receive exactly one message from the given topic/subscription.
    """
    logger.info(
        f"Connecting to Service Bus topic='{topic_name}', subscription='{subscription_name}' "
        "to receive ONE message"
    )

    # IMPORTANT: do NOT use `with sb_client:` or `with receiver:` here.
    # The caller settles the message (complete/abandon) after running the pipeline,
    # and settlement requires the receiver to still be alive.
    receiver = sb_client.get_subscription_receiver(
        topic_name=topic_name,
        subscription_name=subscription_name,
        max_wait_time=30,
    )

    logger.info("Waiting for a single message from Service Bus...")
    messages = receiver.receive_messages(max_message_count=1, max_wait_time=30)

    if not messages:
        # Ensure receiver is closed if we didn't get a message
        try:
            receiver.close()
        except Exception:
            pass
        raise RuntimeError("No messages received from Service Bus within wait time")

    message = messages[0]

    logger.info(
        "Received Service Bus message: "
        f"MessageId={message.message_id}, "
        f"SessionId={message.session_id}, "
        f"SequenceNumber={message.sequence_number}, "
        f"DeliveryCount={message.delivery_count}, "
        f"EnqueuedTimeUtc={message.enqueued_time_utc}"
    )

    # Handle different body types from Service Bus SDK
    if hasattr(message.body, '__iter__') and not isinstance(message.body, (bytes, str)):
        # It's an iterable (list, generator, etc.) - consume it
        body_bytes = b"".join(b for b in message.body)
    elif isinstance(message.body, bytes):
        body_bytes = message.body
    elif isinstance(message.body, str):
        body_str = message.body
        logger.info(f"Raw message body (first 500 chars): {body_str[:500]}")
        try:
            message_data = json.loads(body_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message body as JSON: {e}")
            raise
        logger.info(f"Decoded message_data keys: {list(message_data.keys())}")
        return receiver, message, message_data
    else:
        # Fallback: try to convert to string
        body_bytes = bytes(str(message.body), encoding="utf-8")
    
    # Decode bytes to string
    body_str = body_bytes.decode("utf-8")
    logger.info(f"Raw message body (first 500 chars): {body_str[:500]}")

    try:
        message_data = json.loads(body_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode message body as JSON: {e}")
        raise

    logger.info(f"Decoded message_data keys: {list(message_data.keys())}")
    
    # Extract run_id from custom properties if not in body
    if 'run_id' not in message_data and hasattr(message, 'application_properties'):
        app_props = message.application_properties or {}
        if 'run_id' in app_props:
            message_data['run_id'] = app_props['run_id']
            logger.info(f"Extracted run_id from message custom properties: {message_data['run_id']}")
    
    return receiver, message, message_data


def run_pipeline_from_message(
    message_data: Dict[str, Any],
    key_vault_reader: KeyVaultReader,
    datalake_client: DataLakeServiceClient,
    service_bus_writer: ServiceBusWriter,
    message_id: Optional[str] = None,
) -> str:
    """
    Run Systems 0–4 for a single parsed Service Bus message.

    Args:
        message_data: Parsed message data dictionary
        key_vault_reader: Key Vault reader instance
        datalake_client: Data Lake service client
        service_bus_writer: Service Bus writer instance
        message_id: Service Bus message ID (for deduplication)

    Returns:
        silver_path written by the anonymization step.
    """
    logger.info("STEP 1: Validating and parsing incoming message")
    
    # Extract or generate run_id
    run_id = message_data.get("run_id")
    if not run_id:
        # Check if run_id is in custom properties (from Service Bus message)
        # If still not found, this is an error - reject the message
        error_msg = "Message missing required 'run_id' field. Message rejected."
        logger.error(f"{error_msg} Message keys: {list(message_data.keys())}")
        raise ServiceBusMessageError(error_msg)
    
    # Validate run_id is a valid UUID format
    try:
        uuid.UUID(run_id)
    except (ValueError, TypeError):
        error_msg = f"Invalid run_id format: {run_id}. Must be a valid UUID."
        logger.error(error_msg)
        raise ServiceBusMessageError(error_msg)
    
    logger.info(f"Processing message with run_id={run_id}")
    
    # Check for required fields before parsing (handle old messages gracefully)
    if 'bank_id' not in message_data or not message_data.get('bank_id'):
        error_msg = "Missing required field: bank_id"
        logger.warning(f"[run_id={run_id}] {error_msg}. This appears to be an old message format. Message will be skipped.")
        raise ServiceBusMessageError(error_msg)
    
    parsed_message = parse_data_ingested_message(message_data)
    
    # Add run_id to parsed_message for propagation to all systems
    parsed_message["run_id"] = run_id

    training_upload_id = parsed_message["training_upload_id"]
    bank_id = parsed_message["bank_id"]
    bronze_path = parsed_message["bronze_blob_path"]
    date = parsed_message.get("date")

    logger.info(
        f"[run_id={run_id}] Parsed message: "
        f"training_upload_id={training_upload_id}, "
        f"bank_id={bank_id}, "
        f"bronze_blob_path={bronze_path}, "
        f"date={date}"
    )

    if not date:
        raise ServiceBusMessageError(
            f"Date not found in parsed_message. "
            f"This should have been extracted from bronze_blob_path: {parsed_message.get('bronze_blob_path')}"
        )

    bronze_fs_name = os.getenv("BRONZE_FILE_SYSTEM_NAME")
    silver_fs_name = os.getenv("SILVER_FILE_SYSTEM_NAME")
    if not bronze_fs_name or not silver_fs_name:
        raise RuntimeError("BRONZE_FILE_SYSTEM_NAME and SILVER_FILE_SYSTEM_NAME must both be set")

    bronze_fs = datalake_client.get_file_system_client(bronze_fs_name)
    silver_fs = datalake_client.get_file_system_client(silver_fs_name)

    logger.info(
        f"Using Bronze file system '{bronze_fs_name}' and Silver file system '{silver_fs_name}' "
        f"for training_upload_id={training_upload_id}"
    )
    
    # Strip the file system name prefix from bronze_path since FileSystemClient is already scoped to the file system
    # bronze_path might be "bronze/training/..." but we need just "training/..." for the FileSystemClient
    if bronze_path.startswith(f"{bronze_fs_name}/"):
        bronze_path_relative = bronze_path[len(f"{bronze_fs_name}/"):]
        logger.info(f"Stripped file system prefix from bronze_path: '{bronze_path}' -> '{bronze_path_relative}'")
        bronze_path = bronze_path_relative
        # Update parsed_message so all systems use the correct relative path
        parsed_message["bronze_blob_path"] = bronze_path_relative
    elif bronze_path.startswith(f"{bronze_fs_name}\\"):
        # Handle Windows-style path separators
        bronze_path_relative = bronze_path[len(f"{bronze_fs_name}\\"):]
        logger.info(f"Stripped file system prefix from bronze_path: '{bronze_path}' -> '{bronze_path_relative}'")
        bronze_path = bronze_path_relative
        # Update parsed_message so all systems use the correct relative path
        parsed_message["bronze_blob_path"] = bronze_path_relative

    # Initialize state tracker
    key_vault_url = key_vault_reader.key_vault_url
    logger.info(f"[run_id={run_id}] STEP 2: Initializing state tracker and systems 0–4")
    
    try:
        state_tracker = PipelineStateTracker(
            key_vault_url=key_vault_url,
            key_vault_reader=key_vault_reader
        )
        # Create pipeline run record
        state_tracker.create_run(
            run_id=run_id,
            training_upload_id=training_upload_id,
            bank_id=bank_id,
            status="running"
        )
        logger.info(f"[run_id={run_id}] Created pipeline run record in PostgreSQL")
    except Exception as e:
        logger.warning(f"[run_id={run_id}] Failed to initialize state tracker: {e}. Continuing without state tracking.")
        state_tracker = None

    introspector = FileIntrospector(
        datalake_client=bronze_fs,
        service_bus_writer=service_bus_writer,
        key_vault_url=key_vault_url,
        run_id=run_id,
        state_tracker=state_tracker,
    )

    schema_detector = SchemaDetector(
        datalake_client=bronze_fs,
        service_bus_writer=service_bus_writer,
        key_vault_url=key_vault_url,
        run_id=run_id,
        state_tracker=state_tracker,
    )

    data_sampler = DataSampler(
        datalake_client=bronze_fs,
        service_bus_writer=service_bus_writer,
        key_vault_url=key_vault_url,
        run_id=run_id,
        state_tracker=state_tracker,
    )

    data_analyzer = DataAnalyzer(
        service_bus_writer=service_bus_writer,
        key_vault_url=key_vault_url,
        run_id=run_id,
        state_tracker=state_tracker,
    )

    dataset_anonymizer = DatasetAnonymizer(
        service_bus_writer=service_bus_writer,
        key_vault_url=key_vault_url,
        run_id=run_id,
        state_tracker=state_tracker,
    )

    # Run pipeline with detailed logging
    try:
        # System 0: File Introspection
        logger.info("STEP 3: Running System 0 - File Introspection")
        logger.info(f"Calling introspector.introspect_file with file_path={bronze_path}")
        introspection_result = introspector.introspect_file(
            file_path=bronze_path,
            parsed_message=parsed_message,
        )
        logger.info(f"introspector.introspect_file returned successfully")
        logger.info(
            "System 0 completed. "
            f"Format hints: {getattr(introspection_result, 'format_hints', None)}"
        )

        # System 1: Schema Detection
        logger.info("STEP 4: Running System 1 - Schema Detection")
        
        # 1. Detect the format dynamically
        detected_format, format_conflict, fallback_format = schema_detector.detect_format(
            file_path=bronze_path,
            introspection_result=introspection_result,
            parsed_message=parsed_message,
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
        logger.info(
            "System 1 completed. "
            f"Detected format={schema_result.format}, encoding={schema_result.encoding}"
        )

        # System 2: Data Sampling
        logger.info("STEP 5: Running System 2 - Data Sampling")
        sampling_result = data_sampler.load_and_sample_from_datalake(
            bronze_path=bronze_path,
            format=schema_result.format,
            encoding=schema_result.encoding,
            schema_result=schema_result,
            parsed_message=parsed_message,
            introspection_result=introspection_result,
        )
        logger.info(
            "System 2 completed. "
            f"Number of samples={len(getattr(sampling_result, 'samples', []) or [])}"
        )

        # System 3: Data Analysis
        logger.info("STEP 6: Running System 3 - Data Analysis")
        analysis_result = data_analyzer.analyze(
            sampling_result=sampling_result,
            schema_result=schema_result,
            parsed_message=parsed_message,
        )
        logger.info("System 3 completed.")

        # System 4: PII Detection & Anonymization
        logger.info("STEP 7: Running System 4 - Dataset Anonymizer")
        dataset_anonymizer.set_system_results(
            introspection_result=introspection_result,
            schema_result=schema_result,
            sampling_result=sampling_result,
            analysis_result=analysis_result,
            parsed_message=parsed_message,
        )

        pii_result = dataset_anonymizer.detect_pii(
            schema_result=schema_result,
            data_analysis_result=analysis_result,
            bank_id=bank_id,
        )
        logger.info("PII detection completed.")

        samples = getattr(sampling_result, "samples", []) or []
        if not samples:
            raise ValueError("No samples available from System 2 for anonymization")

        sample_df = samples[0]
        anonymized_result = dataset_anonymizer.anonymize_dataframe(
            df=sample_df,
            pii_fields=pii_result,
            method="hash",
        )
        anonymized_df = anonymized_result.anonymized_data
        logger.info(
            "Anonymization completed. "
            f"Columns in anonymized_df={list(anonymized_df.columns)}"
        )

        # Save anonymized data to Silver
        # Note: Don't include file system name in path since FileSystemClient is already scoped to it
        # Include run_id in path for traceability
        silver_path = f"training/{bank_id}/{date}/{run_id}/{training_upload_id}.parquet"
        logger.info(f"[run_id={run_id}] STEP 8: Writing anonymized data to Silver path='{silver_path}' (file system: {silver_fs_name})")

        # Ensure silver filesystem exists (create if it doesn't)
        try:
            silver_fs.get_file_system_properties()
            logger.info(f"Silver filesystem '{silver_fs_name}' already exists")
        except Exception as e:
            if "FilesystemNotFound" in str(e) or "ContainerNotFound" in str(e):
                logger.info(f"Silver filesystem '{silver_fs_name}' does not exist. Creating it...")
                try:
                    silver_fs.create_file_system()
                    logger.info(f"Successfully created silver filesystem '{silver_fs_name}'")
                except Exception as create_error:
                    logger.error(f"Failed to create silver filesystem '{silver_fs_name}': {create_error}")
                    raise
            else:
                logger.warning(f"Error checking silver filesystem existence: {e}. Attempting to create anyway...")
                try:
                    silver_fs.create_file_system()
                    logger.info(f"Successfully created silver filesystem '{silver_fs_name}'")
                except Exception as create_error:
                    logger.error(f"Failed to create silver filesystem '{silver_fs_name}': {create_error}")
                    raise

        file_client = silver_fs.get_file_client(silver_path)
        import io  # local import to match orchestrator style

        parquet_buffer = io.BytesIO()
        anonymized_df.to_parquet(parquet_buffer, index=False, engine="pyarrow")
        parquet_buffer.seek(0)

        file_client.upload_data(data=parquet_buffer.read(), overwrite=True)
        logger.info(f"Successfully wrote anonymized data to Silver at '{silver_path}'")

        # Create and write llm_context.json to the same folder
        import json
        llm_context_path = f"training/{bank_id}/{date}/{run_id}/llm_context.json"
        
        # Custom encoder to handle bytes objects inside the Pydantic models
        class BytesEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, bytes):
                    try:
                        return obj.decode('utf-8')
                    except UnicodeDecodeError:
                        return obj.hex()
                return super().default(obj)
        
        # Helper to convert Pydantic models to dict if needed
        def _to_dict(obj):
            if hasattr(obj, "model_dump"):
                return obj.model_dump()
            elif hasattr(obj, "dict"):
                return obj.dict()
            return obj if isinstance(obj, dict) else str(obj)

        llm_context_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "bank_id": bank_id,
            "pipeline_timestamp": datetime.utcnow().isoformat(),
            "silver_parquet_path": silver_path,
            "bronze_source_path": bronze_path,
            "introspection": _to_dict(introspection_result),
            "schema_detection": _to_dict(schema_result),
            "data_analysis": _to_dict(analysis_result),
            "pii_detection": _to_dict(pii_result)
        }

        context_file_client = silver_fs.get_file_client(llm_context_path)
        context_file_client.upload_data(
            data=json.dumps(llm_context_data, indent=2, cls=BytesEncoder).encode('utf-8'),
            overwrite=True
        )
        logger.info(f"Successfully wrote llm_context.json to Silver at '{llm_context_path}'")

        # Publish transformed status
        logger.info("STEP 9: Publishing transformed status via ServiceBusWriter")
        try:
            features_mapped = {
                "count": (
                    len(schema_result.column_names)
                    if getattr(schema_result, "column_names", None)
                    else (getattr(schema_result, "column_count", 0) or 0)
                ),
                "mappings": {},  # To be populated by LLM systems later (coder/judge)
            }
            schema_template_id = "pending"  # Will be set by System 5 (LLM Schema Mapping)

            service_bus_writer.publish_transformed(
                training_upload_id=training_upload_id,
                transformed_file_path=silver_path,
                features_mapped=features_mapped,
                schema_template_id=schema_template_id,
                run_id=run_id,
            )
            logger.info(f"[run_id={run_id}] Transformed status published successfully.")
        except Exception as e:
            logger.error(f"[run_id={run_id}] Failed to publish transformed status: {e}")

        # Update pipeline run status to completed
        if state_tracker:
            try:
                state_tracker.update_run_status(
                    run_id=run_id,
                    status="completed",
                    current_system="completed",
                    silver_path=silver_path
                )
                logger.info(f"[run_id={run_id}] Updated pipeline run status to completed")
            except Exception as e:
                logger.warning(f"[run_id={run_id}] Failed to update pipeline run status: {e}")

        logger.info(
            f"[run_id={run_id}] Pipeline completed successfully for "
            f"training_upload_id={training_upload_id}, bank_id={bank_id}"
        )
        return silver_path

    except Exception as e:
        # Map and log error using the same conventions as orchestrator
        logger.error(f"[run_id={run_id}] Pipeline failed with an exception", exc_info=True)

        system_name = "Unknown System"
        if "introspection_result" not in locals():
            system_name = "System 0: File Introspection"
        elif "schema_result" not in locals():
            system_name = "System 1: Schema Detection"
        elif "sampling_result" not in locals():
            system_name = "System 2: Data Sampling"
        elif "analysis_result" not in locals():
            system_name = "System 3: Data Analysis"
        else:
            system_name = "System 4: Dataset Anonymizer"

        # Update pipeline run status to failed
        if state_tracker:
            try:
                state_tracker.update_run_status(
                    run_id=run_id,
                    status="failed",
                    current_system=system_name.lower().replace("system ", "").replace(": ", "-").split("-")[0],
                    error_message=str(e),
                    error_system=system_name
                )
                logger.info(f"[run_id={run_id}] Updated pipeline run status to failed")
            except Exception as state_error:
                logger.warning(f"[run_id={run_id}] Failed to update pipeline run status: {state_error}")

        # Build error message for logs (no re-raise here; caller decides)
        error_str = str(e)
        error_type = type(e).__name__
        stack_trace = traceback.format_exc()
        error_stage = get_stage_name(system_name)

        error_code, user_message, technical_summary = map_error_to_user_message(
            error_type=error_type,
            error_message=error_str,
            system_name=system_name,
            stack_trace=stack_trace,
        )

        logger.error(
            "Error summary: "
            f"stage={error_stage}, "
            f"error_code={error_code}, "
            f"user_message={user_message}, "
            f"technical_summary={technical_summary}"
        )

        # Best-effort: publish error messages using ServiceBusWriter
        try:
            service_bus_writer.publish_system_failed(
                training_upload_id=training_upload_id,
                bank_id=bank_id,
                system_name=system_name,
                error={
                    "message": error_str,
                    "type": error_type,
                    "stack_trace": stack_trace,
                    "bronze_path": bronze_path,
                },
                run_id=run_id,
            )
        except Exception as pub_e:
            logger.error(f"[run_id={run_id}] Failed to publish internal system_failed message: {pub_e}")

        try:
            service_bus_writer.publish_backend_error(
                training_upload_id=training_upload_id,
                error_type=error_type,
                error_message=user_message,
                system_name=system_name,
                stack_trace=stack_trace,
                run_id=run_id,
            )
        except Exception as pub_e:
            logger.error(f"[run_id={run_id}] Failed to publish backend error message: {pub_e}")

        # Propagate the original exception upwards
        raise


# ============================================================
# Main entry point
# ============================================================

def main() -> None:
    """
    Entry point for running the full pipeline from a single Service Bus message.
    """
    parser = argparse.ArgumentParser(
        description="Run schema-mapping Systems 0-4 from one Service Bus message."
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Force DEBUG logging for this run (overrides LOG_LEVEL).",
    )
    args, _unknown = parser.parse_known_args()
    configure_logging(force_debug=args.verbose)
    # Load .env from project root (parent of scripts/ directory)
    dotenv_path = os.path.join(PROJECT_ROOT, ".env")
    load_dotenv(dotenv_path)
    validate_required_env()

    logger.info("=== RUNNING FULL PIPELINE FROM SERVICE BUS MESSAGE ===")
    env = os.getenv("ENVIRONMENT", "local")
    logger.info(f"Environment: {env}")

    key_vault_url = os.getenv("KEY_VAULT_URL")
    storage_account_name_secret = os.getenv("DATALAKE_STORAGE_ACCOUNT_NAME_SECRET")
    topic_name = os.getenv("SERVICEBUS_TOPIC_NAME")
    subscription_name = os.getenv("SERVICEBUS_SUBSCRIPTION_NAME")

    logger.info(f"KEY_VAULT_URL={key_vault_url}")
    logger.info(f"SERVICEBUS_TOPIC_NAME={topic_name}")
    logger.info(f"SERVICEBUS_SUBSCRIPTION_NAME={subscription_name}")
    logger.info(f"DATALAKE_STORAGE_ACCOUNT_NAME_SECRET={storage_account_name_secret}")
    logger.info(f"BRONZE_FILE_SYSTEM_NAME={os.getenv('BRONZE_FILE_SYSTEM_NAME')}")
    logger.info(f"SILVER_FILE_SYSTEM_NAME={os.getenv('SILVER_FILE_SYSTEM_NAME')}")

    # Initialize helpers
    try:
        key_vault_reader = KeyVaultReader(key_vault_url=key_vault_url)
    except KeyVaultError as e:
        logger.error(f"Failed to initialize KeyVaultReader: {e}")
        sys.exit(1)

    try:
        datalake_client = get_datalake_client(
            key_vault_reader=key_vault_reader,
            storage_account_name_secret=storage_account_name_secret,
        )
    except Exception as e:
        logger.error(f"Failed to initialize DataLakeServiceClient: {e}")
        sys.exit(1)

    try:
        # For local testing, use connection string from environment variable to bypass Key Vault
        service_bus_conn_str = os.getenv("ServiceBusConnectionString")
        if service_bus_conn_str:
            logger.info("Using ServiceBusConnectionString from environment (bypassing Key Vault for local testing)")
            service_bus_writer = ServiceBusWriter(connection_string=service_bus_conn_str)
        else:
            logger.info("ServiceBusConnectionString not in environment, falling back to Key Vault")
            service_bus_writer = ServiceBusWriter(key_vault_url=key_vault_url)
    except ServiceBusClientError as e:
        logger.error(f"Failed to initialize ServiceBusWriter: {e}")
        sys.exit(1)

    sb_client = get_servicebus_client()

    # Receive and process exactly one message
    receiver = None
    message = None
    renewer = None
    try:
        # Keep ServiceBusClient alive for the whole receive + process + settle lifecycle
        with sb_client:
            receiver, message, message_data = receive_one_message(
                sb_client=sb_client,
                topic_name=topic_name,
                subscription_name=subscription_name,
            )

            # Set up auto lock renewal for long-running pipeline (max 10 minutes)
            # Service Bus max lock duration is 5 minutes, so we renew for up to 10 minutes
            if receiver and message:
                renewer = AutoLockRenewer()
                # Register message for auto lock renewal (renews every ~30 seconds)
                # max_lock_renewal_duration: 600 seconds (10 minutes) - enough for pipeline
                renewer.register(receiver, message, max_lock_renewal_duration=600)
                logger.info("Registered message for automatic lock renewal (max 10 minutes)")

            silver_path = run_pipeline_from_message(
                message_data=message_data,
                key_vault_reader=key_vault_reader,
                datalake_client=datalake_client,
                service_bus_writer=service_bus_writer,
                message_id=message.message_id if message else None,
            )

            # Complete message after successful processing
            if receiver and message:
                # Stop auto renewal before completing
                if renewer:
                    try:
                        renewer.close()
                        logger.debug("Stopped auto lock renewal")
                    except Exception as e:
                        logger.warning(f"Error stopping auto lock renewal: {e}")
                
                logger.info("Completing Service Bus message (success path)")
                try:
                    receiver.complete_message(message)
                except MessageLockLostError as lock_error:
                    logger.error(f"Message lock expired before completion: {lock_error}")
                    logger.warning("Pipeline completed successfully but message lock expired. Message may be reprocessed.")
                    # Don't raise - pipeline succeeded, just couldn't complete message
                except Exception as complete_error:
                    logger.error(f"Failed to complete message: {complete_error}")
                    raise
                finally:
                    try:
                        receiver.close()
                    except Exception:
                        pass

        logger.info("=== RUN SUMMARY ===")
        logger.info(f"Status: SUCCESS")
        logger.info(f"Anonymized Silver Path: {silver_path}")

    except ServiceBusMessageError as e:
        # Special handling for messages rejected due to missing fields (often old messages)
        # Log as warning if it's a missing field issue (expected for old messages)
        if "Missing required field" in str(e):
            logger.warning(f"[SKIPPING OLD MESSAGE] Message rejected: {e}. This is likely an old message format. Message will be abandoned.")
        else:
            logger.error(f"Message rejected: {e}", exc_info=True)
        if receiver and message:
            try:
                # Try to extract training_upload_id from message for error reporting
                try:
                    message_data_for_error = message_data if 'message_data' in locals() else {}
                    training_upload_id = message_data_for_error.get('training_upload_id') or message_data_for_error.get('upload_id', 'unknown')
                    
                    # Publish error to error subscription
                    try:
                        service_bus_writer.publish_backend_error(
                            training_upload_id=training_upload_id,
                            error_type="ServiceBusMessageError",
                            error_message=str(e),
                            system_name="Message Validation",
                            stack_trace=traceback.format_exc(),
                            run_id=None  # No run_id available for rejected messages
                        )
                        logger.info(f"Published rejection error to error subscription for training_upload_id: {training_upload_id}")
                    except Exception as pub_e:
                        logger.error(f"Failed to publish rejection error: {pub_e}")
                except Exception:
                    pass  # Best effort
                
                logger.info("Abandoning Service Bus message due to rejection")
                receiver.abandon_message(message)
            except MessageLockLostError as lock_error:
                logger.warning(f"Message lock expired, cannot abandon: {lock_error}")
            except Exception as abandon_e:
                # Check if receiver is closed
                if "shutdown" in str(abandon_e).lower() or "closed" in str(abandon_e).lower():
                    logger.debug(f"Receiver already closed, cannot abandon: {abandon_e}")
                else:
                    logger.error(f"Failed to abandon Service Bus message: {abandon_e}")
            finally:
                try:
                    receiver.close()
                except Exception:
                    pass

        logger.info("=== RUN SUMMARY ===")
        logger.info("Status: FAILURE (Message Rejected)")
        logger.info(f"Error: {e}")
        sys.exit(1)
    
    except MessageLockLostError as lock_error:
        # Special handling for lock expiration
        logger.error(f"Message lock expired during processing: {lock_error}", exc_info=True)
        logger.warning("Pipeline processing exceeded message lock duration. Message will be redelivered.")
        
        # Stop auto renewal if it was started
        if renewer:
            try:
                renewer.close()
            except Exception:
                pass
        
        # Try to abandon, but don't fail if receiver is already closed
        if receiver and message:
            try:
                receiver.abandon_message(message)
                logger.info("Abandoned message due to lock expiration")
            except Exception as abandon_e:
                # Receiver may already be closed - this is expected
                if "shutdown" in str(abandon_e).lower() or "closed" in str(abandon_e).lower():
                    logger.debug(f"Receiver already closed, cannot abandon: {abandon_e}")
                else:
                    logger.error(f"Failed to abandon message: {abandon_e}")
            finally:
                try:
                    receiver.close()
                except Exception:
                    pass
        
        logger.info("=== RUN SUMMARY ===")
        logger.info("Status: FAILURE (Lock Expired)")
        logger.info(f"Error: Message lock expired during processing. Pipeline may have partially completed.")
        sys.exit(1)
    
    except Exception as e:
        logger.error(f"Pipeline run failed: {e}", exc_info=True)
        
        # Stop auto renewal if it was started
        if renewer:
            try:
                renewer.close()
            except Exception:
                pass
        
        if receiver and message:
            try:
                logger.info("Abandoning Service Bus message due to failure")
                receiver.abandon_message(message)
            except MessageLockLostError as lock_error:
                logger.warning(f"Message lock expired, cannot abandon: {lock_error}")
            except Exception as abandon_e:
                # Check if receiver is closed
                if "shutdown" in str(abandon_e).lower() or "closed" in str(abandon_e).lower():
                    logger.debug(f"Receiver already closed, cannot abandon: {abandon_e}")
                else:
                    logger.error(f"Failed to abandon Service Bus message: {abandon_e}")
            finally:
                try:
                    receiver.close()
                except Exception:
                    pass

        logger.info("=== RUN SUMMARY ===")
        logger.info("Status: FAILURE")
        logger.info(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

