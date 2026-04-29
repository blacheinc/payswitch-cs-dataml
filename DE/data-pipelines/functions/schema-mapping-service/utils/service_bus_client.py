"""
Service Bus Client
Centralized client for publishing failure and success messages to Service Bus topics
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime

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
    # Define dummy types for type checking when azure.servicebus is not available
    ServiceBusClient = None  # type: ignore
    ServiceBusMessage = None  # type: ignore

logger = logging.getLogger(__name__)


class ServiceBusClientError(Exception):
    """Exception raised for Service Bus client errors"""
    pass


class ServiceBusPublisher:
    """
    Centralized Service Bus client for publishing messages
    
    Handles:
    - Publishing failure messages to 'schema-mapping-failed' topic
    - Publishing success messages to 'schema-mapping-complete' topic
    - Error handling with stack traces
    - Connection string retrieval from Key Vault
    """
    
    # Topic names
    TOPIC_FAILED = "schema-mapping-failed"
    TOPIC_COMPLETE = "schema-mapping-complete"
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        key_vault_url: Optional[str] = None,
        secret_name: str = "ServiceBusConnectionString"
    ):
        """
        Initialize Service Bus Publisher
        
        Args:
            connection_string: Service Bus connection string (if provided directly)
            key_vault_url: Key Vault URL to retrieve connection string from
            secret_name: Name of the secret in Key Vault containing connection string
        """
        if not SERVICE_BUS_AVAILABLE:
            raise ServiceBusClientError(
                "Azure Service Bus SDK not available. Install with: pip install azure-servicebus"
            )
        
        self.connection_string = connection_string
        self.key_vault_url = key_vault_url
        self.secret_name = secret_name
        self._client: Optional[ServiceBusClient] = None
        self._credential = DefaultAzureCredential() if not connection_string else None
    
    def _get_connection_string(self) -> str:
        """
        Get Service Bus connection string from Key Vault or use provided one
        
        Returns:
            Service Bus connection string
            
        Raises:
            ServiceBusClientError: If connection string cannot be retrieved
        """
        if self.connection_string:
            return self.connection_string
        
        if not self.key_vault_url:
            raise ServiceBusClientError(
                "Either connection_string or key_vault_url must be provided"
            )
        
        try:
            secret_client = SecretClient(
                vault_url=self.key_vault_url,
                credential=self._credential
            )
            connection_string = secret_client.get_secret(self.secret_name).value
            return connection_string
        except Exception as e:
            raise ServiceBusClientError(
                f"Failed to retrieve connection string from Key Vault: {str(e)}\n"
                f"Stack trace: {traceback.format_exc()}"
            )
    
    def _get_client(self) -> ServiceBusClient:
        """
        Get or create Service Bus client
        
        Returns:
            ServiceBusClient instance
        """
        if self._client is None:
            connection_string = self._get_connection_string()
            self._client = ServiceBusClient.from_connection_string(connection_string)
        return self._client
    
    def publish_failure(
        self,
        upload_id: str,
        bank_id: str,
        system_name: str,
        error_message: str,
        error_type: str,
        stack_trace: Optional[str] = None,
        bronze_blob_path: Optional[str] = None,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Publish failure message to 'schema-mapping-failed' topic
        
        Args:
            upload_id: Upload identifier
            bank_id: Bank identifier
            system_name: Name of the system that failed (e.g., "System 0: File Introspection")
            error_message: Error message
            error_type: Type of error (e.g., "ValueError", "ConnectionError")
            stack_trace: Full stack trace (if None, will be captured automatically)
            bronze_blob_path: Optional bronze blob path
            additional_context: Optional additional context dictionary
            
        Raises:
            ServiceBusClientError: If publishing fails
        """
        try:
            # Capture stack trace if not provided
            if stack_trace is None:
                stack_trace = traceback.format_exc()
            
            # Build failure message
            message_data = {
                "upload_id": upload_id,
                "bank_id": bank_id,
                "system_name": system_name,
                "status": "failed",
                "error": {
                    "message": error_message,
                    "type": error_type,
                    "stack_trace": stack_trace
                },
                "timestamp": datetime.utcnow().isoformat(),
                "bronze_blob_path": bronze_blob_path
            }
            
            # Add additional context if provided
            if additional_context:
                message_data["context"] = additional_context
            
            # Publish to Service Bus
            client = self._get_client()
            with client:
                sender = client.get_topic_sender(topic_name=self.TOPIC_FAILED)
                with sender:
                    message = ServiceBusMessage(
                        body=json.dumps(message_data),
                        content_type='application/json',
                        message_id=f"{upload_id}-{system_name}-{datetime.utcnow().timestamp()}"
                    )
                    sender.send_messages(message)
            
            logger.info(
                f"Published failure message for upload_id={upload_id}, "
                f"system={system_name}, error_type={error_type}"
            )
            
        except Exception as e:
            error_msg = (
                f"Failed to publish failure message to Service Bus: {str(e)}\n"
                f"Stack trace: {traceback.format_exc()}"
            )
            logger.error(error_msg)
            raise ServiceBusClientError(error_msg) from e
    
    def publish_success(
        self,
        upload_id: str,
        bank_id: str,
        system_name: str,
        result: Dict[str, Any],
        bronze_blob_path: Optional[str] = None
    ) -> None:
        """
        Publish success message to 'schema-mapping-complete' topic
        
        Args:
            upload_id: Upload identifier
            bank_id: Bank identifier
            system_name: Name of the system that completed (e.g., "System 5: Schema Mapping")
            result: Result dictionary with system output
            bronze_blob_path: Optional bronze blob path
            
        Raises:
            ServiceBusClientError: If publishing fails
        """
        try:
            # Build success message
            message_data = {
                "upload_id": upload_id,
                "bank_id": bank_id,
                "system_name": system_name,
                "status": "success",
                "result": result,
                "timestamp": datetime.utcnow().isoformat(),
                "bronze_blob_path": bronze_blob_path
            }
            
            # Publish to Service Bus
            client = self._get_client()
            with client:
                sender = client.get_topic_sender(topic_name=self.TOPIC_COMPLETE)
                with sender:
                    message = ServiceBusMessage(
                        body=json.dumps(message_data),
                        content_type='application/json',
                        message_id=f"{upload_id}-{system_name}-{datetime.utcnow().timestamp()}"
                    )
                    sender.send_messages(message)
            
            logger.info(
                f"Published success message for upload_id={upload_id}, system={system_name}"
            )
            
        except Exception as e:
            error_msg = (
                f"Failed to publish success message to Service Bus: {str(e)}\n"
                f"Stack trace: {traceback.format_exc()}"
            )
            logger.error(error_msg)
            raise ServiceBusClientError(error_msg) from e
    
    def close(self):
        """Close Service Bus client connection"""
        if self._client:
            self._client.close()
            self._client = None
