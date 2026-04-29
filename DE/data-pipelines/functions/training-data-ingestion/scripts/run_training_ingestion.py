"""
Training Data Ingestion Orchestrator
Batch processes messages from data-awaits-ingestion topic
and performs file ingestion to bronze layer with verification
"""

import json
import logging
import os
import sys
import uuid
import enum
from datetime import datetime
from typing import Dict, Any, Optional, List, Set
from pathlib import Path

# Add parent directories to path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))  # scripts/ directory
TRAINING_INGESTION_ROOT = os.path.dirname(CURRENT_DIR)  # training-data-ingestion directory

# Add paths for imports - MUST be done before any utils imports
# Insert at the beginning to ensure it's checked first
if TRAINING_INGESTION_ROOT not in sys.path:
    sys.path.insert(0, TRAINING_INGESTION_ROOT)

# Debug: Verify path is set (can be removed later)
import logging
_logger = logging.getLogger(__name__)
_logger.debug(f"TRAINING_INGESTION_ROOT added to sys.path: {TRAINING_INGESTION_ROOT}")
_logger.debug(f"sys.path contains: {[p for p in sys.path if 'training-data-ingestion' in p]}")

from azure.servicebus import ServiceBusClient, AutoLockRenewer, ServiceBusMessage
from azure.servicebus.exceptions import MessageLockLostError
from azure.identity import DefaultAzureCredential, AzureCliCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

# Import training-specific utilities (self-contained, no dependency on schema-mapping-service)
from utils.training_key_vault_reader import TrainingKeyVaultReader, TrainingKeyVaultError
from utils.training_service_bus_reader import TrainingServiceBusReader
from utils.training_service_bus_writer import TrainingServiceBusWriter
from utils.training_postgres_client import TrainingPostgresClient

# Load local utilities
from utils.storage_client import StorageClient
from utils.checksum_calculator import ChecksumCalculator
from utils.training_uploads_client import TrainingUploadsClient
from utils.bronze_ingestion_log_client import BronzeIngestionLogClient

# Alias for backward compatibility in the code
KeyVaultReader = TrainingKeyVaultReader
KeyVaultError = TrainingKeyVaultError
ServiceBusReader = TrainingServiceBusReader
ServiceBusWriter = TrainingServiceBusWriter
PostgresClient = TrainingPostgresClient

# Try to import dotenv
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

logger = logging.getLogger(__name__)


# Enums for status values
class TrainingUploadStatus(str, enum.Enum):
    """Enum for training_uploads.status values"""
    INGESTING = "ingesting"
    INGESTED = "ingested"
    TRANSFORMING = "transforming"
    TRANSFORMED = "transformed"
    TRAINING = "training"
    TRAINED = "trained"
    ERROR = "error"
    FAILED = "failed"
    COMPLETED = "completed"


class IngestionStatus(str, enum.Enum):
    """Enum for bronze_ingestion_log.ingestion_status values"""
    SUCCESS = "success"
    FILE_NOT_FOUND = "file_not_found"
    COPY_FAILED = "copy_failed"
    VERIFICATION_FAILED = "verification_failed"


def _get_env_or_kv(env_var_name: str, kv_reader: KeyVaultReader, kv_secret_name: str) -> Optional[str]:
    """Get environment variable, or from Key Vault if it's a Key Vault reference or not set"""
    value = os.getenv(env_var_name)
    
    # If it's a Key Vault reference (unresolved), use Key Vault SDK
    if value and value.strip().startswith("@Microsoft.KeyVault"):
        try:
            value = kv_reader.get_secret(kv_secret_name)
            logger.info(f"Retrieved {env_var_name} from Key Vault (was Key Vault reference)")
            return value
        except KeyVaultError:
            pass
    
    # If not set, try Key Vault
    if not value:
        try:
            value = kv_reader.get_secret(kv_secret_name)
            logger.info(f"Retrieved {env_var_name} from Key Vault")
            return value
        except KeyVaultError:
            pass
    
    return value


def get_environment() -> str:
    """Determine environment (local or azure)"""
    env = os.getenv("ENVIRONMENT", "local").lower()
    if env not in ["local", "azure"]:
        env = "local"
    return env


def parse_message_body(message) -> Dict[str, Any]:
    """Parse message body from Service Bus message"""
    body = None
    
    # Try body_as_str() first
    if hasattr(message, 'body_as_str'):
        try:
            body = message.body_as_str()
        except Exception:
            pass
    
    # Try body_as_bytes() and decode
    if body is None and hasattr(message, 'body_as_bytes'):
        try:
            body_bytes = message.body_as_bytes()
            body = body_bytes.decode('utf-8') if isinstance(body_bytes, bytes) else str(body_bytes)
        except Exception:
            pass
    
    # Fallback to message.body
    if body is None:
        body = message.body
        if isinstance(body, bytes):
            body = body.decode('utf-8')
        elif not isinstance(body, str):
            if hasattr(body, '__iter__') and not isinstance(body, (str, bytes)):
                try:
                    chunks = list(body)
                    if chunks and isinstance(chunks[0], bytes):
                        body = b''.join(chunks).decode('utf-8')
                    else:
                        body = ''.join(str(chunk) for chunk in chunks)
                except Exception:
                    body = str(body)
            else:
                body = str(body)
    
    return json.loads(body)


