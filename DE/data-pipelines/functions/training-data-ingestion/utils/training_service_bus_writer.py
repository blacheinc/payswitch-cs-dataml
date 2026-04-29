"""
Training Data Ingestion - Service Bus Writer
Unified Service Bus writer for publishing messages to topics
Adapted from schema-mapping-service for training-data-ingestion
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

from .training_error_message_mapper import map_error_to_user_message, get_stage_name
from .training_key_vault_reader import TrainingKeyVaultReader, TrainingKeyVaultError

logger = logging.getLogger(__name__)


class TrainingServiceBusClientError(Exception):
    """Exception raised for Service Bus client errors"""
    pass


class BackendStatus(str, Enum):
    """Backend status values for data-ingested topic"""
    QUALIFIED = "QUALIFIED"
    TRANSFORMED = "TRANSFORMED"
    ERROR = "ERROR"


class TrainingServiceBusWriter:
    """
    Unified Service Bus writer for training data ingestion
    
    Handles:
    - Backend topic (data-ingested): quality_report, transformed, error subscriptions
    - Error message mapping (technical -> user-friendly)
    - Status enums for consistency
    
    Note:
        Azure Service Bus SDK automatically retries transient failures (network errors,
        throttling, service unavailability) with exponential backoff. No explicit retry
        logic is needed in this class.
    """
    
    # Topic names
    TOPIC_BACKEND = "data-ingested"
    
    # Backend subscriptions
    SUBSCRIPTION_QUALITY_REPORT = "quality_report"
    SUBSCRIPTION_TRANSFORMED = "transformed"
    SUBSCRIPTION_ERROR = "error"
    SUBSCRIPTION_START_TRANSFORMATION = "start-transformation"
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        key_vault_url: Optional[str] = None,
        secret_name: str = "ServiceBusConnectionString",
        key_vault_reader: Optional[TrainingKeyVaultReader] = None
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
            raise TrainingServiceBusClientError(
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
            raise TrainingServiceBusClientError(
                "Either connection_string, key_vault_url, or key_vault_reader must be provided"
            )
        
        try:
            # Use KeyVaultReader if provided, otherwise create one
            if self.key_vault_reader:
                reader = self.key_vault_reader
            else:
                reader = TrainingKeyVaultReader(key_vault_url=self.key_vault_url)
            
            connection_string = reader.get_secret(self.secret_name)
            return connection_string
        except TrainingKeyVaultError as e:
            raise TrainingServiceBusClientError(
                f"Failed to retrieve connection string from Key Vault: {str(e)}"
            ) from e
        except Exception as e:
            raise TrainingServiceBusClientError(
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
            raise TrainingServiceBusClientError(error_msg) from e
    
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
    
    def close(self):
        """Close Service Bus client connection"""
        if self._client:
            self._client.close()
            self._client = None
