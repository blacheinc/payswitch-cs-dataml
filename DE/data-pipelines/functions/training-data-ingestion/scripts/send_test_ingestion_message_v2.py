"""
Script 3: Send Service Bus Message to data-awaits-ingestion Topic
Sends a message with training_upload_id and metadata.

Default (no flag): application properties match **temp-peek-subscription** — use with
``run_training_ingestion.py`` (Azure Function path).

``--adf``: sets ``processing_system = "ADF"`` so **adf-trigger-subscription** receives
the message and the deployed **adf-pipeline-trigger** Function runs
``pipeline-training-data-ingestion`` (blob → bronze in ADF). Do **not** run
``run_training_ingestion.py`` for that message.
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

# Try to import dotenv
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False
    print("⚠️  python-dotenv not installed. Will use environment variables only.")

from azure.servicebus import ServiceBusClient, ServiceBusMessage

# Add parent directories to path
CURRENT_DIR = Path(__file__).parent
TRAINING_INGESTION_ROOT = CURRENT_DIR.parent

# Add paths for imports
if str(TRAINING_INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_INGESTION_ROOT))

# Load environment variables
if HAS_DOTENV:
    env_path = TRAINING_INGESTION_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

from utils.training_key_vault_reader import (
    TrainingKeyVaultReader as KeyVaultReader,
    TrainingKeyVaultError as KeyVaultError,
)


def main():
    """Main function to send Service Bus message"""
    parser = argparse.ArgumentParser(
        description="Send training ingestion message to data-awaits-ingestion."
    )
    parser.add_argument(
        "--adf",
        action="store_true",
        help=(
            "ADF route: set application_properties processing_system=ADF for "
            "adf-trigger-subscription (pipeline-training-data-ingestion). "
            "Do not use run_training_ingestion.py for this message."
        ),
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Script 3: Send Service Bus Message to data-awaits-ingestion")
    if args.adf:
        print("Mode: ADF (processing_system=ADF → adf-trigger-subscription)")
    else:
        print("Mode: Azure Function / temp-peek (no ADF routing)")
    print("=" * 60)
    
    # Load environment variables
    if HAS_DOTENV:
        env_path = os.path.join(TRAINING_INGESTION_ROOT, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
    
    # Configuration
    KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
    if not KEY_VAULT_URL:
        raise ValueError("KEY_VAULT_URL environment variable is required")
    
    TOPIC_NAME = "data-awaits-ingestion"
    
    # Initialize Key Vault reader
    try:
        kv_reader = KeyVaultReader(key_vault_url=KEY_VAULT_URL)
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Key Vault reader: {str(e)}")
        sys.exit(1)
    
    # Get Service Bus connection string
    service_bus_conn_str = os.getenv("ServiceBusConnectionString")
    if not service_bus_conn_str:
        try:
            service_bus_conn_str = kv_reader.get_secret("ServiceBusConnectionString")
            print("✅ Retrieved Service Bus connection string from Key Vault")
        except KeyVaultError as e:
            print(f"❌ ERROR: Failed to get Service Bus connection string from Key Vault: {str(e)}")
            sys.exit(1)
    
    if not service_bus_conn_str:
        print("❌ ERROR: ServiceBusConnectionString not found!")
        print("Set it in .env file, environment variable, or Key Vault")
        sys.exit(1)
    
    # Get values from Script 2 (or prompt user)
    print("\n📋 Enter values from Script 2 (or press Enter to use defaults from last run):")
    print("   (If you just ran Script 2, copy the values from its output)")
    
    training_upload_id = input("   Training Upload ID (UUID): ").strip()
    if not training_upload_id:
        print("   ⚠️  No training_upload_id provided. Please run Script 2 first or provide the UUID.")
        sys.exit(1)
    
    data_source_id = input("   Data Source ID (UUID): ").strip()
    if not data_source_id:
        print("   ⚠️  No data_source_id provided.")
        sys.exit(1)
    
    file_format = input("   File Format (default: json): ").strip() or "json"
    
    file_size_bytes_str = input("   File Size (bytes): ").strip()
    if not file_size_bytes_str:
        print("   ⚠️  No file_size_bytes provided.")
        sys.exit(1)
    try:
        file_size_bytes = int(file_size_bytes_str)
    except ValueError:
        print("   ⚠️  Invalid file_size_bytes. Must be an integer.")
        sys.exit(1)
    
    raw_file_path = input("   Raw File Path (e.g., <data_source_id>/test_ingestion_1.json): ").strip()
    if not raw_file_path:
        raw_file_path = f"{data_source_id}/test_ingestion_1.json"
    
    # Build message body
    message_data = {
        "training_upload_id": training_upload_id,
        "data_source_id": data_source_id,
        "file_format": file_format,
        "file_size_bytes": file_size_bytes,
        "raw_file_path": raw_file_path
    }
    
    print("\n📨 Message Details:")
    print(f"   Topic: {TOPIC_NAME}")
    print(f"   Training Upload ID: {training_upload_id}")
    print(f"   Data Source ID: {data_source_id}")
    print(f"   File Format: {file_format}")
    print(f"   File Size: {file_size_bytes} bytes")
    print(f"   Raw File Path: {raw_file_path}")
    print("\n   Message Body:")
    print(json.dumps(message_data, indent=2))
    
    # Create Service Bus client
    print("\n🔌 Connecting to Service Bus...")
    try:
        servicebus_client = ServiceBusClient.from_connection_string(service_bus_conn_str)
        sender = servicebus_client.get_topic_sender(topic_name=TOPIC_NAME)
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to Service Bus: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    try:
        # Create message
        message_body = json.dumps(message_data)
        message = ServiceBusMessage(message_body)
        
        # Set message properties
        message.message_id = str(uuid.uuid4())
        message.session_id = training_upload_id
        
        # Custom properties: Service Bus SQL filters read these, not the JSON body.
        if args.adf:
            message.application_properties = {
                "processing_system": "ADF",
                "training_upload_id": training_upload_id,
                "source": "test-script-ingestion-adf",
                "data_source_id": data_source_id,
            }
        else:
            message.application_properties = {
                "training_upload_id": training_upload_id,
                "source": "test-script-ingestion-v2",
                "data_source_id": data_source_id,
            }
        
        print("\n📤 Message Properties:")
        print(f"   Message ID: {message.message_id}")
        print(f"   Session ID: {training_upload_id}")
        print(f"   Custom Properties: {message.application_properties}")
        
        # Send message
        print("\n📤 Sending message...")
        sender.send_messages(message)
        print("✅ Message sent successfully!")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to send message: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        sender.close()
        servicebus_client.close()
    
    # Print next steps
    print("\n" + "=" * 60)
    print("✅ Script 3 Complete - Next Steps")
    print("=" * 60)
    print(f"1. Verify the message is in Service Bus topic '{TOPIC_NAME}'")
    print(f"2. Check that training_upload_id '{training_upload_id}' exists in")
    print("   PostgreSQL training_uploads table with status='ingesting'")
    if args.adf:
        print("3. ADF path: do **not** run run_training_ingestion.py.")
        print("   - adf-trigger-subscription → adf-pipeline-trigger Function →")
        print("     pipeline pipeline-training-data-ingestion (blob → bronze).")
        print("4. Azure Portal → Data Factory → Monitor → pipeline runs; confirm success.")
        print("5. When bronze + data-ingested are ready, continue schema-mapping / downstream.")
    else:
        print("3. Run the ingestion script: python scripts/run_training_ingestion.py")
        print("4. The script will:")
        print("   - Peek all messages and find matching training_upload_ids")
        print("   - Process the file: copy to bronze, verify checksum, update DB")
        print("   - Publish success message to data-ingested topic")
    print("=" * 60)


if __name__ == "__main__":
    main()