# Helper functions for processing steps (split from process_single_message)
def calculate_source_checksum(
    checksum_calculator: ChecksumCalculator,
    blob_storage_account_name: str,
    blob_container_name: str,
    raw_file_path: str,
    run_id: str,
    training_upload_id: str,
    training_uploads_client: TrainingUploadsClient,
    bronze_log_client: BronzeIngestionLogClient,
    file_size_bytes: Optional[int]
) -> Optional[str]:
    """
    Step 1: Calculate source file checksum
    
    Returns:
        Source checksum string if successful, None if file not found or error
    """
    source_blob_url = f"https://{blob_storage_account_name}.blob.core.windows.net/{blob_container_name}/{raw_file_path}"
    
    try:
        source_checksum = checksum_calculator.calculate_checksum(source_blob_url)
        return source_checksum
    except ResourceNotFoundError:
        error_msg = f"File not found in data container: {raw_file_path}"
        logger.warning(f"[run_id={run_id}] {error_msg}")
        training_uploads_client.update_status_file_not_found(training_upload_id, error_msg)
        bronze_log_client.insert_log(
            training_upload_id=training_upload_id,
            run_id=run_id,
            source_blob_path=raw_file_path,
            source_checksum_sha256="",
            source_file_size_bytes=0,
            bronze_blob_path="",
            bronze_checksum_sha256="",
            bronze_file_size_bytes=0,
            ingestion_status=IngestionStatus.FILE_NOT_FOUND.value,
            error_message=error_msg
        )
        return None
    except Exception as e:
        error_msg = f"Error calculating source checksum: {str(e)}"
        logger.error(f"[run_id={run_id}] {error_msg}", exc_info=True)
        training_uploads_client.update_status_copy_failed(training_upload_id, error_msg)
        return None


def copy_file_to_bronze(
    storage_client: StorageClient,
    blob_container_name: str,
    raw_file_path: str,
    bronze_container_name: str,
    bronze_relative_path: str,
    run_id: str,
    training_upload_id: str,
    training_uploads_client: TrainingUploadsClient,
    bronze_log_client: BronzeIngestionLogClient,
    source_checksum: str,
    file_size_bytes: Optional[int]
) -> Optional[tuple[bool, str]]:
    """
    Step 2: Copy file to bronze layer
    
    Returns:
        Tuple of (used_blob_api: bool, bronze_path: str) if successful, None on error
    """
    try:
        used_blob_api, bronze_path_returned = storage_client.copy_blob_to_datalake(
            source_container=blob_container_name,
            source_blob_path=raw_file_path,
            destination_filesystem=bronze_container_name,
            destination_path=bronze_relative_path,
            overwrite=True
        )
        logger.info(f"[run_id={run_id}] File copied to bronze: {bronze_path_returned}")
        return (used_blob_api, bronze_path_returned)
    except Exception as e:
        error_msg = f"Copy failed: {str(e)}"
        logger.error(f"[run_id={run_id}] {error_msg}", exc_info=True)
        training_uploads_client.update_status_copy_failed(training_upload_id, error_msg)
        bronze_log_client.insert_log(
            training_upload_id=training_upload_id,
            run_id=run_id,
            source_blob_path=raw_file_path,
            source_checksum_sha256=source_checksum,
            source_file_size_bytes=file_size_bytes or 0,
            bronze_blob_path="",
            bronze_checksum_sha256="",
            bronze_file_size_bytes=0,
            ingestion_status=IngestionStatus.COPY_FAILED.value,
            error_message=error_msg
        )
        return None


def verify_file_exists_after_copy(
    storage_client: StorageClient,
    bronze_container_name: str,
    bronze_relative_path: str,
    bronze_path_returned: str,
    used_blob_api: bool,
    run_id: str,
    training_upload_id: str,
    training_uploads_client: TrainingUploadsClient,
    bronze_log_client: BronzeIngestionLogClient,
    raw_file_path: str,
    source_checksum: str,
    file_size_bytes: Optional[int]
) -> bool:
    """
    Verify file actually exists after copy (before proceeding with verification)
    
    Returns:
        True if file exists and has non-zero size, False otherwise
    """
    try:
        bronze_file_size_check = storage_client.get_file_size(bronze_container_name, bronze_relative_path, use_blob_api=used_blob_api)
        if bronze_file_size_check == 0:
            raise Exception("File exists but has zero size")
        logger.info(f"[run_id={run_id}] Verified file exists in bronze: {bronze_path_returned} ({bronze_file_size_check} bytes)")
        return True
    except Exception as e:
        error_msg = f"File verification failed after copy: {str(e)}"
        logger.error(f"[run_id={run_id}] {error_msg}", exc_info=True)
        training_uploads_client.update_status_copy_failed(training_upload_id, error_msg)
        bronze_log_client.insert_log(
            training_upload_id=training_upload_id,
            run_id=run_id,
            source_blob_path=raw_file_path,
            source_checksum_sha256=source_checksum,
            source_file_size_bytes=file_size_bytes or 0,
            bronze_blob_path=bronze_path_returned,
            bronze_checksum_sha256="",
            bronze_file_size_bytes=0,
            ingestion_status=IngestionStatus.COPY_FAILED.value,
            error_message=error_msg
        )
        return False


def calculate_bronze_checksum(
    checksum_calculator: ChecksumCalculator,
    datalake_storage_account_name: str,
    bronze_path_returned: str,
    used_blob_api: bool,
    run_id: str,
    training_upload_id: str,
    training_uploads_client: TrainingUploadsClient,
    bronze_log_client: BronzeIngestionLogClient,
    raw_file_path: str,
    source_checksum: str,
    file_size_bytes: Optional[int],
    bronze_path: str
) -> Optional[str]:
    """
    Step 3: Calculate bronze file checksum
    
    Returns:
        Bronze checksum string if successful, None on error
    """
    # Use the correct endpoint based on which API was used
    if used_blob_api:
        # File was written via Blob API, use Blob endpoint for checksum
        bronze_blob_url = f"https://{datalake_storage_account_name}.blob.core.windows.net/{bronze_path_returned}"
    else:
        # File was written via DFS API, use DFS endpoint for checksum
        bronze_blob_url = f"https://{datalake_storage_account_name}.dfs.core.windows.net/{bronze_path_returned}"
    
    try:
        bronze_checksum = checksum_calculator.calculate_checksum(bronze_blob_url)
        return bronze_checksum
    except Exception as e:
        error_msg = f"Error calculating bronze checksum: {str(e)}"
        logger.error(f"[run_id={run_id}] {error_msg}", exc_info=True)
        training_uploads_client.update_status_verification_failed(training_upload_id, error_msg)
        bronze_log_client.insert_log(
            training_upload_id=training_upload_id,
            run_id=run_id,
            source_blob_path=raw_file_path,
            source_checksum_sha256=source_checksum,
            source_file_size_bytes=file_size_bytes or 0,
            bronze_blob_path=bronze_path,
            bronze_checksum_sha256="",
            bronze_file_size_bytes=0,
            ingestion_status=IngestionStatus.VERIFICATION_FAILED.value,
            error_message=error_msg
        )
        return None


