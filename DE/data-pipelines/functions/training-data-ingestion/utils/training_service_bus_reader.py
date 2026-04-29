"""
Training Data Ingestion - Service Bus Reader
Utility for reading messages from Service Bus topics
Adapted from schema-mapping-service for training-data-ingestion
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from azure.servicebus import ServiceBusClient, ServiceBusReceiver, ServiceBusMessage

try:
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    SERVICE_BUS_AVAILABLE = True
except ImportError:
    SERVICE_BUS_AVAILABLE = False
    ServiceBusClient = None  # type: ignore
    ServiceBusMessage = None  # type: ignore

from .training_key_vault_reader import TrainingKeyVaultReader
from .training_service_bus_writer import TrainingServiceBusClientError

logger = logging.getLogger(__name__)


class TrainingServiceBusReader:
    """
    Service Bus reader for training data ingestion
    
    Primarily used for:
    - Reading messages from dead-letter queues
    - Testing message publishing
    - Debugging subscription filters
    - Batch processing messages
    
    Note:
        Azure Service Bus SDK automatically retries transient failures (network errors,
        throttling, service unavailability) with exponential backoff. No explicit retry
        logic is needed in this class.
    """
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        key_vault_url: Optional[str] = None,
        secret_name: str = "ServiceBusConnectionString"
    ):
        """
        Initialize Service Bus Reader
        
        Args:
            connection_string: Service Bus connection string (if provided directly)
            key_vault_url: Key Vault URL to retrieve connection string from
            secret_name: Name of the secret in Key Vault containing connection string
        """
        if not SERVICE_BUS_AVAILABLE:
            raise TrainingServiceBusClientError(
                "Azure Service Bus SDK not available. Install with: pip install azure-servicebus"
            )
        
        self.connection_string = connection_string
        self.key_vault_url = key_vault_url
        self.secret_name = secret_name
        self._client: Optional[ServiceBusClient] = None
        self._key_vault_reader: Optional[TrainingKeyVaultReader] = None
        self._receiver: Optional[ServiceBusReceiver] = None
    
    def _get_key_vault_reader(self) -> TrainingKeyVaultReader:
        """Get or create KeyVaultReader instance"""
        if self._key_vault_reader is None:
            if not self.key_vault_url:
                raise TrainingServiceBusClientError(
                    "key_vault_url is required when connection_string is not provided"
                )
            self._key_vault_reader = TrainingKeyVaultReader(key_vault_url=self.key_vault_url)
        return self._key_vault_reader
    
    def _get_connection_string(self) -> str:
        """Get Service Bus connection string from Key Vault or use provided one"""
        if self.connection_string:
            return self.connection_string
        
        if not self.key_vault_url:
            raise TrainingServiceBusClientError(
                "Either connection_string or key_vault_url must be provided"
            )
        
        try:
            reader = self._get_key_vault_reader()
            connection_string = reader.get_secret(self.secret_name)
            return connection_string
        except Exception as e:
            raise TrainingServiceBusClientError(
                f"Failed to retrieve connection string from Key Vault: {str(e)}"
            )
    
    def _get_client(self) -> ServiceBusClient:
        """Get or create Service Bus client"""
        if self._client is None:
            connection_string = self._get_connection_string()
            self._client = ServiceBusClient.from_connection_string(connection_string)
        return self._client
    
    def peek_all_messages(
        self,
        topic_name: str,
        subscription_name: str,
        max_messages: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Peek at all available messages (up to max_messages) without removing them
        
        Args:
            topic_name: Topic name
            subscription_name: Subscription name
            max_messages: Maximum number of messages to peek (default: 1000)
            
        Returns:
            List of message dictionaries with parsed body and metadata
        """
        messages = []
        
        try:
            client = self._get_client()
            with client:
                receiver = client.get_subscription_receiver(
                    topic_name=topic_name,
                    subscription_name=subscription_name
                )
                with receiver:
                    peeked_messages = receiver.peek_messages(max_message_count=max_messages)
                    
                    for message in peeked_messages:
                        try:
                            # Parse message body
                            body = self._parse_message_body(message)
                            message_data = json.loads(body)
                            
                            # Add message metadata
                            message_info = {
                                **message_data,
                                "_message_id": message.message_id,
                                "_sequence_number": message.sequence_number if hasattr(message, 'sequence_number') else None
                            }
                            messages.append(message_info)
                            
                        except Exception as e:
                            logger.error(f"Error processing peeked message: {str(e)}")
            
            logger.info(f"Peeked at {len(messages)} messages from {topic_name}/{subscription_name}")
            return messages
            
        except Exception as e:
            logger.error(f"Error peeking messages: {str(e)}")
            raise TrainingServiceBusClientError(f"Failed to peek messages: {str(e)}") from e
    
    def receive_next_message(
        self,
        topic_name: str,
        subscription_name: str,
        max_wait_time: int = 30,
        max_lock_duration: int = 120
    ) -> tuple[Optional[ServiceBusMessage], Optional[ServiceBusReceiver]]:
        """
        Receive the next available message from the subscription (locks the message)
        
        Args:
            topic_name: Topic name
            subscription_name: Subscription name
            max_wait_time: Maximum wait time in seconds (default: 30)
            max_lock_duration: Maximum lock duration in seconds (default: 120)
            
        Returns:
            Tuple of (ServiceBusMessage object if message received, None if timeout, ServiceBusReceiver)
        """
        try:
            client = self._get_client()
            receiver = client.get_subscription_receiver(
                topic_name=topic_name,
                subscription_name=subscription_name,
                max_lock_duration=max_lock_duration
            )
            messages = receiver.receive_messages(
                max_message_count=1,
                max_wait_time=max_wait_time
            )
            
            if messages:
                return (messages[0], receiver)
            return (None, receiver)
            
        except Exception as e:
            logger.error(f"Error receiving message: {str(e)}")
            raise TrainingServiceBusClientError(f"Failed to receive message: {str(e)}") from e
    
    def complete_message(self, receiver: ServiceBusReceiver, message: ServiceBusMessage) -> None:
        """
        Complete a message (remove it from the queue)
        
        Args:
            receiver: ServiceBusReceiver that received the message
            message: ServiceBusMessage to complete
        """
        try:
            receiver.complete_message(message)
            logger.debug(f"Completed message: {message.message_id}")
        except Exception as e:
            logger.error(f"Error completing message: {str(e)}")
            raise TrainingServiceBusClientError(f"Failed to complete message: {str(e)}") from e
    
    def abandon_message(self, receiver: ServiceBusReceiver, message: ServiceBusMessage) -> None:
        """
        Abandon a message (return it to the queue for retry)
        
        Args:
            receiver: ServiceBusReceiver that received the message
            message: ServiceBusMessage to abandon
        """
        try:
            receiver.abandon_message(message)
            logger.debug(f"Abandoned message: {message.message_id}")
        except Exception as e:
            logger.error(f"Error abandoning message: {str(e)}")
            raise TrainingServiceBusClientError(f"Failed to abandon message: {str(e)}") from e
    
    def dead_letter_message(
        self,
        receiver: ServiceBusReceiver,
        message: ServiceBusMessage,
        reason: str = "Message processing failed",
        description: Optional[str] = None
    ) -> None:
        """
        Dead-letter a message (move it to dead-letter queue)
        
        Args:
            receiver: ServiceBusReceiver that received the message
            message: ServiceBusMessage to dead-letter
            reason: Reason for dead-lettering
            description: Optional description
        """
        try:
            receiver.dead_letter_message(message, reason=reason, error_description=description)
            logger.info(f"Dead-lettered message: {message.message_id}, reason: {reason}")
        except Exception as e:
            logger.error(f"Error dead-lettering message: {str(e)}")
            raise TrainingServiceBusClientError(f"Failed to dead-letter message: {str(e)}") from e
    
    def _parse_message_body(self, message) -> str:
        """Helper method to parse message body from various formats"""
        body = None
        
        # Try body_as_str() first (newer SDK versions)
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
                # Handle generators or iterables
                if hasattr(body, '__iter__') and not isinstance(body, (str, bytes)):
                    try:
                        # Try to join as bytes first
                        chunks = list(body)
                        if chunks and isinstance(chunks[0], bytes):
                            body = b''.join(chunks).decode('utf-8')
                        else:
                            body = ''.join(str(chunk) for chunk in chunks)
                    except Exception:
                        body = str(body)
                else:
                    body = str(body)
        
        return body
    
    def close(self):
        """Close Service Bus client connection, receiver, and Key Vault reader"""
        if self._receiver:
            try:
                self._receiver.close()
            except Exception:
                pass
            self._receiver = None
        if self._client:
            self._client.close()
            self._client = None
        if self._key_vault_reader:
            self._key_vault_reader.close()
            self._key_vault_reader = None
