"""
Test script to send a Service Bus message for ADF pipeline trigger testing

Requires environment variable ServiceBusConnectionString (or SERVICEBUS_CONNECTION_STRING).
"""

import json
import os
import sys

from azure.servicebus import ServiceBusClient, ServiceBusMessage

TOPIC_NAME = "data-awaits-ingestion"


def _require_service_bus_connection_string() -> str:
    conn = (
        os.environ.get("ServiceBusConnectionString")
        or os.environ.get("SERVICEBUS_CONNECTION_STRING")
        or ""
    ).strip()
    if not conn:
        print("ERROR: Service Bus connection string not set.", file=sys.stderr)
        print(
            "  Set ServiceBusConnectionString or SERVICEBUS_CONNECTION_STRING in the environment.",
            file=sys.stderr,
        )
        sys.exit(1)
    return conn


def send_adf_test_message():
    """Send a test message with processing_system = 'ADF'"""
    
    # Test message data
    message_body = {
        "training_upload_id": "test-adf-trigger-001",
        "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
        "file_format": "json",
        "file_size_bytes": 1000,
        "raw_file_path": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf/test_adf_trigger.json"
    }
    
    connection_string = _require_service_bus_connection_string()
    client = ServiceBusClient.from_connection_string(connection_string)
    sender = client.get_topic_sender(topic_name=TOPIC_NAME)

    try:
        # Create message with processing_system and training_upload_id in custom properties
        # This allows Service Bus filters to check both values
        message = ServiceBusMessage(
            body=json.dumps(message_body),
            application_properties={
                "processing_system": "ADF",
                "training_upload_id": message_body["training_upload_id"]  # Add to custom properties for filtering
            }
        )
        
        # Send message
        sender.send_messages(message)
        print("✅ Test message sent successfully!")
        print(f"   Topic: {TOPIC_NAME}")
        print(f"   Message body: {json.dumps(message_body, indent=2)}")
        print(f"   Custom properties (application_properties):")
        print(f"     - processing_system = 'ADF'")
        print(f"     - training_upload_id = '{message_body['training_upload_id']}'")
        print(f"\n   ⚠️  IMPORTANT: Both values are in application_properties (custom properties),")
        print(f"      NOT in the message body. This is required for SQL filters to work!")
        print(f"\n   This message should be received by 'adf-trigger-subscription'")
        print(f"   and should NOT be received by 'temp-peek-subscription'")
        
    except Exception as e:
        print(f"❌ Failed to send message: {str(e)}")
        sys.exit(1)
    finally:
        sender.close()
        client.close()


def send_azure_function_test_message():
    """Send a test message with processing_system = 'Azure Function'"""
    
    # Test message data
    message_body = {
        "training_upload_id": "test-af-trigger-001",
        "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
        "file_format": "json",
        "file_size_bytes": 1000,
        "raw_file_path": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf/test_af_trigger.json"
    }
    
    connection_string = _require_service_bus_connection_string()
    client = ServiceBusClient.from_connection_string(connection_string)
    sender = client.get_topic_sender(topic_name=TOPIC_NAME)

    try:
        # Create message with processing_system and training_upload_id in custom properties
        # This allows Service Bus filters to check both values
        message = ServiceBusMessage(
            body=json.dumps(message_body),
            application_properties={
                "processing_system": "Azure Function",
                "training_upload_id": message_body["training_upload_id"]  # Add to custom properties for filtering
            }
        )
        
        # Send message
        sender.send_messages(message)
        print("✅ Test message sent successfully!")
        print(f"   Topic: {TOPIC_NAME}")
        print(f"   Message body: {json.dumps(message_body, indent=2)}")
        print(f"   Custom properties (application_properties):")
        print(f"     - processing_system = 'Azure Function'")
        print(f"     - training_upload_id = '{message_body['training_upload_id']}'")
        print(f"\n   ⚠️  IMPORTANT: Both values are in application_properties (custom properties),")
        print(f"      NOT in the message body. This is required for SQL filters to work!")
        print(f"\n   This message should be received by 'temp-peek-subscription'")
        print(f"   and should NOT be received by 'adf-trigger-subscription'")
        
    except Exception as e:
        print(f"❌ Failed to send message: {str(e)}")
        sys.exit(1)
    finally:
        sender.close()
        client.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Send test Service Bus message")
    parser.add_argument(
        "--type",
        choices=["adf", "azure-function", "both"],
        default="adf",
        help="Type of message to send (default: adf)"
    )
    
    args = parser.parse_args()
    
    if args.type == "adf":
        send_adf_test_message()
    elif args.type == "azure-function":
        send_azure_function_test_message()
    elif args.type == "both":
        print("Sending ADF test message...")
        send_adf_test_message()
        print("\n" + "="*60 + "\n")
        print("Sending Azure Function test message...")
        send_azure_function_test_message()
