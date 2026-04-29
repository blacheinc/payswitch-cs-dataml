"""
Pipeline State Tracker
Tracks pipeline run state and system completions in PostgreSQL
"""
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import contextmanager

try:
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

try:
    from schema_registry.postgres_client import PostgresClient
except ImportError:
    from ..schema_registry.postgres_client import PostgresClient

logger = logging.getLogger(__name__)


class PipelineStateTracker:
    """Tracks pipeline run state and system completions in PostgreSQL"""
    
    def __init__(
        self,
        postgres_client: Optional[PostgresClient] = None,
        key_vault_url: Optional[str] = None,
        key_vault_reader = None
    ):
        """
        Initialize Pipeline State Tracker
        
        Args:
            postgres_client: Optional PostgresClient instance
            key_vault_url: Key Vault URL (if postgres_client not provided)
            key_vault_reader: Optional KeyVaultReader instance
        """
        if not SQLALCHEMY_AVAILABLE:
            raise ImportError("SQLAlchemy not available. Install with: pip install sqlalchemy")
        
        if postgres_client:
            self.postgres_client = postgres_client
        else:
            self.postgres_client = PostgresClient(
                key_vault_url=key_vault_url,
                key_vault_reader=key_vault_reader
            )
    
    @contextmanager
    def _get_session(self):
        """Get database session context manager"""
        # get_session() already returns a Session instance, not a factory
        session = self.postgres_client.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def create_run(
        self,
        run_id: str,
        training_upload_id: str,
        bank_id: str,
        status: str = "running"
    ) -> bool:
        """
        Create a new pipeline run record
        
        Args:
            run_id: Run ID (UUID string)
            training_upload_id: Training upload ID
            bank_id: Bank ID
            status: Initial status (default: "running")
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_session() as session:
                session.execute(
                    text("""
                        INSERT INTO pipeline_runs (
                            run_id, training_upload_id, bank_id, status, current_system, started_at
                        ) VALUES (
                            :run_id, :training_upload_id, :bank_id, :status, :current_system, :started_at
                        )
                        ON CONFLICT (run_id) DO UPDATE SET
                            updated_at = CURRENT_TIMESTAMP
                    """),
                    {
                        "run_id": uuid.UUID(run_id),
                        "training_upload_id": uuid.UUID(training_upload_id),
                        "bank_id": bank_id,
                        "status": status,
                        "current_system": None,
                        "started_at": datetime.utcnow()
                    }
                )
                logger.info(f"Created pipeline run record: run_id={run_id}, training_upload_id={training_upload_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to create pipeline run record: {e}", exc_info=True)
            return False
    
    def update_run_status(
        self,
        run_id: str,
        status: str,
        current_system: Optional[str] = None,
        error_message: Optional[str] = None,
        error_system: Optional[str] = None,
        silver_path: Optional[str] = None
    ) -> bool:
        """
        Update pipeline run status
        
        Args:
            run_id: Run ID
            status: New status ("running", "completed", "failed", "cancelled")
            current_system: Current system name
            error_message: Error message (if failed)
            error_system: System that failed
            silver_path: Path to anonymized data in Silver
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_session() as session:
                update_fields = {
                    "run_id": uuid.UUID(run_id),
                    "status": status,
                    "updated_at": datetime.utcnow()
                }
                
                if current_system is not None:
                    update_fields["current_system"] = current_system
                
                if status == "completed":
                    update_fields["completed_at"] = datetime.utcnow()
                    # On successful completion, clear any previous error info
                    update_fields["error_message"] = None
                    update_fields["error_system"] = None
                
                if error_message is not None:
                    update_fields["error_message"] = error_message
                
                if error_system is not None:
                    update_fields["error_system"] = error_system
                
                if silver_path is not None:
                    update_fields["silver_path"] = silver_path
                
                # Build dynamic UPDATE query
                set_clauses = []
                params = {"run_id": uuid.UUID(run_id)}
                
                for key, value in update_fields.items():
                    if key != "run_id":
                        set_clauses.append(f"{key} = :{key}")
                        params[key] = value
                
                if set_clauses:
                    query = f"""
                        UPDATE pipeline_runs
                        SET {', '.join(set_clauses)}
                        WHERE run_id = :run_id
                    """
                    session.execute(text(query), params)
                    logger.debug(f"Updated pipeline run status: run_id={run_id}, status={status}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to update pipeline run status: {e}", exc_info=True)
            return False
    
    def start_system(
        self,
        run_id: str,
        training_upload_id: str,
        system_name: str,
        message_id: Optional[str] = None,
        subscription_name: Optional[str] = None
    ) -> bool:
        """
        Record system start
        
        Args:
            run_id: Run ID
            training_upload_id: Training upload ID
            system_name: System name ("introspection", "schema", "sampling", "analysis", "anonymization")
            message_id: Service Bus message ID
            subscription_name: Subscription name
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_session() as session:
                session.execute(
                    text("""
                        INSERT INTO system_completions (
                            run_id, training_upload_id, system_name, status, started_at,
                            message_id, subscription_name
                        ) VALUES (
                            :run_id, :training_upload_id, :system_name, :status, :started_at,
                            :message_id, :subscription_name
                        )
                        ON CONFLICT (run_id, system_name) DO UPDATE SET
                            status = :status,
                            started_at = :started_at,
                            message_id = :message_id,
                            subscription_name = :subscription_name,
                            completed_at = NULL,
                            error_message = NULL
                    """),
                    {
                        "run_id": uuid.UUID(run_id),
                        "training_upload_id": uuid.UUID(training_upload_id),
                        "system_name": system_name,
                        "status": "in_progress",
                        "started_at": datetime.utcnow(),
                        "message_id": message_id,
                        "subscription_name": subscription_name
                    }
                )
                logger.debug(f"Recorded system start: run_id={run_id}, system={system_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to record system start: {e}", exc_info=True)
            return False
    
    def complete_system(
        self,
        run_id: str,
        system_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record system completion
        
        Args:
            run_id: Run ID
            system_name: System name
            metadata: Optional system-specific metadata (stored as JSONB)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            import json
            with self._get_session() as session:
                session.execute(
                    text("""
                        UPDATE system_completions
                        SET status = :status,
                            completed_at = :completed_at,
                            metadata = :metadata
                        WHERE run_id = :run_id AND system_name = :system_name
                    """),
                    {
                        "run_id": uuid.UUID(run_id),
                        "system_name": system_name,
                        "status": "completed",
                        "completed_at": datetime.utcnow(),
                        "metadata": json.dumps(metadata) if metadata else None
                    }
                )
                logger.debug(f"Recorded system completion: run_id={run_id}, system={system_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to record system completion: {e}", exc_info=True)
            return False
    
    def fail_system(
        self,
        run_id: str,
        system_name: str,
        error_message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Record system failure
        
        Args:
            run_id: Run ID
            system_name: System name
            error_message: Error message
            metadata: Optional error metadata
        
        Returns:
            True if successful, False otherwise
        """
        try:
            import json
            with self._get_session() as session:
                session.execute(
                    text("""
                        UPDATE system_completions
                        SET status = :status,
                            completed_at = :completed_at,
                            error_message = :error_message,
                            metadata = :metadata
                        WHERE run_id = :run_id AND system_name = :system_name
                    """),
                    {
                        "run_id": uuid.UUID(run_id),
                        "system_name": system_name,
                        "status": "failed",
                        "completed_at": datetime.utcnow(),
                        "error_message": error_message,
                        "metadata": json.dumps(metadata) if metadata else None
                    }
                )
                logger.debug(f"Recorded system failure: run_id={run_id}, system={system_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to record system failure: {e}", exc_info=True)
            return False
    
    def check_deduplication(
        self,
        run_id: str,
        system_name: str,
        message_id: str,
        subscription_name: str
    ) -> bool:
        """
        Check if message was already processed (deduplication)
        
        Args:
            run_id: Run ID
            system_name: System name
            message_id: Service Bus message ID
            subscription_name: Subscription name
        
        Returns:
            True if already processed, False if new
        """
        try:
            with self._get_session() as session:
                result = session.execute(
                    text("""
                        SELECT COUNT(*) as count
                        FROM message_deduplication
                        WHERE run_id = :run_id
                          AND system_name = :system_name
                          AND message_id = :message_id
                    """),
                    {
                        "run_id": uuid.UUID(run_id),
                        "system_name": system_name,
                        "message_id": message_id
                    }
                ).fetchone()
                
                if result and result[0] > 0:
                    logger.info(
                        f"Message already processed (deduplication): "
                        f"run_id={run_id}, system={system_name}, message_id={message_id}"
                    )
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to check deduplication: {e}", exc_info=True)
            # On error, assume not processed (fail open)
            return False
    
    def record_message_processed(
        self,
        run_id: str,
        training_upload_id: str,
        system_name: str,
        message_id: str,
        subscription_name: str
    ) -> bool:
        """
        Record that a message was processed (for deduplication)
        
        Args:
            run_id: Run ID
            training_upload_id: Training upload ID
            system_name: System name
            message_id: Service Bus message ID
            subscription_name: Subscription name
        
        Returns:
            True if successful, False otherwise
        """
        try:
            with self._get_session() as session:
                session.execute(
                    text("""
                        INSERT INTO message_deduplication (
                            run_id, training_upload_id, system_name, message_id, subscription_name, processed_at
                        ) VALUES (
                            :run_id, :training_upload_id, :system_name, :message_id, :subscription_name, :processed_at
                        )
                        ON CONFLICT (run_id, system_name, message_id) DO NOTHING
                    """),
                    {
                        "run_id": uuid.UUID(run_id),
                        "training_upload_id": uuid.UUID(training_upload_id),
                        "system_name": system_name,
                        "message_id": message_id,
                        "subscription_name": subscription_name,
                        "processed_at": datetime.utcnow()
                    }
                )
                logger.debug(f"Recorded message processed: run_id={run_id}, system={system_name}, message_id={message_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to record message processed: {e}", exc_info=True)
            return False
    
    def check_system_already_completed(
        self,
        run_id: str,
        system_name: str
    ) -> bool:
        """
        Check if a system was already completed for this run
        
        Args:
            run_id: Run ID
            system_name: System name
        
        Returns:
            True if already completed, False otherwise
        """
        try:
            with self._get_session() as session:
                result = session.execute(
                    text("""
                        SELECT status
                        FROM system_completions
                        WHERE run_id = :run_id AND system_name = :system_name
                    """),
                    {
                        "run_id": uuid.UUID(run_id),
                        "system_name": system_name
                    }
                ).fetchone()
                
                if result and result[0] == "completed":
                    logger.info(f"System already completed: run_id={run_id}, system={system_name}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to check system completion status: {e}", exc_info=True)
            # On error, assume not completed (fail open)
            return False
