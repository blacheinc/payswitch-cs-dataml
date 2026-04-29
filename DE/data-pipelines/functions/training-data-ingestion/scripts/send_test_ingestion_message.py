"""
Send a test message to data-awaits-ingestion topic for training data ingestion
This message will be picked up by the run_training_ingestion.py script
"""

import json
import os
import sys
import uuid
from pathlib import Path

# Try to import dotenv, but make it optional
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False
    print("⚠️  python-dotenv not installed. Will use environment variables only.")

from azure.servicebus import ServiceBusClient, ServiceBusMessage

# Add parent directories to path (same pattern as run_training_ingestion.py)
CURRENT_DIR = Path(__file__).parent
TRAINING_INGESTION_ROOT = CURRENT_DIR.parent
FUNCTION_ROOT = TRAINING_INGESTION_ROOT.parent
SCHEMA_MAPPING_ROOT = FUNCTION_ROOT / "schema-mapping-service"

# Add paths for imports
if str(SCHEMA_MAPPING_ROOT) not in sys.path:
    sys.path.insert(0, str(SCHEMA_MAPPING_ROOT))
if str(TRAINING_INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_INGESTION_ROOT))

# Load environment variables
if HAS_DOTENV:
    env_path = TRAINING_INGESTION_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # Try parent .env
        parent_env = SCHEMA_MAPPING_ROOT / ".env"
        if parent_env.exists():
            load_dotenv(parent_env)
else:
    print("ℹ️  Skipping .env file loading (python-dotenv not available)")

# Import KeyVaultReader using same pattern as run_training_ingestion.py
import importlib.util

kv_reader_path = SCHEMA_MAPPING_ROOT / "utils" / "key_vault_reader.py"
if not kv_reader_path.exists():
    print(f"❌ ERROR: KeyVaultReader not found at: {kv_reader_path}")
    sys.exit(1)

kv_spec = importlib.util.spec_from_file_location("key_vault_reader", str(kv_reader_path))
kv_module = importlib.util.module_from_spec(kv_spec)
kv_spec.loader.exec_module(kv_module)
KeyVaultReader = kv_module.KeyVaultReader
KeyVaultError = kv_module.KeyVaultError

# Get Service Bus connection string (try env first, then Key Vault)
connection_string = os.getenv("ServiceBusConnectionString")
if not connection_string:
    # Try Key Vault
    key_vault_url = os.getenv("KEY_VAULT_URL")
    if not key_vault_url:
        print("❌ ERROR: KEY_VAULT_URL not found in environment")
        print("Please set KEY_VAULT_URL in .env file or as environment variable")
        sys.exit(1)
    
    try:
        print(f"🔑 Loading Service Bus connection string from Key Vault: {key_vault_url}")
        kv_reader = KeyVaultReader(key_vault_url=key_vault_url)
        connection_string = kv_reader.get_secret("ServiceBusConnectionString")
        print("✅ Retrieved connection string from Key Vault")
    except KeyVaultError as e:
        print(f"❌ ERROR: Failed to get Service Bus connection string from Key Vault: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: Unexpected error accessing Key Vault: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if not connection_string:
    print("❌ ERROR: ServiceBusConnectionString not found!")
    print("Set it in .env file, environment variable, or Key Vault")
    sys.exit(1)

# Topic name
TOPIC_NAME = "data-awaits-ingestion"

# Hardcoded values matching the database record
# These must match an existing record in training_uploads table
training_upload_id = "ea9e194b-0a3b-420d-9b6e-0e58a8a91843"
data_source_id = "b4ed5120-65f4-46c5-b687-dc895a1d6bbf"
file_format = "json"
file_size_bytes = 667146
raw_file_path = "b4ed5120-65f4-46c5-b687-dc895a1d6bbf/dataset1_digital_bank.json"

# Message body - includes all fields to match database record
message_data = {
    "training_upload_id": training_upload_id,
    "data_source_id": data_source_id,
    "file_format": file_format,
    "file_size_bytes": file_size_bytes,
    "raw_file_path": raw_file_path
}

print("=" * 60)
print("Sending Test Message to data-awaits-ingestion Topic")
print("=" * 60)
print(f"Topic: {TOPIC_NAME}")
print(f"Training Upload ID: {training_upload_id}")
print(f"Data Source ID: {data_source_id}")
print(f"File Format: {file_format}")
print(f"File Size: {file_size_bytes} bytes")
print(f"Raw File Path: {raw_file_path}")
print()
print("Message Body:")
print(json.dumps(message_data, indent=2))
print()

# Create Service Bus client
print("Connecting to Service Bus...")
servicebus_client = ServiceBusClient.from_connection_string(connection_string)
sender = servicebus_client.get_topic_sender(topic_name=TOPIC_NAME)

try:
    # Create message
    message_body = json.dumps(message_data)
    message = ServiceBusMessage(message_body)
    
    # Set message properties
    message.message_id = str(uuid.uuid4())
    message.session_id = training_upload_id
    
    # IMPORTANT: Set custom properties for SQL filter
    # The subscription filter is: training_upload_id IS NOT NULL
    message.application_properties = {
        "training_upload_id": training_upload_id,  # Required for SQL filter
        "source": "test-script-ingestion",
        "data_source_id": data_source_id
    }
    
    print("Message Properties:")
    print(f"  Message ID: {message.message_id}")
    print(f"  Session ID: {training_upload_id}")
    print(f"  Custom Properties: {message.application_properties}")
    print()
    
    # Send message
    print("Sending message...")
    sender.send_messages(message)
    print("✅ Message sent successfully!")
    print()
    print("=" * 60)
    print("Next Steps")
    print("=" * 60)
    print(f"1. Verify the message is in Service Bus topic '{TOPIC_NAME}'")
    print(f"2. Check that training_upload_id '{training_upload_id}' exists in")
    print("   PostgreSQL training_uploads table with status='ingesting'")
    print(f"3. Run the ingestion script: python scripts/run_training_ingestion.py")
    print("4. The script will:")
    print("   - Check if the training_upload_id exists in the database")
    print("   - If found, process the ingestion")
    print("   - If not found, complete the message without processing")
    print()
    print("⚠️  NOTE: The ingestion processor will look up file details")
    print("   from the training_uploads table. If the record doesn't exist,")
    print("   the message will be completed without error.")
    
except Exception as e:
    print(f"❌ ERROR: Failed to send message: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    sender.close()
    servicebus_client.close()