def verify_checksums_match(
    source_checksum: str,
    bronze_checksum: str,
    run_id: str,
    training_upload_id: str,
    training_uploads_client: TrainingUploadsClient,
    bronze_log_client: BronzeIngestionLogClient,
    raw_file_path: str,
    file_size_bytes: Optional[int],
    bronze_path: str
) -> bool:
    """
    Verify checksums match
    
    Returns:
        True if checksums match, False otherwise
    """
    if source_checksum != bronze_checksum:
        error_msg = f"Checksum mismatch: source={source_checksum[:16]}..., bronze={bronze_checksum[:16]}..."
        logger.error(f"[run_id={run_id}] {error_msg}")
        training_uploads_client.update_status_verification_failed(training_upload_id, error_msg)
        bronze_log_client.insert_log(
            training_upload_id=training_upload_id,
            run_id=run_id,
            source_blob_path=raw_file_path,
            source_checksum_sha256=source_checksum,
            source_file_size_bytes=file_size_bytes or 0,
            bronze_blob_path=bronze_path,
            bronze_checksum_sha256=bronze_checksum,
            bronze_file_size_bytes=0,
            ingestion_status=IngestionStatus.VERIFICATION_FAILED.value,
            error_message=error_msg
        )
        return False
    return True


def get_bronze_file_size(
    storage_client: StorageClient,
    bronze_container_name: str,
    bronze_relative_path: str,
    used_blob_api: bool,
    run_id: str,
    training_upload_id: str,
    training_uploads_client: TrainingUploadsClient
) -> Optional[int]:
    """
    Step 4: Get bronze file size (use same API that was used to write the file)
    
    Returns:
        File size in bytes if successful, None on error
    """
    try:
        bronze_file_size = storage_client.get_file_size(bronze_container_name, bronze_relative_path, use_blob_api=used_blob_api)
        return bronze_file_size
    except Exception as e:
        error_msg = f"Error getting bronze file size: {str(e)}"
        logger.error(f"[run_id={run_id}] {error_msg}", exc_info=True)
        training_uploads_client.update_status_verification_failed(training_upload_id, error_msg)
        return None


def update_database_status_ingested(
    training_uploads_client: TrainingUploadsClient,
    training_upload_id: str,
    run_id: str
) -> bool:
    """
    Step 5: Update database status to 'ingested'
    
    Returns:
        True if successful, False otherwise
    """
    try:
        training_uploads_client.update_status_ingested(training_upload_id)
        return True
    except Exception as e:
        error_msg = f"Database update failed: {str(e)}"
        logger.error(f"[run_id={run_id}] {error_msg}", exc_info=True)
        return False


def insert_bronze_ingestion_log(
    bronze_log_client: BronzeIngestionLogClient,
    training_upload_id: str,
    run_id: str,
    raw_file_path: str,
    source_checksum: str,
    file_size_bytes: Optional[int],
    bronze_path: str,
    bronze_checksum: str,
    bronze_file_size: int
) -> None:
    """
    Step 6: Insert bronze ingestion log (non-critical - logs warning on failure)
    """
    try:
        bronze_log_client.insert_log(
            training_upload_id=training_upload_id,
            run_id=run_id,
            source_blob_path=raw_file_path,
            source_checksum_sha256=source_checksum,
            source_file_size_bytes=file_size_bytes or 0,
            bronze_blob_path=bronze_path,
            bronze_checksum_sha256=bronze_checksum,
            bronze_file_size_bytes=bronze_file_size,
            ingestion_status=IngestionStatus.SUCCESS.value,
            error_message=None
        )
    except Exception as e:
        logger.warning(f"[run_id={run_id}] Failed to insert bronze log (non-critical): {str(e)}")


def publish_success_message(
    service_bus_writer: ServiceBusWriter,
    training_upload_id: str,
    data_source_id: str,
    bronze_path: str,
    run_id: str,
    *,
    file_format: Optional[str] = None,
    source_blob_path: Optional[str] = None,
    row_count: Optional[int] = None,
) -> bool:
    """
    Step 7: Publish success message to data-ingested topic
    
    Returns:
        True if successful, False otherwise
    """
    try:
        success_message = {
            "training_upload_id": training_upload_id,
            "bank_id": data_source_id,  # Use data_source_id as bank_id
            "bronze_blob_path": bronze_path,
            "run_id": run_id
        }
        if file_format is not None:
            success_message["file_format"] = file_format
        if source_blob_path is not None:
            success_message["source_blob_path"] = source_blob_path
        if row_count is not None:
            success_message["row_count"] = row_count
        # Use ServiceBusWriter's _publish_to_subscription method
        service_bus_writer._publish_to_subscription(
            topic_name=service_bus_writer.TOPIC_BACKEND,
            subscription_name="start-transformation",
            message_data=success_message,
            run_id=run_id
        )
        logger.info(f"[run_id={run_id}] Success message published to data-ingested")
        return True
    except Exception as e:
        error_msg = f"Service Bus publish failed: {str(e)}"
        logger.error(f"[run_id={run_id}] {error_msg}", exc_info=True)
        return False


