"""
Script to send a test message to Service Bus to trigger the Schema Mapping Function
This script properly sets the Session ID required for partitioned topics with ordering
"""

import os
import sys
import json
import uuid
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from utils.key_vault_reader import KeyVaultReader


def load_dotenv(dotenv_path: str = None) -> None:
    """
    Minimal .env loader.
    
    - Lines starting with '#' are comments.
    - Empty lines are ignored.
    - KEY=VALUE pairs are loaded into os.environ if not already set.
    """
    if dotenv_path is None:
        # Look for .env in project root (parent of scripts/ directory)
        CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
        PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
        dotenv_path = os.path.join(PROJECT_ROOT, ".env")
    
    if not os.path.exists(dotenv_path):
        print(f"[WARNING] .env file not found at {dotenv_path} - relying on existing environment variables only")
        return
    
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def send_test_message(
    key_vault_url: str,
    training_upload_id: str = None,
    bank_id: str = "bank-digital-001",
    bronze_blob_path: str = None,
    run_id: str = None,
):
    """
    Send a test message to Service Bus to trigger the Schema Mapping Function
    
    Args:
        key_vault_url: Key Vault URL
        training_upload_id: Training upload ID (will generate if not provided)
        bank_id: Bank ID (same UUID as data_source_id for training uploads)
        bronze_blob_path: Full path in ADLS, e.g. bronze/training/{bank_id}/{YYYY-MM-DD}/{upload_id}.json
        run_id: Correlation id for silver output path; generated if omitted (required by orchestrator)
    """
    # Generate upload ID if not provided
    if not training_upload_id:
        training_upload_id = str(uuid.uuid4())

    if not run_id:
        run_id = str(uuid.uuid4())
    
    # Default bronze path if not provided
    # Use the date where the test files actually exist (2026-03-04)
    if not bronze_blob_path:
        date_str = "2026-03-04"  # Date where test files actually exist
        bronze_blob_path = f"bronze/training/{bank_id}/{date_str}/test_data_with_pii.csv"
    
    # Create message payload
    message_data = {
        "run_id": run_id,
        "training_upload_id": training_upload_id,
        "bank_id": bank_id,
        "bronze_blob_path": bronze_blob_path,
    }
    
    print("="*60)
    print("Sending Test Message to Service Bus")
    print("="*60)
    print(f"Run ID: {run_id}")
    print(f"Training Upload ID: {training_upload_id}")
    print(f"Bank ID: {bank_id}")
    print(f"Bronze Blob Path: {bronze_blob_path}")
    print()
    
    # Prefer ServiceBusConnectionString from environment for local testing
    connection_string = os.getenv("ServiceBusConnectionString")
    if connection_string:
        print("Using ServiceBusConnectionString from environment (bypassing Key Vault for local testing)")
    else:
        # Fallback: Get Service Bus connection string from Key Vault
        print("Retrieving Service Bus connection string from Key Vault...")
        with KeyVaultReader(key_vault_url=key_vault_url) as kv_reader:
            connection_string = kv_reader.get_secret("ServiceBusConnectionString")
        
        if not connection_string:
            raise ValueError("ServiceBusConnectionString not found in environment or Key Vault")
        
        print("[OK] Connection string retrieved from Key Vault")
    print()
    
    # Create Service Bus client
    print("Connecting to Service Bus...")
    servicebus_client = ServiceBusClient.from_connection_string(connection_string)
    
    # Create sender for the topic
    topic_name = "data-ingested"
    print(f"Creating sender for topic: {topic_name}")
    sender = servicebus_client.get_topic_sender(topic_name=topic_name)
    
    try:
        # Create message
        message_body = json.dumps(message_data)
        message = ServiceBusMessage(message_body)
        
        # IMPORTANT: Set unique Message ID to avoid duplicate detection issues
        # Generate a unique message ID for each message
        message.message_id = str(uuid.uuid4())
        
        # IMPORTANT: Set Session ID (required for partitioned topics with ordering)
        # Use training_upload_id as session_id to ensure messages from the same upload
        # are processed in order
        message.session_id = training_upload_id
        
        # Custom properties for SQL filters on start-transformation (when enabled)
        message.application_properties = {
            "subscription": "start-transformation",
            "source": "test-script",
            "run_id": run_id,
            "training_upload_id": training_upload_id,
            "bank_id": bank_id,
            "bronze_blob_path": bronze_blob_path,
        }
        
        print(f"Message ID: {message.message_id}")
        print(f"Session ID: {training_upload_id}")
        print(f"Custom properties: {message.application_properties}")
        print()
        
        # Send message
        print("Sending message...")
        sender.send_messages(message)
        print("[OK] Message sent successfully!")
        print()
        
        print("="*60)
        print("Message Details")
        print("="*60)
        print(f"Topic: {topic_name}")
        print(f"Subscription: start-transformation")
        print(f"Session ID: {training_upload_id}")
        print(f"Message Body: {message_body}")
        print()
        print("The function should be triggered automatically.")
        print("Monitor logs with:")
        print("  az functionapp log tail --name schema-mapping-service --resource-group blache-cdtscr-dev-data-rg --follow")
        
    except Exception as e:
        print(f"[ERROR] Error sending message: {str(e)}")
        raise
    finally:
        sender.close()
        servicebus_client.close()


if __name__ == "__main__":
    # Load .env file first (before checking environment variables)
    load_dotenv()
    
    # Configuration
    KEY_VAULT_URL = os.getenv(
        "KEY_VAULT_URL",
        "https://blachekvruhclai6km.vault.azure.net/"
    )
    
    # You can customize these values
    TRAINING_UPLOAD_ID = None  # Will generate UUID if None
    BANK_ID = "bank-digital-001"
    BRONZE_BLOB_PATH = None  # Will use default if None
    
    # Example: Use specific path
    # BRONZE_BLOB_PATH = "bronze/training/bank-digital-001/2026-03-04/test_data_with_pii.csv"
    
    try:
        send_test_message(
            key_vault_url=KEY_VAULT_URL,
            training_upload_id=TRAINING_UPLOAD_ID,
            bank_id=BANK_ID,
            bronze_blob_path=BRONZE_BLOB_PATH
        )
    except Exception as e:
        print(f"\n[ERROR] Failed to send message: {str(e)}")
        sys.exit(1)
