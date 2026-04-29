"""
PostgreSQL Client for Training Uploads Table
Handles database operations for training_uploads table
"""

import logging
import sys
import os
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy import text

# Import TrainingPostgresClient (self-contained, no dependency on schema-mapping-service)
from .training_postgres_client import TrainingPostgresClient

# Alias for backward compatibility
PostgresClient = TrainingPostgresClient

# Import enums from run_training_ingestion (lazy import to avoid circular dependency)
# We'll import them when needed in methods to avoid import-time issues
logger = logging.getLogger(__name__)


def _get_training_upload_status_enum():
    """Lazy import of TrainingUploadStatus enum to avoid circular imports"""
    try:
        # Add parent directory to path if needed
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        from scripts.run_training_ingestion import TrainingUploadStatus
        return TrainingUploadStatus
    except ImportError:
        # Fallback: return a mock enum-like object if import fails
        class MockEnum:
            INGESTING = "ingesting"
            INGESTED = "ingested"
            ERROR = "error"
        return MockEnum


class TrainingUploadsClient:
    """Client for training_uploads table operations"""
    
    def __init__(self, postgres_client: PostgresClient):
        """
        Initialize Training Uploads Client
        
        Args:
            postgres_client: PostgresClient instance
        """
        self.postgres_client = postgres_client
        logger.info("Training Uploads Client initialized")
    
    def find_matching_ids(self, training_upload_ids: list[str]) -> set[str]:
        """
        Find which training_upload_ids exist in the database with status='ingesting'
        
        Args:
            training_upload_ids: List of training upload IDs to check
            
        Returns:
            Set of matching IDs that exist with status='ingesting'
        """
        if not training_upload_ids:
            return set()
        
        # Compare using id::text so we can pass a text[] parameter list
        # This avoids UUID vs text operator issues in PostgreSQL
        query = """
            SELECT id
            FROM training_uploads
            WHERE id::text = ANY(:training_upload_ids)
            AND status = :status
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                result = session.execute(
                    text(query),
                    {"training_upload_ids": training_upload_ids, "status": TrainingUploadStatus.INGESTING.value}
                )
                matching_ids = {str(row[0]) for row in result.fetchall()}
                logger.info(f"Found {len(matching_ids)} matching IDs out of {len(training_upload_ids)} checked")
                return matching_ids
                
        except Exception as e:
            logger.error(f"Error finding matching IDs: {str(e)}", exc_info=True)
            raise
    
    def lookup_metadata(self, training_upload_id: str) -> Optional[Dict[str, Any]]:
        """
        Lookup training upload metadata from training_uploads table
        
        Args:
            training_upload_id: Training upload ID (UUID)
            
        Returns:
            Dictionary with metadata or None if not found
        """
        query = """
            SELECT 
                id,
                data_source_id,
                status,
                file_name,
                file_format,
                file_size_bytes,
                raw_file_path,
                file_metadata,
                record_count
            FROM training_uploads
            WHERE id = :training_upload_id
            AND status = :status
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                result = session.execute(
                    text(query),
                    {"training_upload_id": training_upload_id, "status": TrainingUploadStatus.INGESTING.value}
                )
                row = result.fetchone()
                
                if not row:
                    logger.warning(f"No record found for training_upload_id={training_upload_id} with status='ingesting'")
                    return None
                
                # Convert row to dictionary
                columns = result.keys()
                metadata = dict(zip(columns, row))
                
                logger.info(f"Found metadata for training_upload_id={training_upload_id}: data_source_id={metadata.get('data_source_id')}")
                return metadata
                
        except Exception as e:
            logger.error(f"Error looking up metadata: {str(e)}", exc_info=True)
            raise
    
    def update_bronze_metadata(
        self,
        training_upload_id: str,
        bronze_blob_path: str,
        bronze_file_size_bytes: int,
        bronze_checksum_sha256: str,
        bronze_row_count: Optional[int] = None
    ) -> None:
        """
        Update training_uploads table with bronze layer information
        
        Args:
            training_upload_id: Training upload ID
            bronze_blob_path: Path to file in bronze layer
            bronze_file_size_bytes: File size in bytes
            bronze_checksum_sha256: SHA-256 checksum
            bronze_row_count: Row count (optional, from record_count)
        """
        query = """
            UPDATE training_uploads
            SET 
                bronze_blob_path = :bronze_blob_path,
                bronze_row_count = :bronze_row_count,
                bronze_file_size_bytes = :bronze_file_size_bytes,
                bronze_checksum_sha256 = :bronze_checksum_sha256,
                bronze_status = 'verified',
                bronze_verified_at = CURRENT_TIMESTAMP,
                status = :status,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :training_upload_id
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                session.execute(
                    text(query),
                    {
                        "training_upload_id": training_upload_id,
                        "bronze_blob_path": bronze_blob_path,
                        "bronze_row_count": bronze_row_count,
                        "bronze_file_size_bytes": bronze_file_size_bytes,
                        "bronze_checksum_sha256": bronze_checksum_sha256,
                        "status": TrainingUploadStatus.INGESTED.value
                    }
                )
                session.commit()
                logger.info(f"Updated bronze metadata for training_upload_id={training_upload_id}")
                
        except Exception as e:
            logger.error(f"Error updating bronze metadata: {str(e)}", exc_info=True)
            raise
    
    def update_verification_failed(
        self,
        training_upload_id: str,
        error_message: str,
        expected_size: Optional[int] = None,
        actual_size: Optional[int] = None
    ) -> None:
        """
        Update training_uploads table when verification fails
        
        Args:
            training_upload_id: Training upload ID
            error_message: Error message
            expected_size: Expected file size (optional)
            actual_size: Actual file size (optional)
        """
        error_details = error_message
        if expected_size is not None and actual_size is not None:
            error_details = f"File size verification failed. Expected: {expected_size} bytes. Actual: {actual_size} bytes."
        
        query = """
            UPDATE training_uploads
            SET 
                bronze_status = 'verification_failed',
                status = :status,
                error_message = :error_message,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :training_upload_id
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                session.execute(
                    text(query),
                    {
                        "training_upload_id": training_upload_id,
                        "error_message": error_details,
                        "status": TrainingUploadStatus.ERROR.value
                    }
                )
                session.commit()
                logger.info(f"Updated verification failure for training_upload_id={training_upload_id}")
                
        except Exception as e:
            logger.error(f"Error updating verification failure: {str(e)}", exc_info=True)
            raise
    
    def update_status_ingested(self, training_upload_id: str) -> None:
        """
        Update training_uploads table status to 'ingested' after successful ingestion
        
        Args:
            training_upload_id: Training upload ID
        """
        query = """
            UPDATE training_uploads
            SET 
                status = :status,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :training_upload_id
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                session.execute(
                    text(query),
                    {"training_upload_id": training_upload_id, "status": TrainingUploadStatus.INGESTED.value}
                )
                session.commit()
                logger.info(f"Updated status to 'ingested' for training_upload_id={training_upload_id}")
                
        except Exception as e:
            logger.error(f"Error updating status to 'ingested': {str(e)}", exc_info=True)
            raise
    
    def update_status_file_not_found(
        self,
        training_upload_id: str,
        error_message: str
    ) -> None:
        """
        Update training_uploads table status to 'error' (file not found)
        
        Args:
            training_upload_id: Training upload ID
            error_message: Error message explaining why file was not found
        """
        query = """
            UPDATE training_uploads
            SET 
                status = :status,
                error_message = :error_message,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :training_upload_id
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                session.execute(
                    text(query),
                    {
                        "training_upload_id": training_upload_id,
                        "error_message": error_message,
                        "status": TrainingUploadStatus.ERROR.value
                    }
                )
                session.commit()
                logger.info(f"Updated status to 'error' (file not found) for training_upload_id={training_upload_id}")
                
        except Exception as e:
            logger.error(f"Error updating status to 'error' (file not found): {str(e)}", exc_info=True)
            raise
    
    def update_status_copy_failed(
        self,
        training_upload_id: str,
        error_message: str
    ) -> None:
        """
        Update training_uploads table status to 'error' (copy failed)
        
        Args:
            training_upload_id: Training upload ID
            error_message: Error message explaining why copy failed
        """
        query = """
            UPDATE training_uploads
            SET 
                status = :status,
                error_message = :error_message,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :training_upload_id
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                session.execute(
                    text(query),
                    {
                        "training_upload_id": training_upload_id,
                        "error_message": error_message,
                        "status": TrainingUploadStatus.ERROR.value
                    }
                )
                session.commit()
                logger.info(f"Updated status to 'error' (copy failed) for training_upload_id={training_upload_id}")
                
        except Exception as e:
            logger.error(f"Error updating status to 'error' (copy failed): {str(e)}", exc_info=True)
            raise
    
    def update_status_verification_failed(
        self,
        training_upload_id: str,
        error_message: str
    ) -> None:
        """
        Update training_uploads table status to 'error' (verification failed)
        
        Args:
            training_upload_id: Training upload ID
            error_message: Error message explaining why verification failed
        """
        query = """
            UPDATE training_uploads
            SET 
                status = :status,
                error_message = :error_message,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :training_upload_id
        """
        
        try:
            with self.postgres_client.get_session() as session:
                TrainingUploadStatus = _get_training_upload_status_enum()
                session.execute(
                    text(query),
                    {
                        "training_upload_id": training_upload_id,
                        "error_message": error_message,
                        "status": TrainingUploadStatus.ERROR.value
                    }
                )
                session.commit()
                logger.info(f"Updated status to 'error' (verification failed) for training_upload_id={training_upload_id}")
                
        except Exception as e:
            logger.error(f"Error updating status to 'error' (verification failed): {str(e)}", exc_info=True)
            raise