def process_single_message(
    training_upload_id: str,
    message_data: Dict[str, Any],
    metadata: Dict[str, Any],
    run_id: str,
    storage_client: StorageClient,
    checksum_calculator: ChecksumCalculator,
    training_uploads_client: TrainingUploadsClient,
    bronze_log_client: BronzeIngestionLogClient,
    service_bus_writer: ServiceBusWriter,
    blob_storage_account_name: str,
    datalake_storage_account_name: str,
    blob_container_name: str,
    bronze_container_name: str
) -> bool:
    """
    Process a single message: copy file, verify, update DB, publish success message
    
    Returns:
        True if successful, False otherwise
        
    Note:
        Azure SDK automatically retries transient failures (network errors, throttling, etc.)
        with exponential backoff. No explicit retry logic is needed.
    """
    try:
        data_source_id = str(metadata.get("data_source_id"))
        file_format = metadata.get("file_format")
        file_size_bytes = metadata.get("file_size_bytes")
        raw_file_path = metadata.get("raw_file_path")
        
        logger.info(f"[run_id={run_id}] Processing: data_source_id={data_source_id}, file_format={file_format}")
        
        # Step 1: Calculate source file checksum
        source_checksum = calculate_source_checksum(
            checksum_calculator=checksum_calculator,
            blob_storage_account_name=blob_storage_account_name,
            blob_container_name=blob_container_name,
            raw_file_path=raw_file_path,
            run_id=run_id,
            training_upload_id=training_upload_id,
            training_uploads_client=training_uploads_client,
            bronze_log_client=bronze_log_client,
            file_size_bytes=file_size_bytes
        )
        if source_checksum is None:
            return False
        
        # Step 2: Copy file to bronze layer
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        file_name = metadata.get('file_name', training_upload_id)
        # Remove extension from file_name if it has one, then add the correct extension
        if '.' in file_name:
            file_name = file_name.rsplit('.', 1)[0]
        bronze_relative_path = f"training/{data_source_id}/{date_str}/{file_name}.{file_format}"
        bronze_path = f"{bronze_container_name}/{bronze_relative_path}"
        
        copy_result = copy_file_to_bronze(
            storage_client=storage_client,
            blob_container_name=blob_container_name,
            raw_file_path=raw_file_path,
            bronze_container_name=bronze_container_name,
            bronze_relative_path=bronze_relative_path,
            run_id=run_id,
            training_upload_id=training_upload_id,
            training_uploads_client=training_uploads_client,
            bronze_log_client=bronze_log_client,
            source_checksum=source_checksum,
            file_size_bytes=file_size_bytes
        )
        if copy_result is None:
            return False
        used_blob_api, bronze_path_returned = copy_result
        
        # Verify file actually exists after copy
        if not verify_file_exists_after_copy(
            storage_client=storage_client,
            bronze_container_name=bronze_container_name,
            bronze_relative_path=bronze_relative_path,
            bronze_path_returned=bronze_path_returned,
            used_blob_api=used_blob_api,
            run_id=run_id,
            training_upload_id=training_upload_id,
            training_uploads_client=training_uploads_client,
            bronze_log_client=bronze_log_client,
            raw_file_path=raw_file_path,
            source_checksum=source_checksum,
            file_size_bytes=file_size_bytes
        ):
            return False
        
        # Step 3: Calculate bronze file checksum
        bronze_checksum = calculate_bronze_checksum(
            checksum_calculator=checksum_calculator,
            datalake_storage_account_name=datalake_storage_account_name,
            bronze_path_returned=bronze_path_returned,
            used_blob_api=used_blob_api,
            run_id=run_id,
            training_upload_id=training_upload_id,
            training_uploads_client=training_uploads_client,
            bronze_log_client=bronze_log_client,
            raw_file_path=raw_file_path,
            source_checksum=source_checksum,
            file_size_bytes=file_size_bytes,
            bronze_path=bronze_path
        )
        if bronze_checksum is None:
            return False
        
        # Verify checksums match
        if not verify_checksums_match(
            source_checksum=source_checksum,
            bronze_checksum=bronze_checksum,
            run_id=run_id,
            training_upload_id=training_upload_id,
            training_uploads_client=training_uploads_client,
            bronze_log_client=bronze_log_client,
            raw_file_path=raw_file_path,
            file_size_bytes=file_size_bytes,
            bronze_path=bronze_path
        ):
            return False
        
        # Step 4: Get bronze file size
        bronze_file_size = get_bronze_file_size(
            storage_client=storage_client,
            bronze_container_name=bronze_container_name,
            bronze_relative_path=bronze_relative_path,
            used_blob_api=used_blob_api,
            run_id=run_id,
            training_upload_id=training_upload_id,
            training_uploads_client=training_uploads_client
        )
        if bronze_file_size is None:
            return False
        
        # Step 5: Update database status to 'ingested'
        if not update_database_status_ingested(
            training_uploads_client=training_uploads_client,
            training_upload_id=training_upload_id,
            run_id=run_id
        ):
            return False
        
        # Step 6: Insert bronze ingestion log
        insert_bronze_ingestion_log(
            bronze_log_client=bronze_log_client,
            training_upload_id=training_upload_id,
            run_id=run_id,
            raw_file_path=raw_file_path,
            source_checksum=source_checksum,
            file_size_bytes=file_size_bytes,
            bronze_path=bronze_path,
            bronze_checksum=bronze_checksum,
            bronze_file_size=bronze_file_size
        )
        
        # Step 7: Publish success message
        record_count = metadata.get("record_count")
        if not publish_success_message(
            service_bus_writer=service_bus_writer,
            training_upload_id=training_upload_id,
            data_source_id=data_source_id,
            bronze_path=bronze_path,
            run_id=run_id,
            file_format=file_format,
            source_blob_path=raw_file_path,
            row_count=record_count,
        ):
            return False
        
        logger.info(f"[run_id={run_id}] ✅ Message processed successfully")
        return True
        
    except Exception as e:
        logger.error(f"[run_id={run_id}] Unexpected error processing message: {str(e)}", exc_info=True)
        return False


