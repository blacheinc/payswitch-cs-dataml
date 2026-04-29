"""
Script to send a test message WITH run_id to Service Bus (Happy Path Test)
This is for Phase 3 testing - verifying full pipeline with run_id works end-to-end
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


def send_test_message_with_run_id(
    key_vault_url: str,
    run_id: str = None,
    training_upload_id: str = None,
    bank_id: str = "bank-digital-001",
    bronze_blob_path: str = None
):
    """
    Send a test message WITH run_id to Service Bus (Happy Path Test)
    
    Args:
        key_vault_url: Key Vault URL
        run_id: Run ID (will generate UUID if not provided)
        training_upload_id: Training upload ID (will generate if not provided)
        bank_id: Bank ID
        bronze_blob_path: Full path to file in ADLS bronze layer
    """
    # Generate run_id if not provided
    if not run_id:
        run_id = str(uuid.uuid4())
    
    # Generate upload ID if not provided
    if not training_upload_id:
        training_upload_id = str(uuid.uuid4())
    
    # Default bronze path if not provided
    # Use the date where the test files actually exist (2026-02-24)
    if not bronze_blob_path:
        date_str = "2026-02-24"  # Date where JSON test files actually exist
        bronze_blob_path = f"bronze/training/{bank_id}/{date_str}/test_data_with_pii.json"
    
    # Create message payload WITH run_id
    message_data = {
        "run_id": run_id,  # REQUIRED for new implementation
        "training_upload_id": training_upload_id,
        "bank_id": bank_id,
        "bronze_blob_path": bronze_blob_path
    }
    
    print("="*60)
    print("Sending Test Message WITH run_id (Happy Path Test)")
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
        message.message_id = str(uuid.uuid4())
        
        # IMPORTANT: Set Session ID (required for partitioned topics with ordering)
        message.session_id = training_upload_id
        
        # Set custom properties for subscription filtering
        # These are used by SQL filters: run_id IS NOT NULL AND training_upload_id IS NOT NULL AND bank_id IS NOT NULL AND bronze_blob_path IS NOT NULL
        message.application_properties = {
            "subscription": "start-transformation",
            "source": "test-script-with-run-id",
            "run_id": run_id,  # For SQL filter
            "training_upload_id": training_upload_id,  # For SQL filter
            "bank_id": bank_id,  # For SQL filter
            "bronze_blob_path": bronze_blob_path  # For SQL filter
        }
        
        print(f"Message ID: {message.message_id}")
        print(f"Session ID: {training_upload_id}")
        print(f"Run ID: {run_id}")
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
        print(f"Run ID: {run_id}")
        print(f"Session ID: {training_upload_id}")
        print(f"Message Body: {message_body}")
        print()
        print("Expected behavior:")
        print("  - Pipeline should process with run_id tracking")
        print("  - PostgreSQL records should be created")
        print("  - All logs should include [run_id=...] prefix")
        print("  - Silver file path should include run_id")
        
    except Exception as e:
        print(f"[ERROR] Error sending message: {str(e)}")
        raise
    finally:
        sender.close()
        servicebus_client.close()


if __name__ == "__main__":
    import argparse

    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Send data-ingested message (with run_id) to trigger schema mapping on a bronze file."
    )
    parser.add_argument(
        "--training-upload-id",
        default=None,
        help="training_uploads.id UUID (default: random)",
    )
    parser.add_argument(
        "--bank-id",
        default=None,
        help="bank_id = data_source_id UUID",
    )
    parser.add_argument(
        "--bronze-blob-path",
        default=None,
        help="Full ADLS path, e.g. bronze/training/<data_source_id>/<YYYY-MM-DD>/<training_upload_id>.json (omit for script default)",
    )
    parser.add_argument("--run-id", default=None, help="Optional; default new UUID")
    parser.add_argument(
        "--key-vault-url",
        default=os.getenv(
            "KEY_VAULT_URL", "https://blachekvruhclai6km.vault.azure.net/"
        ),
    )
    args = parser.parse_args()

    try:
        send_test_message_with_run_id(
            key_vault_url=args.key_vault_url,
            run_id=args.run_id,
            training_upload_id=args.training_upload_id,
            bank_id=args.bank_id or "bank-digital-001",
            bronze_blob_path=args.bronze_blob_path,
        )
    except Exception as e:
        print(f"\n[ERROR] Failed to send message: {str(e)}")
        sys.exit(1)
