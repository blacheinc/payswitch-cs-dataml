"""
Test script to send a Service Bus message for production ADF pipeline testing
Usage: python test_production_pipeline.py --training-upload-id YOUR_UUID --data-source-id YOUR_UUID

Requires environment variable ServiceBusConnectionString (or SERVICEBUS_CONNECTION_STRING).
Do not commit connection strings; copy from Key Vault or local.settings.json for the session only.
"""

import argparse
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


def send_production_test_message(training_upload_id, data_source_id, file_format="json", file_size_bytes=1000, raw_file_path=None):
    """
    Send a test message for the production ADF pipeline
    
    Args:
        training_upload_id: UUID of the training_uploads record (must exist in DB with status='ingesting')
        data_source_id: UUID of the data source (must exist in data_sources table)
        file_format: File format (default: 'json')
        file_size_bytes: File size in bytes (default: 1000)
        raw_file_path: Path to file in blob storage (default: {data_source_id}/test_file.{file_format})
    """
    
    if raw_file_path is None:
        raw_file_path = f"{data_source_id}/test_file.{file_format}"
    
    # Test message data
    message_body = {
        "training_upload_id": training_upload_id,
        "data_source_id": data_source_id,
        "file_format": file_format,
        "file_size_bytes": file_size_bytes,
        "raw_file_path": raw_file_path
    }
    
    connection_string = _require_service_bus_connection_string()
    client = ServiceBusClient.from_connection_string(connection_string)
    sender = client.get_topic_sender(topic_name=TOPIC_NAME)
    
    try:
        # Create message with processing_system in custom properties
        # This routes to adf-trigger-subscription
        message = ServiceBusMessage(
            body=json.dumps(message_body),
            application_properties={
                "processing_system": "ADF",
                "training_upload_id": training_upload_id
            }
        )
        
        # Send message
        sender.send_messages(message)
        print("✅ Test message sent successfully!")
        print(f"\n📋 Message Details:")
        print(f"   Topic: {TOPIC_NAME}")
        print(f"   Message body:")
        print(json.dumps(message_body, indent=4))
        print(f"\n   Custom properties (application_properties):")
        print(f"     - processing_system = 'ADF'")
        print(f"     - training_upload_id = '{training_upload_id}'")
        print(f"\n📝 Next Steps:")
        print(f"   1. Check Azure Function logs (should trigger ADF pipeline)")
        print(f"   2. Check ADF pipeline runs in Azure Portal")
        print(f"   3. Verify database updates (training_uploads.status = 'ingested')")
        print(f"   4. Check bronze_ingestion_log table for new record")
        print(f"   5. Verify file in bronze layer")
        print(f"   6. Check success message in 'data-ingested' topic")
        
    except Exception as e:
        print(f"❌ Failed to send message: {str(e)}")
        sys.exit(1)
    finally:
        sender.close()
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Send test Service Bus message for production ADF pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set connection string for this shell (PowerShell), then run:
  #   $env:ServiceBusConnectionString = "<from Key Vault or local.settings.json>"
  # Basic usage (uses defaults for file_format, file_size_bytes, raw_file_path)
  python test_production_pipeline.py --training-upload-id abc-123 --data-source-id def-456
  
  # Full options
  python test_production_pipeline.py \\
    --training-upload-id abc-123 \\
    --data-source-id def-456 \\
    --file-format json \\
    --file-size-bytes 5000 \\
    --raw-file-path "def-456/my_test_file.json"
        """
    )
    
    parser.add_argument(
        "--training-upload-id",
        required=True,
        help="UUID of training_uploads record (must exist in DB with status='ingesting')"
    )
    parser.add_argument(
        "--data-source-id",
        required=True,
        help="UUID of data source (must exist in data_sources table)"
    )
    parser.add_argument(
        "--file-format",
        default="json",
        help="File format (default: json)"
    )
    parser.add_argument(
        "--file-size-bytes",
        type=int,
        default=1000,
        help="File size in bytes (default: 1000)"
    )
    parser.add_argument(
        "--raw-file-path",
        default=None,
        help="Path to file in blob storage (default: {data_source_id}/test_file.{file_format})"
    )
    
    args = parser.parse_args()
    
    send_production_test_message(
        training_upload_id=args.training_upload_id,
        data_source_id=args.data_source_id,
        file_format=args.file_format,
        file_size_bytes=args.file_size_bytes,
        raw_file_path=args.raw_file_path
    )