def main():
    """Main batch processing orchestration (standalone script or timer-driven run)
    
    NOTE: This function is NOT used by the Azure Function Service Bus trigger.
    The Function uses a separate single-message path that does not peek or
    receive messages itself, to avoid double-reading from Service Bus.
    """
    # Load environment variables
    if HAS_DOTENV:
        env_path = os.path.join(TRAINING_INGESTION_ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
    
    # Determine environment
    env = get_environment()
    logger.info(f"Environment: {env}")
    
    # Configuration
    KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
    if not KEY_VAULT_URL:
        raise ValueError("KEY_VAULT_URL environment variable is required")
    
    SERVICEBUS_TOPIC_NAME = os.getenv("SERVICEBUS_TOPIC_NAME", "data-awaits-ingestion")
    SERVICEBUS_SUBSCRIPTION_NAME = os.getenv("SERVICEBUS_SUBSCRIPTION_NAME", "temp-peek-subscription")
    
    # Check for storage account names in multiple formats (local vs Azure naming)
    # Local uses: DATALAKE_STORAGE_ACCOUNT_NAME, BLOB_STORAGE_ACCOUNT_NAME
    # Azure uses: DataLakeStorageAccountName, BlobStorageAccountName (from Key Vault references)
    DATALAKE_STORAGE_ACCOUNT_NAME = (
        os.getenv("DATALAKE_STORAGE_ACCOUNT_NAME") or 
        os.getenv("DataLakeStorageAccountName")
    )
    BLOB_STORAGE_ACCOUNT_NAME = (
        os.getenv("BLOB_STORAGE_ACCOUNT_NAME") or 
        os.getenv("BlobStorageAccountName")
    )
    BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME", "data")
    BRONZE_CONTAINER_NAME = os.getenv("BRONZE_CONTAINER_NAME", "bronze")
    
    # Initialize Key Vault reader
    try:
        kv_reader = KeyVaultReader(key_vault_url=KEY_VAULT_URL)
    except Exception as e:
        logger.error(f"Failed to initialize Key Vault reader: {str(e)}")
        raise
    
    logger.info("=" * 60)
    logger.info("TRAINING DATA INGESTION ORCHESTRATOR (BATCH MODE)")
    logger.info("=" * 60)
    logger.info(f"Service Bus Topic: {SERVICEBUS_TOPIC_NAME}")
    logger.info(f"Service Bus Subscription: {SERVICEBUS_SUBSCRIPTION_NAME}")
    logger.info(f"Key Vault URL: {KEY_VAULT_URL}")
    
    # Get Service Bus connection string
    service_bus_conn_str = _get_env_or_kv("ServiceBusConnectionString", kv_reader, "ServiceBusConnectionString")
    if not service_bus_conn_str:
        logger.error("Failed to get Service Bus connection string")
        raise ValueError("ServiceBusConnectionString must be set")
    
    # Get storage account names from Key Vault if not in environment or if Key Vault reference
    DATALAKE_STORAGE_ACCOUNT_NAME = (
        _get_env_or_kv("DATALAKE_STORAGE_ACCOUNT_NAME", kv_reader, "DataLakeStorageAccountName") or
        _get_env_or_kv("DataLakeStorageAccountName", kv_reader, "DataLakeStorageAccountName")
    )
    
    BLOB_STORAGE_ACCOUNT_NAME = (
        _get_env_or_kv("BLOB_STORAGE_ACCOUNT_NAME", kv_reader, "BlobStorageAccountName") or
        _get_env_or_kv("BlobStorageAccountName", kv_reader, "BlobStorageAccountName")
    )
    
    if not BLOB_STORAGE_ACCOUNT_NAME:
        raise ValueError("BLOB_STORAGE_ACCOUNT_NAME or BlobStorageAccountName must be set")
    
    if not DATALAKE_STORAGE_ACCOUNT_NAME:
        raise ValueError(
            "DATALAKE_STORAGE_ACCOUNT_NAME or DataLakeStorageAccountName must be set (and must point to your Data Lake Gen2 account, "
            "e.g., blachedly27jgavel2x32)."
        )
    
    logger.info(f"Data Lake Storage Account: {DATALAKE_STORAGE_ACCOUNT_NAME}")
    logger.info(f"Blob Storage Account: {BLOB_STORAGE_ACCOUNT_NAME}")
    logger.info(f"Blob Container Name: {BLOB_CONTAINER_NAME}")
    
    # Get storage connection strings (fallback for auth issues)
    blob_connection_string = (
        _get_env_or_kv("BLOB_STORAGE_CONNECTION_STRING", kv_reader, "BlobStorageConnectionString") or
        _get_env_or_kv("BlobStorageConnectionString", kv_reader, "BlobStorageConnectionString")
    )
    
    if not blob_connection_string:
        try:
            for secret_name in ["StorageAccountConnectionString", "AzureWebJobsStorage"]:
                try:
                    blob_connection_string = kv_reader.get_secret(secret_name)
                    logger.info(f"Retrieved blob storage connection string from Key Vault: {secret_name}")
                    break
                except KeyVaultError:
                    continue
        except Exception as e:
            logger.debug(f"Could not retrieve blob connection string from Key Vault: {str(e)}")
    
    datalake_connection_string = (
        _get_env_or_kv("DATALAKE_STORAGE_CONNECTION_STRING", kv_reader, "StorageConnectionString") or
        _get_env_or_kv("StorageConnectionString", kv_reader, "StorageConnectionString")
    )
    
    if not datalake_connection_string:
        try:
            # Check for Data Lake connection string - try StorageConnectionString first (as per user's Key Vault)
            for secret_name in ["DataLakeStorageConnectionString", "DataLakeConnectionString"]:
                try:
                    datalake_connection_string = kv_reader.get_secret(secret_name)
                    logger.info(f"Retrieved data lake connection string from Key Vault: {secret_name}")
                    break
                except KeyVaultError:
                    continue
        except Exception as e:
            logger.debug(f"Could not retrieve data lake connection string from Key Vault: {str(e)}")
    
    # IMPORTANT: Do NOT fall back to blob connection string for data lake,
    # because your blob and data lake accounts are different.
    if not datalake_connection_string:
        raise ValueError(
            "DATALAKE_STORAGE_CONNECTION_STRING (env) or a Key Vault secret "
            "StorageConnectionString/DataLakeStorageConnectionString/DataLakeConnectionString must be set and must point to "
            "your Data Lake Gen2 account (e.g., blachedly27jgavel2x32)."
        )
    
    # Initialize clients
    credential = AzureCliCredential() if env == "local" else DefaultAzureCredential()
    
    # PostgreSQL client
    postgres_client = PostgresClient(
        key_vault_url=KEY_VAULT_URL,
        key_vault_reader=kv_reader
    )
    training_uploads_client = TrainingUploadsClient(postgres_client)
    bronze_log_client = BronzeIngestionLogClient(postgres_client)
    
    # Storage client
    storage_client = StorageClient(
        blob_storage_account_name=BLOB_STORAGE_ACCOUNT_NAME,
        datalake_storage_account_name=DATALAKE_STORAGE_ACCOUNT_NAME,
        blob_connection_string=blob_connection_string,
        datalake_connection_string=datalake_connection_string,
        credential=credential,
        env=env
    )
    
    # Checksum calculator
    checksum_calculator = ChecksumCalculator(
        credential=credential,
        blob_connection_string=blob_connection_string,
        datalake_connection_string=datalake_connection_string,
        datalake_storage_account_name=DATALAKE_STORAGE_ACCOUNT_NAME,
        env=env
    )
    
    # Service Bus writer
    service_bus_writer = ServiceBusWriter(
        connection_string=service_bus_conn_str,
        key_vault_url=KEY_VAULT_URL,
        key_vault_reader=kv_reader
    )
    
    # Service Bus reader (only used in batch mode)
    service_bus_reader = ServiceBusReader(
        connection_string=service_bus_conn_str,
        key_vault_url=KEY_VAULT_URL
    )
    
    logger.info("=" * 60)
    logger.info("PHASE 1: Peek all messages and extract training_upload_ids")
    logger.info("=" * 60)
    
    # Phase 1: Peek all messages
    try:
        peeked_messages = service_bus_reader.peek_all_messages(
            topic_name=SERVICEBUS_TOPIC_NAME,
            subscription_name=SERVICEBUS_SUBSCRIPTION_NAME,
            max_messages=1000
        )
        logger.info(f"Peeked {len(peeked_messages)} messages")
    except Exception as e:
        logger.error(f"Error peeking messages: {str(e)}", exc_info=True)
        raise
    
    # Extract training_upload_ids
    training_upload_ids = []
    for msg in peeked_messages:
        training_upload_id = msg.get("training_upload_id") or msg.get("upload_id")
        if training_upload_id:
            training_upload_ids.append(training_upload_id)
    
    logger.info(f"Extracted {len(training_upload_ids)} training_upload_ids from messages")
    
    if not training_upload_ids:
        logger.info("No messages with training_upload_id found. Exiting.")
        return
    
    # Phase 2: Query database for matching IDs
    logger.info("=" * 60)
    logger.info("PHASE 2: Query database for matching IDs with status='ingesting'")
    logger.info("=" * 60)
    
    try:
        matching_ids = training_uploads_client.find_matching_ids(training_upload_ids)
        logger.info(f"Found {len(matching_ids)} matching IDs in database")
    except Exception as e:
        logger.error(f"Error querying database: {str(e)}", exc_info=True)
        raise
    
    if not matching_ids:
        logger.info("No matching IDs found in database. Exiting.")
        return
    
    # Phase 3: Process matching messages
    logger.info("=" * 60)
    logger.info("PHASE 3: Process matching messages sequentially")
    logger.info("=" * 60)
    
    # Create Service Bus client and receiver
    sb_client = ServiceBusClient.from_connection_string(service_bus_conn_str)
    receiver = sb_client.get_subscription_receiver(
        topic_name=SERVICEBUS_TOPIC_NAME,
        subscription_name=SERVICEBUS_SUBSCRIPTION_NAME,
        max_lock_duration=120  # 2 minutes
    )
    
    processed_count = 0
    success_count = 0
    failed_count = 0
    dead_lettered_count = 0
    
    try:
        with receiver:
            auto_lock_renewer = AutoLockRenewer(max_lock_renewal_duration=600)  # 10 minutes
            
            # Receive messages one by one and process if matching
            while True:
                message, receiver_obj = service_bus_reader.receive_next_message(
                    topic_name=SERVICEBUS_TOPIC_NAME,
                    subscription_name=SERVICEBUS_SUBSCRIPTION_NAME,
                    max_wait_time=30
                )
                
                if not message:
                    logger.info("No more messages to receive. Exiting receive loop.")
                    break
                
                processed_count += 1
                
                try:
                    # Parse message
                    message_data = parse_message_body(message)
                    training_upload_id = message_data.get("training_upload_id") or message_data.get("upload_id")
                    
                    if not training_upload_id:
                        logger.warning(f"Message {message.message_id} missing training_upload_id. Dead-lettering.")
                        receiver.dead_letter_message(
                            message,
                            reason="Message missing required field 'training_upload_id'"
                        )
                        dead_lettered_count += 1
                        continue
                    
                    # Check if this ID matches our database query
                    if training_upload_id not in matching_ids:
                        logger.info(f"training_upload_id={training_upload_id} not in matching set. Dead-lettering.")
                        receiver.dead_letter_message(
                            message,
                            reason=f"No matching training_uploads record with status='ingesting' for training_upload_id={training_upload_id}"
                        )
                        dead_lettered_count += 1
                        continue
                    
                    # Lookup full metadata
                    metadata = training_uploads_client.lookup_metadata(training_upload_id)
                    if not metadata:
                        logger.warning(f"Metadata not found for {training_upload_id}. Dead-lettering.")
                        receiver.dead_letter_message(
                            message,
                            reason=f"Metadata lookup failed for training_upload_id={training_upload_id}"
                        )
                        dead_lettered_count += 1
                        continue
                    
                    # Register for auto lock renewal
                    auto_lock_renewer.register(receiver, message)
                    
                    # Generate run_id for this processing
                    run_id = str(uuid.uuid4())
                    
                    # Process the message
                    success = process_single_message(
                        training_upload_id=training_upload_id,
                        message_data=message_data,
                        metadata=metadata,
                        run_id=run_id,
                        storage_client=storage_client,
                        checksum_calculator=checksum_calculator,
                        training_uploads_client=training_uploads_client,
                        bronze_log_client=bronze_log_client,
                        service_bus_writer=service_bus_writer,
                        blob_storage_account_name=BLOB_STORAGE_ACCOUNT_NAME,
                        datalake_storage_account_name=DATALAKE_STORAGE_ACCOUNT_NAME,
                        blob_container_name=BLOB_CONTAINER_NAME,
                        bronze_container_name=BRONZE_CONTAINER_NAME
                    )
                    
                    if success:
                        receiver.complete_message(message)
                        success_count += 1
                        logger.info(f"✅ Message {processed_count} processed successfully")
                    else:
                        receiver.abandon_message(message)
                        failed_count += 1
                        logger.warning(f"⚠️  Message {processed_count} processing failed (abandoned for retry)")
                
                except Exception as e:
                    # Unexpected exception - log and skip (complete message, don't touch DB)
                    logger.error(f"Unexpected error processing message {processed_count}: {str(e)}", exc_info=True)
                    receiver.complete_message(message)  # Complete to skip
                    failed_count += 1
    
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        raise
    finally:
        try:
            receiver.close()
            sb_client.close()
            service_bus_reader.close()
        except Exception:
            pass
    
    # Summary
    logger.info("=" * 60)
    logger.info("BATCH PROCESSING COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total messages processed: {processed_count}")
    logger.info(f"Successfully ingested: {success_count}")
    logger.info(f"Failed (abandoned for retry): {failed_count}")
    logger.info(f"Dead-lettered (non-matching): {dead_lettered_count}")
    logger.info("=" * 60)


def run_single_message_from_function(message_data: Dict[str, Any]) -> None:
    """
    Entry point for the Azure Function (Service Bus trigger) - per-message flow.
    
    This function:
    - Does NOT peek or receive from Service Bus (the trigger already did that).
    - Looks up training_uploads by id with status='ingesting'.
    - If no matching row is found, logs and returns (message is completed).
    - If found, runs the same ingestion pipeline as batch mode for this one id.
    
    All errors are logged; no exceptions are propagated so the Function runtime
    treats the message as successfully handled (Log + Complete semantics).
    """
    # Load environment variables (same as batch mode)
    if HAS_DOTENV:
        env_path = os.path.join(TRAINING_INGESTION_ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)

    env = get_environment()
    logger.info(f"[single-message] Environment: {env}")

    KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
    if not KEY_VAULT_URL:
        logger.error("[single-message] KEY_VAULT_URL environment variable is required")
        return False

    SERVICEBUS_TOPIC_NAME = os.getenv("SERVICEBUS_TOPIC_NAME", "data-awaits-ingestion")
    SERVICEBUS_SUBSCRIPTION_NAME = os.getenv("SERVICEBUS_SUBSCRIPTION_NAME", "temp-peek-subscription")

    # Check for storage account names in multiple formats (local vs Azure naming)
    DATALAKE_STORAGE_ACCOUNT_NAME = (
        os.getenv("DATALAKE_STORAGE_ACCOUNT_NAME") or 
        os.getenv("DataLakeStorageAccountName")
    )
    BLOB_STORAGE_ACCOUNT_NAME = (
        os.getenv("BLOB_STORAGE_ACCOUNT_NAME") or 
        os.getenv("BlobStorageAccountName")
    )
    BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME", "data")
    BRONZE_CONTAINER_NAME = os.getenv("BRONZE_CONTAINER_NAME", "bronze")

    try:
        kv_reader = KeyVaultReader(key_vault_url=KEY_VAULT_URL)
    except Exception as e:
        logger.error(f"[single-message] Failed to initialize Key Vault reader: {str(e)}", exc_info=True)
        return

    # Service Bus connection string
    service_bus_conn_str = _get_env_or_kv("ServiceBusConnectionString", kv_reader, "ServiceBusConnectionString")
    if not service_bus_conn_str:
        logger.error("[single-message] Failed to get Service Bus connection string")
        return

    # Storage account names from Key Vault if not in environment or if Key Vault reference
    DATALAKE_STORAGE_ACCOUNT_NAME = (
        _get_env_or_kv("DATALAKE_STORAGE_ACCOUNT_NAME", kv_reader, "DataLakeStorageAccountName") or
        _get_env_or_kv("DataLakeStorageAccountName", kv_reader, "DataLakeStorageAccountName")
    )
    
    BLOB_STORAGE_ACCOUNT_NAME = (
        _get_env_or_kv("BLOB_STORAGE_ACCOUNT_NAME", kv_reader, "BlobStorageAccountName") or
        _get_env_or_kv("BlobStorageAccountName", kv_reader, "BlobStorageAccountName")
    )

    if not BLOB_STORAGE_ACCOUNT_NAME:
        logger.error("[single-message] BLOB_STORAGE_ACCOUNT_NAME or BlobStorageAccountName must be set")
        return

    if not DATALAKE_STORAGE_ACCOUNT_NAME:
        logger.error(
            "[single-message] DATALAKE_STORAGE_ACCOUNT_NAME or DataLakeStorageAccountName must be set (and must point to your Data Lake Gen2 account)."
        )
        return

    # Storage connection strings (mirror batch logic)
    blob_connection_string = (
        _get_env_or_kv("BLOB_STORAGE_CONNECTION_STRING", kv_reader, "BlobStorageConnectionString") or
        _get_env_or_kv("BlobStorageConnectionString", kv_reader, "BlobStorageConnectionString")
    )

    if not blob_connection_string:
        try:
            for secret_name in ["StorageAccountConnectionString", "AzureWebJobsStorage"]:
                try:
                    blob_connection_string = kv_reader.get_secret(secret_name)
                    logger.info(f"[single-message] Retrieved blob storage connection string from Key Vault: {secret_name}")
                    break
                except KeyVaultError:
                    continue
        except Exception as e:
            logger.debug(f"[single-message] Could not retrieve blob connection string from Key Vault: {str(e)}")

    datalake_connection_string = (
        _get_env_or_kv("DATALAKE_STORAGE_CONNECTION_STRING", kv_reader, "StorageConnectionString") or
        _get_env_or_kv("StorageConnectionString", kv_reader, "StorageConnectionString")
    )
    
    if not datalake_connection_string:
        try:
            for secret_name in ["DataLakeStorageConnectionString", "DataLakeConnectionString"]:
                try:
                    datalake_connection_string = kv_reader.get_secret(secret_name)
                    logger.info(f"[single-message] Retrieved data lake connection string from Key Vault: {secret_name}")
                    break
                except KeyVaultError:
                    continue
        except Exception as e:
            logger.debug(f"[single-message] Could not retrieve data lake connection string from Key Vault: {str(e)}")

    if not datalake_connection_string:
        logger.error(
            "[single-message] DATALAKE_STORAGE_CONNECTION_STRING (env) or a Key Vault secret "
            "'StorageConnectionString'/'DataLakeStorageConnectionString'/'DataLakeConnectionString' must be set "
            "and must point to your Data Lake Gen2 account."
        )
        return

    # Initialize clients (mirror batch mode)
    credential = AzureCliCredential() if env == "local" else DefaultAzureCredential()

    postgres_client = PostgresClient(
        key_vault_url=KEY_VAULT_URL,
        key_vault_reader=kv_reader
    )
    training_uploads_client = TrainingUploadsClient(postgres_client)
    bronze_log_client = BronzeIngestionLogClient(postgres_client)

    storage_client = StorageClient(
        blob_storage_account_name=BLOB_STORAGE_ACCOUNT_NAME,
        datalake_storage_account_name=DATALAKE_STORAGE_ACCOUNT_NAME,
        blob_connection_string=blob_connection_string,
        datalake_connection_string=datalake_connection_string,
        credential=credential,
        env=env
    )

    checksum_calculator = ChecksumCalculator(
        credential=credential,
        blob_connection_string=blob_connection_string,
        datalake_connection_string=datalake_connection_string,
        datalake_storage_account_name=DATALAKE_STORAGE_ACCOUNT_NAME,
        env=env
    )

    service_bus_writer = ServiceBusWriter(
        connection_string=service_bus_conn_str,
        key_vault_url=KEY_VAULT_URL,
        key_vault_reader=kv_reader
    )

    # Extract training_upload_id from message
    training_upload_id = message_data.get("training_upload_id") or message_data.get("upload_id")
    logger.info(f"[single-message] Message data keys: {list(message_data.keys())}")
    logger.info(f"[single-message] Extracted training_upload_id: {training_upload_id}")
    
    if not training_upload_id:
        logger.warning("[single-message] Message missing 'training_upload_id'/'upload_id'. Skipping.")
        return False

    # Check if this ID has a matching row with status='ingesting'
    try:
        logger.info(f"[single-message] Querying database for training_upload_id={training_upload_id} with status='ingesting'")
        matching_ids = training_uploads_client.find_matching_ids([training_upload_id])
        logger.info(f"[single-message] Found {len(matching_ids)} matching IDs: {matching_ids}")
    except Exception as e:
        logger.error(
            f"[single-message] Error querying database for training_upload_id={training_upload_id}: {str(e)}",
            exc_info=True,
        )
        return False

    if training_upload_id not in matching_ids:
        logger.warning(
            f"[single-message] ❌ No training_uploads row with id={training_upload_id} and status='ingesting'. "
            f"Matching IDs found: {matching_ids}. "
            "Skipping without touching database. "
            "Please check: 1) Does the record exist? 2) Is status='ingesting'?"
        )
        return False

    # Lookup full metadata
    try:
        metadata = training_uploads_client.lookup_metadata(training_upload_id)
    except Exception as e:
        logger.error(
            f"[single-message] Metadata lookup failed for training_upload_id={training_upload_id}: {str(e)}",
            exc_info=True,
        )
        return False

    if not metadata:
        logger.warning(
            f"[single-message] Metadata not found for training_upload_id={training_upload_id}. Skipping."
        )
        return False

    # Generate run_id for this processing
    run_id = str(uuid.uuid4())

    logger.info(
        f"[single-message] Starting ingestion for training_upload_id={training_upload_id}, run_id={run_id}"
    )

    try:
        success = process_single_message(
            training_upload_id=training_upload_id,
            message_data=message_data,
            metadata=metadata,
            run_id=run_id,
            storage_client=storage_client,
            checksum_calculator=checksum_calculator,
            training_uploads_client=training_uploads_client,
            bronze_log_client=bronze_log_client,
            service_bus_writer=service_bus_writer,
            blob_storage_account_name=BLOB_STORAGE_ACCOUNT_NAME,
            datalake_storage_account_name=DATALAKE_STORAGE_ACCOUNT_NAME,
            blob_container_name=BLOB_CONTAINER_NAME,
            bronze_container_name=BRONZE_CONTAINER_NAME
        )

        if success:
            logger.info(
                f"[single-message] ✅ Ingestion completed successfully for training_upload_id={training_upload_id}, "
                f"run_id={run_id}"
            )
            return True
        else:
            logger.warning(
                f"[single-message] ⚠️ Ingestion reported failure for training_upload_id={training_upload_id}, "
                f"run_id={run_id}. See logs above for details."
            )
            return False
    except Exception as e:
        # Unexpected exception – log and return without raising (Log + Complete semantics)
        logger.error(
            f"[single-message] Unexpected error during ingestion for training_upload_id={training_upload_id}: {str(e)}",
            exc_info=True,
        )
        return False
    finally:
        # Ensure database connections are closed before function completes
        try:
            if 'postgres_client' in locals():
                postgres_client.close()
        except Exception:
            pass
        try:
            if 'kv_reader' in locals():
                kv_reader.close()
        except Exception:
            pass


if __name__ == "__main__":
    # Configure logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Suppress verbose Azure SDK logs (Service Bus internal connection/link state changes)
    # These are too verbose for production logs
    azure_loggers = [
        'azure.servicebus._pyamqp',
        'azure.servicebus._servicebus_receiver',
        'azure.servicebus._servicebus_sender',
        'azure.core.pipeline.policies.http_logging_policy',
        'azure.identity',
        'urllib3.connectionpool'
    ]
    for logger_name in azure_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    # Create logger
    logger = logging.getLogger("run_training_ingestion")
    logger.info("Logging configured. Level=%s", log_level)
    
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}", exc_info=True)
        sys.exit(1)
