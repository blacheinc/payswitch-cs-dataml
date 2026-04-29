"""
Training Data Ingestion Processor
Core processing logic for ingesting training data files
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from azure.servicebus import ServiceBusMessage

# Import local utilities
import sys
import os
# Add parent directory to path for local imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from utils.checksum_calculator import ChecksumCalculator
from utils.storage_client import StorageClient
from utils.training_uploads_client import TrainingUploadsClient

# Import Service Bus Writer from schema-mapping-service
schema_mapping_root = os.path.join(os.path.dirname(parent_dir), 'schema-mapping-service')
if schema_mapping_root not in sys.path:
    sys.path.insert(0, schema_mapping_root)
from utils.service_bus_writer import ServiceBusWriter

logger = logging.getLogger(__name__)


class IngestionProcessor:
    """Processes training data ingestion from Service Bus message"""
    
    def __init__(
        self,
        storage_client: StorageClient,
        training_uploads_client: TrainingUploadsClient,
        checksum_calculator: ChecksumCalculator,
        service_bus_writer: ServiceBusWriter,
        blob_storage_account_name: str,
        datalake_storage_account_name: str,
        blob_container_name: str = "data"
    ):
        """
        Initialize Ingestion Processor
        
        Args:
            storage_client: Storage client for blob and data lake operations
            training_uploads_client: Client for training_uploads table
            checksum_calculator: Checksum calculator instance
            service_bus_writer: Service Bus writer for publishing messages
            blob_storage_account_name: Blob storage account name
            datalake_storage_account_name: Data Lake storage account name
        """
        self.storage_client = storage_client
        self.training_uploads_client = training_uploads_client
        self.checksum_calculator = checksum_calculator
        self.service_bus_writer = service_bus_writer
        self.blob_storage_account_name = blob_storage_account_name
        self.datalake_storage_account_name = datalake_storage_account_name
        self.blob_container_name = blob_container_name
    
    def process_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single ingestion message
        
        Args:
            message_data: Parsed Service Bus message data
            
        Returns:
            Dictionary with processing result
            
        Raises:
            Exception: If processing fails
        """
        # Generate run_id for this ingestion
        run_id = str(uuid.uuid4())
        logger.info(f"[run_id={run_id}] Starting ingestion processing")
        
        try:
            # Step 1: Parse and validate message format
            # Skip messages that are from downstream processing (have transformation/quality fields)
            downstream_fields = ["quality_report", "quality_score", "transformed_file_path", 
                                "features_mapped", "schema_template_id", "status"]
            if any(field in message_data for field in downstream_fields):
                # This is a downstream message, not an ingestion message - skip it
                logger.warning(
                    f"[run_id={run_id}] Skipping downstream message (has fields: {[f for f in downstream_fields if f in message_data]}). "
                    f"Expected ingestion message format with training_upload_id, data_source_id, file_format, etc."
                )
                raise ValueError("Message is from downstream processing, not ingestion. Skipping.")
            
            training_upload_id = message_data.get("training_upload_id") or message_data.get("upload_id")
            if not training_upload_id:
                raise ValueError("Missing required field: training_upload_id or upload_id")
            
            logger.info(f"[run_id={run_id}] Processing training_upload_id={training_upload_id}")
            
            # Step 2: Lookup metadata from PostgreSQL
            logger.info(f"[run_id={run_id}] Looking up metadata from training_uploads table...")
            metadata = self.training_uploads_client.lookup_metadata(training_upload_id)
            
            if not metadata:
                error_msg = f"No record found for training_upload_id={training_upload_id} with status='ingesting'"
                logger.error(f"[run_id={run_id}] {error_msg}")
                raise ValueError(error_msg)
            
            data_source_id = metadata.get("data_source_id")
            file_format = metadata.get("file_format")
            file_size_bytes = metadata.get("file_size_bytes")
            raw_file_path = metadata.get("raw_file_path")
            record_count = metadata.get("record_count")
            
            logger.info(f"[run_id={run_id}] Metadata retrieved: data_source_id={data_source_id}, file_format={file_format}")

            if not file_format:
                raise ValueError(
                    f"Missing file_format in training_uploads metadata for training_upload_id={training_upload_id}"
                )
            
            # Step 3: Calculate source file checksum
            logger.info(f"[run_id={run_id}] Calculating source file checksum...")
            source_blob_url = f"https://{self.blob_storage_account_name}.blob.core.windows.net/{self.blob_container_name}/{raw_file_path}"
            source_checksum = self.checksum_calculator.calculate_checksum(source_blob_url)
            logger.info(f"[run_id={run_id}] Source checksum: {source_checksum[:16]}...")
            
            # Step 4: Copy file to bronze layer (same key pattern as run_training_ingestion.process_single_message)
            logger.info(f"[run_id={run_id}] Copying file to bronze layer...")
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            file_name = metadata.get("file_name") or training_upload_id
            file_name = str(file_name).strip()
            if "." in file_name:
                file_name = file_name.rsplit(".", 1)[0]
            bronze_path = f"training/{data_source_id}/{date_str}/{file_name}.{file_format}"
            
            # Extract bank_id from raw_file_path (format: bank_id/filename)
            source_blob_path = raw_file_path  # e.g., "bank-digital-001/upload_id.csv"
            
            self.storage_client.copy_blob_to_datalake(
                source_container=self.blob_container_name,
                source_blob_path=source_blob_path,
                destination_filesystem="bronze",
                destination_path=bronze_path,
                overwrite=True
            )
            logger.info(f"[run_id={run_id}] File copied to bronze: {bronze_path}")
            
            # Step 5: Calculate bronze file checksum
            logger.info(f"[run_id={run_id}] Calculating bronze file checksum...")
            bronze_blob_url = f"https://{self.datalake_storage_account_name}.dfs.core.windows.net/bronze/{bronze_path}"
            bronze_checksum = self.checksum_calculator.calculate_checksum(bronze_blob_url)
            logger.info(f"[run_id={run_id}] Bronze checksum: {bronze_checksum[:16]}...")
            
            # Step 6: Get bronze file size
            logger.info(f"[run_id={run_id}] Getting bronze file size...")
            bronze_file_size = self.storage_client.get_file_size("bronze", bronze_path)
            logger.info(f"[run_id={run_id}] Bronze file size: {bronze_file_size} bytes")
            
            # Step 7: Verify integrity
            logger.info(f"[run_id={run_id}] Verifying file integrity...")
            if source_checksum != bronze_checksum:
                error_msg = f"Checksum mismatch. Source: {source_checksum[:16]}..., Bronze: {bronze_checksum[:16]}..."
                logger.error(f"[run_id={run_id}] {error_msg}")
                self._handle_verification_failure(
                    run_id=run_id,
                    training_upload_id=training_upload_id,
                    bronze_path=bronze_path,
                    error_message=error_msg,
                    expected_size=file_size_bytes,
                    actual_size=bronze_file_size
                )
                raise ValueError(error_msg)
            
            if file_size_bytes and bronze_file_size != file_size_bytes:
                error_msg = f"File size mismatch. Expected: {file_size_bytes} bytes, Actual: {bronze_file_size} bytes"
                logger.error(f"[run_id={run_id}] {error_msg}")
                self._handle_verification_failure(
                    run_id=run_id,
                    training_upload_id=training_upload_id,
                    bronze_path=bronze_path,
                    error_message=error_msg,
                    expected_size=file_size_bytes,
                    actual_size=bronze_file_size
                )
                raise ValueError(error_msg)
            
            logger.info(f"[run_id={run_id}] File integrity verified successfully")
            
            # Step 8: Update PostgreSQL metadata
            logger.info(f"[run_id={run_id}] Updating PostgreSQL metadata...")
            self.training_uploads_client.update_bronze_metadata(
                training_upload_id=training_upload_id,
                bronze_blob_path=bronze_path,
                bronze_file_size_bytes=bronze_file_size,
                bronze_checksum_sha256=bronze_checksum,
                bronze_row_count=record_count
            )
            logger.info(f"[run_id={run_id}] PostgreSQL metadata updated")
            
            # Step 9: Publish success message
            logger.info(f"[run_id={run_id}] Publishing success message to data-ingested topic...")
            self._publish_success_message(
                run_id=run_id,
                training_upload_id=training_upload_id,
                data_source_id=data_source_id,
                bronze_path=bronze_path,
                raw_file_path=raw_file_path,
                file_format=file_format,
                record_count=record_count,
                column_count=None  # Not available in training_uploads table
            )
            logger.info(f"[run_id={run_id}] Success message published")
            
            logger.info(f"[run_id={run_id}] Ingestion processing completed successfully")
            
            return {
                "run_id": run_id,
                "status": "success",
                "training_upload_id": training_upload_id,
                "bronze_path": bronze_path
            }
            
        except Exception as e:
            logger.error(f"[run_id={run_id}] Processing failed: {str(e)}", exc_info=True)
            # Publish failure message if we have training_upload_id
            if 'training_upload_id' in locals():
                try:
                    self._publish_failure_message(
                        run_id=run_id,
                        training_upload_id=training_upload_id,
                        error_message=str(e)
                    )
                except Exception as pub_error:
                    logger.error(f"[run_id={run_id}] Failed to publish failure message: {str(pub_error)}")
            raise
    
    def _handle_verification_failure(
        self,
        run_id: str,
        training_upload_id: str,
        bronze_path: str,
        error_message: str,
        expected_size: Optional[int],
        actual_size: Optional[int]
    ) -> None:
        """Handle verification failure - update metadata and publish failure message"""
        try:
            # Update PostgreSQL
            self.training_uploads_client.update_verification_failed(
                training_upload_id=training_upload_id,
                error_message=error_message,
                expected_size=expected_size,
                actual_size=actual_size
            )
            
            # Publish failure message
            self._publish_failure_message(
                run_id=run_id,
                training_upload_id=training_upload_id,
                error_message=error_message
            )
        except Exception as e:
            logger.error(f"[run_id={run_id}] Error handling verification failure: {str(e)}", exc_info=True)
    
    def _publish_success_message(
        self,
        run_id: str,
        training_upload_id: str,
        data_source_id: str,
        bronze_path: str,
        raw_file_path: str,
        file_format: str,
        record_count: Optional[int],
        column_count: Optional[int]
    ) -> None:
        """Publish success message to data-ingested topic"""
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "bank_id": data_source_id,  # data_source_id is the bank_id
            "bronze_blob_path": bronze_path,
            "source_blob_path": raw_file_path,
            "file_format": file_format,
            "row_count": record_count,
            "column_count": column_count,
            "ingestion_timestamp": datetime.utcnow().isoformat(),
            "status": "bronze_ingested"
        }
        
        # Use ServiceBusWriter to publish (it handles custom properties)
        self.service_bus_writer._publish_to_subscription(
            topic_name=ServiceBusWriter.TOPIC_BACKEND,
            subscription_name="start-transformation",
            message_data=message_data,
            run_id=run_id
        )
    
    def _publish_failure_message(
        self,
        run_id: str,
        training_upload_id: str,
        error_message: str
    ) -> None:
        """Publish failure message to data-ingested topic error subscription"""
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "status": "ERROR",
            "error_message": error_message,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.service_bus_writer._publish_to_subscription(
            topic_name=ServiceBusWriter.TOPIC_BACKEND,
            subscription_name=ServiceBusWriter.SUBSCRIPTION_ERROR,
            message_data=message_data,
            run_id=run_id
        )
