"""
PostgreSQL Client for Bronze Ingestion Log Table
Handles database operations for bronze_ingestion_log table
"""

import logging
from typing import Optional
from sqlalchemy import text

# Import TrainingPostgresClient (self-contained, no dependency on schema-mapping-service)
from .training_postgres_client import TrainingPostgresClient

# Alias for backward compatibility
PostgresClient = TrainingPostgresClient

logger = logging.getLogger(__name__)


class BronzeIngestionLogClient:
    """Client for bronze_ingestion_log table operations"""
    
    def __init__(self, postgres_client: PostgresClient):
        """
        Initialize Bronze Ingestion Log Client
        
        Args:
            postgres_client: PostgresClient instance
        """
        self.postgres_client = postgres_client
        logger.info("Bronze Ingestion Log Client initialized")
    
    def insert_log(
        self,
        training_upload_id: str,
        run_id: str,
        source_blob_path: str,
        source_checksum_sha256: str,
        source_file_size_bytes: int,
        bronze_blob_path: str,
        bronze_checksum_sha256: str,
        bronze_file_size_bytes: int,
        ingestion_status: str,
        error_message: Optional[str] = None
    ) -> None:
        """
        Insert a record into bronze_ingestion_log table
        
        Args:
            training_upload_id: Training upload ID (UUID)
            run_id: Run ID (UUID)
            source_blob_path: Path to source file in data container
            source_checksum_sha256: SHA-256 checksum of source file
            source_file_size_bytes: Size of source file in bytes
            bronze_blob_path: Path to file in bronze container
            bronze_checksum_sha256: SHA-256 checksum of bronze file
            bronze_file_size_bytes: Size of bronze file in bytes
            ingestion_status: Status ('success', 'file_not_found', 'copy_failed', 'verification_failed')
            error_message: Error message (if any)
        """
        query = """
            INSERT INTO bronze_ingestion_log (
                training_upload_id,
                run_id,
                source_blob_path,
                source_checksum_sha256,
                source_file_size_bytes,
                bronze_blob_path,
                bronze_checksum_sha256,
                bronze_file_size_bytes,
                ingestion_status,
                error_message,
                ingested_at
            )
            VALUES (
                :training_upload_id,
                :run_id,
                :source_blob_path,
                :source_checksum_sha256,
                :source_file_size_bytes,
                :bronze_blob_path,
                :bronze_checksum_sha256,
                :bronze_file_size_bytes,
                :ingestion_status,
                :error_message,
                CURRENT_TIMESTAMP
            )
        """
        
        try:
            with self.postgres_client.get_session() as session:
                session.execute(
                    text(query),
                    {
                        "training_upload_id": training_upload_id,
                        "run_id": run_id,
                        "source_blob_path": source_blob_path,
                        "source_checksum_sha256": source_checksum_sha256,
                        "source_file_size_bytes": source_file_size_bytes,
                        "bronze_blob_path": bronze_blob_path,
                        "bronze_checksum_sha256": bronze_checksum_sha256,
                        "bronze_file_size_bytes": bronze_file_size_bytes,
                        "ingestion_status": ingestion_status,
                        "error_message": error_message
                    }
                )
                session.commit()
                logger.info(f"Inserted bronze ingestion log for training_upload_id={training_upload_id}, run_id={run_id}, status={ingestion_status}")
                
        except Exception as e:
            logger.error(f"Error inserting bronze ingestion log: {str(e)}", exc_info=True)
            raise
