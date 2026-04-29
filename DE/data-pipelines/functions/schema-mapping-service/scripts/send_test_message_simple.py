"""
Simple script to send test message using connection string from local.settings.json
No Key Vault needed - uses direct connection string
"""

import json
import uuid
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from azure.servicebus import ServiceBusClient, ServiceBusMessage

# Read connection string from local.settings.json
local_settings_path = Path(__file__).parent.parent / "local.settings.json"
with open(local_settings_path, 'r') as f:
    local_settings = json.load(f)

connection_string = local_settings["Values"]["ServiceBusConnectionString"]

# Create message payload
training_upload_id = str(uuid.uuid4())
message_data = {
    "training_upload_id": training_upload_id,
    "bank_id": "bank-digital-001",
    "bronze_blob_path": "bronze/training/bank-digital-001/2026-03-04/test_data_with_pii.csv"
}

print("="*60)
print("Sending Test Message to Service Bus")
print("="*60)
print(f"Training Upload ID: {training_upload_id}")
print(f"Bank ID: {message_data['bank_id']}")
print(f"Bronze Blob Path: {message_data['bronze_blob_path']}")
print()

# Create Service Bus client
print("Connecting to Service Bus...")
client = ServiceBusClient.from_connection_string(connection_string)
sender = client.get_topic_sender("data-ingested")

try:
    # Create message
    message_body = json.dumps(message_data)
    message = ServiceBusMessage(message_body)
    
    # Set message properties
    message.message_id = str(uuid.uuid4())
    message.session_id = training_upload_id
    message.application_properties = {
        "subscription": "start-transformation",
        "source": "test-script"
    }
    
    print(f"Message ID: {message.message_id}")
    print(f"Session ID: {training_upload_id}")
    print()
    
    # Send message
    print("Sending message...")
    sender.send_messages(message)
    print("[OK] Message sent successfully!")
    print()
    print("="*60)
    print("Message Details")
    print("="*60)
    print(f"Topic: data-ingested")
    print(f"Subscription: start-transformation")
    print(f"Training Upload ID: {training_upload_id}")
    print(f"Message Body: {message_body}")
    print()
    print("Check the function host window for processing logs.")
    
except Exception as e:
    print(f"[ERROR] Failed to send message: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    sender.close()
    client.close()
