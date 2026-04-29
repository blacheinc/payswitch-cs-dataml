"""
Service Bus Publishing Test Script
Simple script to test Service Bus message publishing and verify filters work correctly
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.service_bus_writer import ServiceBusWriter, BackendStatus, InternalStatus
from utils.service_bus_reader import ServiceBusReader
from utils.key_vault_reader import KeyVaultReader


def test_internal_topic_publishing(key_vault_url: str):
    """Test publishing to internal topic (schema-mapping-service)"""
    print("\n" + "="*60)
    print("Testing Internal Topic (schema-mapping-service)")
    print("="*60)
    
    writer = ServiceBusWriter(key_vault_url=key_vault_url)
    reader = ServiceBusReader(key_vault_url=key_vault_url)
    
    test_upload_id = f"test-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    test_bank_id = "test-bank-001"
    
    print(f"\nTest Upload ID: {test_upload_id}")
    print(f"Test Bank ID: {test_bank_id}")
    
    # Test 1: System Starting
    print("\n1. Publishing System Starting message...")
    writer.publish_system_starting(
        upload_id=test_upload_id,
        bank_id=test_bank_id,
        system_name="System 0: File Introspection"
    )
    print("   ✓ Published")
    
    # Test 2: System Complete
    print("\n2. Publishing System Complete message...")
    writer.publish_system_complete(
        upload_id=test_upload_id,
        bank_id=test_bank_id,
        system_name="System 1: Schema Detection",
        status=InternalStatus.SCHEMA_DETECTED,
        result={
            "format": "csv",
            "column_count": 25,
            "row_count": 500,
            "confidence": 0.95
        }
    )
    print("   ✓ Published")
    
    # Test 3: System Failed
    print("\n3. Publishing System Failed message...")
    writer.publish_system_failed(
        training_upload_id=test_upload_id,
        bank_id=test_bank_id,
        system_name="System 2: Data Sampling",
        error={
            "message": "Test error for verification",
            "type": "ValueError",
            "stack_trace": "Traceback (most recent call last):\n  ...",
            "bronze_path": "test/path.csv"
        }
    )
    print("   ✓ Published")
    
    # Wait for messages to be processed
    print("\n4. Waiting 3 seconds for messages to be processed...")
    import time
    time.sleep(3)
    
    # Verify messages in correct subscriptions
    print("\n5. Verifying messages in subscriptions...")
    
    # Check introspection-complete
    print("\n   Checking 'introspection-complete' subscription...")
    messages = reader.peek_messages(
        topic_name="schema-mapping-service",
        subscription_name="introspection-complete",
        max_messages=5
    )
    found = any(msg.get('upload_id') == test_upload_id for msg in messages)
    print(f"   {'✓' if found else '✗'} Message found: {found}")
    
    # Check schema-detected
    print("\n   Checking 'schema-detected' subscription...")
    messages = reader.peek_messages(
        topic_name="schema-mapping-service",
        subscription_name="schema-detected",
        max_messages=5
    )
    found = any(msg.get('upload_id') == test_upload_id for msg in messages)
    print(f"   {'✓' if found else '✗'} Message found: {found}")
    
    # Check failed
    print("\n   Checking 'failed' subscription...")
    messages = reader.peek_messages(
        topic_name="schema-mapping-service",
        subscription_name="failed",
        max_messages=5
    )
    found = any(msg.get('upload_id') == test_upload_id for msg in messages)
    print(f"   {'✓' if found else '✗'} Message found: {found}")
    
    # Verify filter isolation (message should NOT be in wrong subscription)
    print("\n6. Verifying filter isolation...")
    print("\n   Checking 'sampling-complete' subscription (should be empty)...")
    messages = reader.peek_messages(
        topic_name="schema-mapping-service",
        subscription_name="sampling-complete",
        max_messages=5
    )
    found = any(msg.get('upload_id') == test_upload_id for msg in messages)
    print(f"   {'✗ FILTER BROKEN!' if found else '✓ Filter working (message not in wrong subscription)'}")
    
    print("\n" + "="*60)
    print("Internal Topic Test Complete")
    print("="*60)


def test_backend_topic_publishing(key_vault_url: str):
    """Test publishing to backend topic (data-ingested)"""
    print("\n" + "="*60)
    print("Testing Backend Topic (data-ingested)")
    print("="*60)
    
    writer = ServiceBusWriter(key_vault_url=key_vault_url)
    reader = ServiceBusReader(key_vault_url=key_vault_url)
    
    test_upload_id = f"test-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    
    print(f"\nTest Upload ID: {test_upload_id}")
    
    # Test 1: Quality Report
    print("\n1. Publishing Quality Report message...")
    quality_report = {
        "file_quality": {
            "file_size_bytes": 1234567,
            "encoding": "utf-8",
            "format": "csv"
        },
        "schema_quality": {
            "format": "csv",
            "column_count": 25,
            "format_detection_confidence": 0.95
        },
        "data_quality": {
            "overall_completeness_score": 0.87,
            "column_completeness": {
                "column1": 95.5,
                "column2": 78.2
            }
        },
        "pii_quality": {
            "pii_fields_detected": 5,
            "anonymization_applied": True,
            "pii_detection_confidence": 0.92
        },
        "quality_score": 0.85
    }
    
    writer.publish_quality_report(
        training_upload_id=test_upload_id,
        quality_report=quality_report,
        quality_score=0.85
    )
    print("   ✓ Published")
    
    # Test 2: Transformed
    print("\n2. Publishing Transformed message...")
    features_mapped = {
        "count": 18,
        "mappings": {
            "national_id": {
                "source_fields": ["customer_id", "id_number"],
                "transformation": "concatenated"
            },
            "monthly_income": {
                "source_fields": ["salary"],
                "transformation": "direct_mapping"
            }
        }
    }
    
    writer.publish_transformed(
        training_upload_id=test_upload_id,
        transformed_file_path="gold/training/test-bank-001/2026-02-24/test-upload.parquet",
        features_mapped=features_mapped,
        schema_template_id="uuid-12345-67890"
    )
    print("   ✓ Published")
    
    # Test 3: Backend Error
    print("\n3. Publishing Backend Error message...")
    writer.publish_backend_error(
        training_upload_id=test_upload_id,
        error_type="ValueError",
        error_message="File format could not be detected",
        system_name="System 1: Schema Detection",
        stack_trace="Traceback..."
    )
    print("   ✓ Published")
    
    # Wait for messages to be processed
    print("\n4. Waiting 3 seconds for messages to be processed...")
    import time
    time.sleep(3)
    
    # Verify messages in correct subscriptions
    print("\n5. Verifying messages in subscriptions...")
    
    # Check quality_report
    print("\n   Checking 'quality_report' subscription...")
    messages = reader.peek_messages(
        topic_name="data-ingested",
        subscription_name="quality_report",
        max_messages=5
    )
    found = any(msg.get('training_upload_id') == test_upload_id for msg in messages)
    print(f"   {'✓' if found else '✗'} Message found: {found}")
    if found:
        msg = next(msg for msg in messages if msg.get('training_upload_id') == test_upload_id)
        print(f"      Status: {msg.get('status')}")
        print(f"      Quality Score: {msg.get('quality_score')}")
    
    # Check transformed
    print("\n   Checking 'transformed' subscription...")
    messages = reader.peek_messages(
        topic_name="data-ingested",
        subscription_name="transformed",
        max_messages=5
    )
    found = any(msg.get('training_upload_id') == test_upload_id for msg in messages)
    print(f"   {'✓' if found else '✗'} Message found: {found}")
    if found:
        msg = next(msg for msg in messages if msg.get('training_upload_id') == test_upload_id)
        print(f"      Status: {msg.get('status')}")
        print(f"      Features Mapped: {msg.get('features_mapped', {}).get('count')}")
    
    # Check error
    print("\n   Checking 'error' subscription...")
    messages = reader.peek_messages(
        topic_name="data-ingested",
        subscription_name="error",
        max_messages=5
    )
    found = any(msg.get('training_upload_id') == test_upload_id for msg in messages)
    print(f"   {'✓' if found else '✗'} Message found: {found}")
    if found:
        msg = next(msg for msg in messages if msg.get('training_upload_id') == test_upload_id)
        print(f"      Status: {msg.get('status')}")
        print(f"      Error Code: {msg.get('error_report', {}).get('error_code')}")
        print(f"      User Message: {msg.get('error_report', {}).get('user_message', '')[:50]}...")
    
    # Verify filter isolation
    print("\n6. Verifying filter isolation...")
    print("\n   Checking 'quality_report' subscription for transformed message (should be empty)...")
    messages = reader.peek_messages(
        topic_name="data-ingested",
        subscription_name="quality_report",
        max_messages=10
    )
    # Check if transformed message is NOT in quality_report
    transformed_found = any(
        msg.get('training_upload_id') == test_upload_id and 
        msg.get('status') == 'TRANSFORMED'
        for msg in messages
    )
    print(f"   {'✗ FILTER BROKEN!' if transformed_found else '✓ Filter working (transformed message not in quality_report)'}")
    
    print("\n" + "="*60)
    print("Backend Topic Test Complete")
    print("="*60)


def main():
    """Main test function"""
    print("\n" + "="*60)
    print("Service Bus Publishing Test Script")
    print("="*60)
    
    # Get Key Vault URL
    key_vault_url = os.getenv('KEY_VAULT_URL')
    if not key_vault_url:
        print("\n❌ ERROR: KEY_VAULT_URL environment variable not set")
        print("   Please set it before running this script:")
        print("   export KEY_VAULT_URL='https://your-vault.vault.azure.net/'")
        return
    
    print(f"\nKey Vault URL: {key_vault_url}")
    
    try:
        # Test internal topic
        test_internal_topic_publishing(key_vault_url)
        
        # Test backend topic
        test_backend_topic_publishing(key_vault_url)
        
        print("\n" + "="*60)
        print("✅ All Tests Complete!")
        print("="*60)
        print("\nNext Steps:")
        print("1. Check Azure Portal to verify messages in subscriptions")
        print("2. Verify subscription filters are working correctly")
        print("3. Check that messages only appear in expected subscriptions")
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
