"""
Example script for backend engineers to send messages to trigger ADF pipeline

This script demonstrates how to send a Service Bus message that will trigger
the ADF training data ingestion pipeline.

Prerequisites:
- Azure Service Bus connection string
- training_uploads record with status = 'ingesting'
- File exists in Blob Storage at the specified raw_file_path
"""

import json
import uuid
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

# Configuration
KEY_VAULT_URL = "https://your-keyvault.vault.azure.net/"  # Update with your Key Vault URL
SERVICE_BUS_TOPIC = "data-awaits-ingestion"

# Message data - Replace with actual values from training_uploads table
MESSAGE_DATA = {
    "training_upload_id": "70257f35-edcf-4c1c-a129-4d5ded8ceaa5",  # From training_uploads.id
    "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",      # From training_uploads.data_source_id
    "file_format": "json",                                          # From training_uploads.file_format
    "file_size_bytes": 4547,                                        # From training_uploads.file_size_bytes
    "raw_file_path": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf/test_ingestion_1.json"  # From training_uploads.raw_file_path
}


def get_service_bus_connection_string(key_vault_url: str) -> str:
    """Retrieve Service Bus connection string from Key Vault"""
    credential = DefaultAzureCredential()
    secret_client = SecretClient(vault_url=key_vault_url, credential=credential)
    
    # Try common secret names
    secret_names = [
        "ServiceBusConnectionString",
        "serviceBusConnectionString",
        "ServiceBusConnection"
    ]
    
    for secret_name in secret_names:
        try:
            secret = secret_client.get_secret(secret_name)
            return secret.value
        except Exception:
            continue
    
    raise ValueError(f"Service Bus connection string not found in Key Vault. Tried: {secret_names}")


def send_adf_trigger_message(
    message_data: dict,
    service_bus_connection_string: str,
    topic_name: str = SERVICE_BUS_TOPIC
):
    """
    Send Service Bus message to trigger ADF pipeline
    
    Args:
        message_data: Dictionary with training_upload_id, data_source_id, file_format, 
                     file_size_bytes, raw_file_path
        service_bus_connection_string: Service Bus connection string
        topic_name: Service Bus topic name (default: data-awaits-ingestion)
    """
    # Validate required fields
    required_fields = ["training_upload_id", "data_source_id", "file_format", "file_size_bytes", "raw_file_path"]
    missing_fields = [field for field in required_fields if field not in message_data or not message_data[field]]
    
    if missing_fields:
        raise ValueError(f"Missing required fields: {missing_fields}")
    
    # Create Service Bus client
    servicebus_client = ServiceBusClient.from_connection_string(service_bus_connection_string)
    sender = servicebus_client.get_topic_sender(topic_name=topic_name)
    
    try:
        # Create message body
        message_body = json.dumps(message_data)
        message = ServiceBusMessage(message_body)
        
        # Set message metadata
        message.message_id = str(uuid.uuid4())
        message.session_id = message_data["training_upload_id"]
        
        # Set custom properties (REQUIRED for ADF trigger subscription filter)
        message.application_properties = {
            "processing_system": "ADF",  # REQUIRED: Must be "ADF" for the subscription filter
            "training_upload_id": message_data["training_upload_id"]  # Optional but recommended
        }
        
        # Send message
        print(f"Sending message to topic: {topic_name}")
        print(f"Training Upload ID: {message_data['training_upload_id']}")
        print(f"Message ID: {message.message_id}")
        print(f"Session ID: {message.session_id}")
        print(f"Custom Properties: {message.application_properties}")
        
        sender.send_messages(message)
        
        print("\n✅ Message sent successfully!")
        print(f"\nThe ADF pipeline will be triggered automatically.")
        print(f"Monitor pipeline execution in Azure Portal:")
        print(f"  Data Factory → Pipelines → pipeline-training-data-ingestion → Monitor")
        
    except Exception as e:
        print(f"\n❌ Error sending message: {str(e)}")
        raise
    finally:
        sender.close()
        servicebus_client.close()


def main():
    """Main function"""
    print("=" * 60)
    print("ADF Pipeline Trigger - Message Sender")
    print("=" * 60)
    print()
    
    # Option 1: Use connection string directly (if you have it)
    # SERVICE_BUS_CONNECTION_STRING = "Endpoint=sb://..."
    
    # Option 2: Retrieve from Key Vault (recommended)
    try:
        print("Retrieving Service Bus connection string from Key Vault...")
        service_bus_connection_string = get_service_bus_connection_string(KEY_VAULT_URL)
        print("✅ Connection string retrieved")
    except Exception as e:
        print(f"❌ Failed to retrieve connection string: {str(e)}")
        print("\nAlternative: Set SERVICE_BUS_CONNECTION_STRING directly in the script")
        return
    
    print()
    print("Message Data:")
    print(json.dumps(MESSAGE_DATA, indent=2))
    print()
    
    # Send message
    try:
        send_adf_trigger_message(
            message_data=MESSAGE_DATA,
            service_bus_connection_string=service_bus_connection_string
        )
    except Exception as e:
        print(f"\n❌ Failed to send message: {str(e)}")
        return


if __name__ == "__main__":
    main()
