"""
Service Bus Writer
Unified Service Bus writer for both backend (data-ingested) and internal (schema-mapping-service) topics
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime
from enum import Enum

if TYPE_CHECKING:
    from azure.servicebus import ServiceBusClient, ServiceBusMessage

try:
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    from azure.core.exceptions import AzureError
    SERVICE_BUS_AVAILABLE = True
except ImportError:
    SERVICE_BUS_AVAILABLE = False
    ServiceBusClient = None  # type: ignore
    ServiceBusMessage = None  # type: ignore

try:
    from .error_message_mapper import map_error_to_user_message, get_stage_name
    from .key_vault_reader import KeyVaultReader, KeyVaultError
except ImportError:
    from utils.error_message_mapper import map_error_to_user_message, get_stage_name
    from utils.key_vault_reader import KeyVaultReader, KeyVaultError

logger = logging.getLogger(__name__)


class ServiceBusClientError(Exception):
    """Exception raised for Service Bus client errors"""
    pass


class BackendStatus(str, Enum):
    """Backend status values for data-ingested topic"""
    QUALIFIED = "QUALIFIED"
    TRANSFORMED = "TRANSFORMED"
    ERROR = "ERROR"


class InternalStatus(str, Enum):
    """Internal status values for schema-mapping-service topic"""
    STARTING = "STARTING"
    INTROSPECTION_COMPLETE = "INTROSPECTION_COMPLETE"
    SCHEMA_DETECTED = "SCHEMA_DETECTED"
    SAMPLING_COMPLETE = "SAMPLING_COMPLETE"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    ANONYMIZATION_COMPLETE = "ANONYMIZATION_COMPLETE"
    MAPPING_COMPLETE = "MAPPING_COMPLETE"
    FAILED = "FAILED"


class ServiceBusWriter:
    """
    Unified Service Bus writer for both topics
    
    Handles:
    - Backend topic (data-ingested): quality_report, transformed, error subscriptions
    - Internal topic (schema-mapping-service): system progress subscriptions
    - Error message mapping (technical -> user-friendly)
    - Status enums for consistency
    """
    
    # Topic names
    TOPIC_BACKEND = "data-ingested"
    TOPIC_INTERNAL = "schema-mapping-service"
    
    # Backend subscriptions
    SUBSCRIPTION_QUALITY_REPORT = "quality_report"
    SUBSCRIPTION_TRANSFORMED = "transformed"  # Final curated status (deterministic flow); transformed-llm deprecated
    SUBSCRIPTION_ERROR = "error"
    
    # Internal subscriptions
    SUBSCRIPTION_INTROSPECTION_COMPLETE = "introspection-complete"
    SUBSCRIPTION_SCHEMA_DETECTED = "schema-detected"
    SUBSCRIPTION_SAMPLING_COMPLETE = "sampling-complete"
    SUBSCRIPTION_ANALYSIS_COMPLETE = "analysis-complete"
    SUBSCRIPTION_ANONYMIZATION_COMPLETE = "anonymization-complete"
    SUBSCRIPTION_MAPPING_COMPLETE = "mapping-complete"
    SUBSCRIPTION_FAILED = "failed"
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        key_vault_url: Optional[str] = None,
        secret_name: str = "ServiceBusConnectionString",
        key_vault_reader: Optional[KeyVaultReader] = None
    ):
        """
        Initialize Service Bus Writer
        
        Args:
            connection_string: Service Bus connection string (if provided directly)
            key_vault_url: Key Vault URL to retrieve connection string from
            secret_name: Name of the secret in Key Vault containing connection string
            key_vault_reader: Optional KeyVaultReader instance (if None, will create one)
        """
        if not SERVICE_BUS_AVAILABLE:
            raise ServiceBusClientError(
                "Azure Service Bus SDK not available. Install with: pip install azure-servicebus"
            )
        
        self.connection_string = connection_string
        self.key_vault_url = key_vault_url
        self.secret_name = secret_name
        self.key_vault_reader = key_vault_reader
        self._client: Optional[ServiceBusClient] = None
        self._credential = DefaultAzureCredential() if not connection_string else None
    
    def _get_connection_string(self) -> str:
        """Get Service Bus connection string from Key Vault or use provided one"""
        if self.connection_string:
            return self.connection_string
        
        if not self.key_vault_url and not self.key_vault_reader:
            raise ServiceBusClientError(
                "Either connection_string, key_vault_url, or key_vault_reader must be provided"
            )
        
        try:
            # Use KeyVaultReader if provided, otherwise create one
            if self.key_vault_reader:
                reader = self.key_vault_reader
            else:
                reader = KeyVaultReader(key_vault_url=self.key_vault_url)
            
            connection_string = reader.get_secret(self.secret_name)
            return connection_string
        except KeyVaultError as e:
            raise ServiceBusClientError(
                f"Failed to retrieve connection string from Key Vault: {str(e)}"
            ) from e
        except Exception as e:
            raise ServiceBusClientError(
                f"Unexpected error retrieving connection string: {str(e)}\n"
                f"Stack trace: {traceback.format_exc()}"
            ) from e
    
    def _get_client(self) -> ServiceBusClient:
        """Get or create Service Bus client"""
        if self._client is None:
            connection_string = self._get_connection_string()
            self._client = ServiceBusClient.from_connection_string(connection_string)
        return self._client
    
    def _publish_to_subscription(
        self,
        topic_name: str,
        subscription_name: str,
        message_data: Dict[str, Any],
        message_id: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> None:
        """
        Publish message to a specific subscription
        
        Args:
            topic_name: Topic name
            subscription_name: Subscription name
            message_data: Message data dictionary
            message_id: Optional message ID
            run_id: Optional run ID (required for filtering)
        """
        try:
            client = self._get_client()
            # Note: Service Bus topics don't have direct subscription senders
            # We publish to the topic, and subscriptions filter messages
            # For now, we'll use topic sender and rely on subscription filters
            sender = client.get_topic_sender(topic_name=topic_name)
            try:
                if message_id is None:
                    message_id = f"{message_data.get('training_upload_id') or message_data.get('upload_id', 'unknown')}-{datetime.utcnow().timestamp()}"
                
                # Ensure run_id is in message body
                if run_id and 'run_id' not in message_data:
                    message_data['run_id'] = run_id
                
                # Get run_id from message_data if not provided
                if not run_id:
                    run_id = message_data.get('run_id')
                
                # Get training_upload_id for filtering
                training_upload_id = message_data.get('training_upload_id') or message_data.get('upload_id')
                
                message = ServiceBusMessage(
                    body=json.dumps(message_data),
                    content_type='application/json',
                    message_id=message_id
                )
                
                # Add custom properties for subscription filtering
                # These are used by SQL filters: run_id IS NOT NULL AND training_upload_id IS NOT NULL AND bank_id IS NOT NULL AND bronze_blob_path IS NOT NULL
                application_properties = {
                    "subscription": subscription_name,
                    "status": message_data.get("status", "unknown")
                }
                
                # Add run_id and training_upload_id to custom properties for filtering
                if run_id:
                    application_properties["run_id"] = run_id
                if training_upload_id:
                    application_properties["training_upload_id"] = training_upload_id
                
                # Add bank_id and bronze_blob_path to custom properties for filtering (if present in message_data)
                bank_id = message_data.get("bank_id")
                if bank_id:
                    application_properties["bank_id"] = bank_id
                bronze_blob_path = message_data.get("bronze_blob_path")
                if bronze_blob_path:
                    application_properties["bronze_blob_path"] = bronze_blob_path
                
                # Add transformed_file_path to custom properties for transformed subscription filter
                transformed_file_path = message_data.get("transformed_file_path")
                if transformed_file_path:
                    application_properties["transformed_file_path"] = transformed_file_path
                
                message.application_properties = application_properties
                
                # Set session_id for topics that require ordering (like data-ingested)
                # Use training_upload_id or upload_id as session_id to ensure messages
                # from the same upload are processed in order
                if topic_name == self.TOPIC_BACKEND:
                    session_id = training_upload_id or 'default-session'
                    message.session_id = session_id
                
                sender.send_messages(message)
                logger.info(
                    f"Published message to topic={topic_name}, subscription={subscription_name}, "
                    f"run_id={run_id}, training_upload_id={training_upload_id}"
                )
            finally:
                sender.close()
            
        except Exception as e:
            error_msg = (
                f"Failed to publish message to Service Bus: {str(e)}\n"
                f"Stack trace: {traceback.format_exc()}"
            )
            logger.error(error_msg)
            raise ServiceBusClientError(error_msg) from e
    
    # ============================================================
    # Backend Topic Methods (data-ingested)
    # ============================================================
    
    def publish_quality_report(
        self,
        training_upload_id: str,
        quality_report: Dict[str, Any],
        quality_score: float,
        run_id: Optional[str] = None
    ) -> None:
        """
        Publish quality report to backend's quality_report subscription
        
        Args:
            training_upload_id: Training upload ID
            quality_report: Quality report dictionary
            quality_score: Quality score (0.0-1.0)
            run_id: Run ID (required for filtering)
        """
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "quality_report": quality_report,
            "quality_score": quality_score,
            "status": BackendStatus.QUALIFIED.value,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self._publish_to_subscription(
            topic_name=self.TOPIC_BACKEND,
            subscription_name=self.SUBSCRIPTION_QUALITY_REPORT,
            message_data=message_data,
            run_id=run_id
        )
    
    def publish_transformed(
        self,
        training_upload_id: str,
        transformed_file_path: str,
        features_mapped: Dict[str, Any],  # {count: int, mappings: Dict}
        schema_template_id: str,
        run_id: Optional[str] = None
    ) -> None:
        """
        Publish transformed file info to backend's transformed subscription
        
        Args:
            training_upload_id: Training upload ID
            transformed_file_path: Path to transformed file in Gold layer
            features_mapped: Dictionary with count and mappings
            schema_template_id: PostgreSQL schema template ID
            run_id: Run ID (required for filtering)
        """
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "transformed_file_path": transformed_file_path,
            "features_mapped": features_mapped,
            "schema_template_id": schema_template_id,
            "status": BackendStatus.TRANSFORMED.value,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self._publish_to_subscription(
            topic_name=self.TOPIC_BACKEND,
            subscription_name=self.SUBSCRIPTION_TRANSFORMED,
            message_data=message_data,
            run_id=run_id
        )
    
    def publish_backend_error(
        self,
        training_upload_id: str,
        error_type: str,
        error_message: str,
        system_name: str,
        stack_trace: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> None:
        """
        Publish user-friendly error to backend's error subscription
        
        Args:
            training_upload_id: Training upload ID
            error_type: Error type (e.g., "ValueError")
            error_message: Error message
            system_name: System name that failed
            stack_trace: Optional stack trace
            run_id: Run ID (required for filtering)
        """
        error_code, user_message, technical_summary = map_error_to_user_message(
            error_type, error_message, system_name, stack_trace
        )
        
        stage_name = get_stage_name(system_name)
        
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "error_report": {
                "stage": stage_name,
                "user_message": user_message,
                "technical_summary": technical_summary,
                "error_code": error_code
            },
            "status": BackendStatus.ERROR.value,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self._publish_to_subscription(
            topic_name=self.TOPIC_BACKEND,
            subscription_name=self.SUBSCRIPTION_ERROR,
            message_data=message_data,
            run_id=run_id
        )
    
    # ============================================================
    # Internal Topic Methods (schema-mapping-service)
    # ============================================================
    
    def publish_system_starting(
        self,
        training_upload_id: str,
        bank_id: str,
        system_name: str,
        run_id: Optional[str] = None
    ) -> None:
        """
        Publish system starting message to internal topic
        
        Args:
            training_upload_id: Training upload ID
            bank_id: Bank ID
            system_name: System name (e.g., "System 1: Schema Detection")
            run_id: Run ID (required for filtering)
        """
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "upload_id": training_upload_id,  # Backward compatibility
            "bank_id": bank_id,
            "system_name": system_name,
            "status": InternalStatus.STARTING.value,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Determine subscription based on system name
        subscription = self._get_subscription_for_system(system_name)
        
        self._publish_to_subscription(
            topic_name=self.TOPIC_INTERNAL,
            subscription_name=subscription,
            message_data=message_data,
            run_id=run_id
        )
    
    def publish_system_complete(
        self,
        training_upload_id: str,
        bank_id: str,
        system_name: str,
        status: InternalStatus,
        result: Dict[str, Any],
        run_id: Optional[str] = None
    ) -> None:
        """
        Publish system completion message to internal topic
        
        Args:
            training_upload_id: Training upload ID
            bank_id: Bank ID
            system_name: System name
            status: Internal status enum
            result: Result dictionary
            run_id: Run ID (required for filtering)
        """
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "upload_id": training_upload_id,  # Backward compatibility
            "bank_id": bank_id,
            "system_name": system_name,
            "status": status.value,
            "result": result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Determine subscription based on system name
        subscription = self._get_subscription_for_system(system_name)
        
        self._publish_to_subscription(
            topic_name=self.TOPIC_INTERNAL,
            subscription_name=subscription,
            message_data=message_data,
            run_id=run_id
        )
    
    def publish_system_failed(
        self,
        training_upload_id: str,
        bank_id: str,
        system_name: str,
        error: Dict[str, Any],
        run_id: Optional[str] = None
    ) -> None:
        """
        Publish system failure message to internal topic (detailed technical error)
        
        Args:
            training_upload_id: Training upload ID
            bank_id: Bank ID
            system_name: System name
            error: Error dictionary with detailed technical information
            run_id: Run ID (required for filtering)
        """
        message_data = {
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "upload_id": training_upload_id,  # Backward compatibility
            "bank_id": bank_id,
            "system_name": system_name,
            "status": InternalStatus.FAILED.value,
            "error": error,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self._publish_to_subscription(
            topic_name=self.TOPIC_INTERNAL,
            subscription_name=self.SUBSCRIPTION_FAILED,
            message_data=message_data,
            run_id=run_id
        )

    def publish_mapping_complete_handoff(
        self,
        training_upload_id: str,
        bank_id: str,
        run_id: str,
        request_id: str,
        anonymized_silver_path: str,
        analysis_context_path: str,
        source_system: str = "xds",
        flow_type: str = "training",
        applicant_context: Optional[Dict[str, Any]] = None,
        systems04_summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Publish canonical handoff message to mapping-complete subscription.
        This is consumed by deterministic transformation service.
        """
        message_data = {
            "run_id": run_id,
            "request_id": request_id,
            "training_upload_id": training_upload_id,
            "bank_id": bank_id,
            "data_source_id": bank_id,
            "flow_type": flow_type,
            "source_system": source_system,
            "anonymized_silver_path": anonymized_silver_path,
            "analysis_context_path": analysis_context_path,
            "applicant_context": applicant_context or {},
            "systems04_summary": systems04_summary or {},
            "status": InternalStatus.MAPPING_COMPLETE.value,
            "system_name": "System 4: Dataset Anonymizer",
            "timestamp": datetime.utcnow().isoformat(),
        }
        self._publish_to_subscription(
            topic_name=self.TOPIC_INTERNAL,
            subscription_name=self.SUBSCRIPTION_MAPPING_COMPLETE,
            message_data=message_data,
            run_id=run_id,
        )
    
    def _get_subscription_for_system(self, system_name: str) -> str:
        """
        Get subscription name for a system
        
        Args:
            system_name: System name (e.g., "System 0: File Introspection")
            
        Returns:
            Subscription name
        """
        system_lower = system_name.lower()
        
        if "introspection" in system_lower or "system 0" in system_lower:
            return self.SUBSCRIPTION_INTROSPECTION_COMPLETE
        elif "schema detection" in system_lower or "system 1" in system_lower:
            return self.SUBSCRIPTION_SCHEMA_DETECTED
        elif "sampling" in system_lower or "system 2" in system_lower:
            return self.SUBSCRIPTION_SAMPLING_COMPLETE
        elif "analysis" in system_lower or "system 3" in system_lower:
            return self.SUBSCRIPTION_ANALYSIS_COMPLETE
        elif "anonymiz" in system_lower or "pii" in system_lower or "system 4" in system_lower:
            return self.SUBSCRIPTION_ANONYMIZATION_COMPLETE
        elif "mapping" in system_lower or "system 5" in system_lower:
            return self.SUBSCRIPTION_MAPPING_COMPLETE
        else:
            return self.SUBSCRIPTION_FAILED
    
    def close(self):
        """Close Service Bus client connection"""
        if self._client:
            self._client.close()
            self._client = None
