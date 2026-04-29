"""
Check if function published status messages to Service Bus topics
This helps verify if the function ran successfully
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.service_bus_reader import ServiceBusReader
from utils.key_vault_reader import KeyVaultReader

def check_function_output():
    """Check Service Bus topics for status messages"""
    kv_url = "https://blachekvruhclai6km.vault.azure.net/"
    
    print("="*60)
    print("Checking Function Output (Service Bus Messages)")
    print("="*60)
    print()
    
    with KeyVaultReader(key_vault_url=kv_url) as kv:
        reader = ServiceBusReader(kv_url)
    
    # Check internal topic subscriptions
    print("1. Internal Topic (schema-mapping-service):")
    print("-" * 60)
    internal_subs = [
        "introspection-complete",
        "schema-detected", 
        "sampling-complete",
        "analysis-complete",
        "anonymization-complete",
        "failed"
    ]
    
    for sub in internal_subs:
        try:
            messages = reader.peek_messages("schema-mapping-service", sub, max_messages=5)
            if messages:
                print(f"  [{sub}]: {len(messages)} message(s) found")
                # Show latest message
                latest = messages[0]
                if isinstance(latest, dict):
                    status = latest.get("status", "unknown")
                    upload_id = latest.get("upload_id") or latest.get("training_upload_id", "unknown")
                    print(f"    Latest: status={status}, upload_id={upload_id[:20]}...")
            else:
                print(f"  [{sub}]: No messages")
        except Exception as e:
            print(f"  [{sub}]: Error - {str(e)}")
    
    print()
    
    # Check backend topic subscriptions
    print("2. Backend Topic (data-ingested):")
    print("-" * 60)
    backend_subs = ["quality_report", "transformed", "error"]
    
    for sub in backend_subs:
        try:
            messages = reader.peek_messages("data-ingested", sub, max_messages=5)
            if messages:
                print(f"  [{sub}]: {len(messages)} message(s) found")
                latest = messages[0]
                if isinstance(latest, dict):
                    status = latest.get("status", "unknown")
                    upload_id = latest.get("training_upload_id", "unknown")
                    print(f"    Latest: status={status}, upload_id={upload_id[:20]}...")
            else:
                print(f"  [{sub}]: No messages")
        except Exception as e:
            print(f"  [{sub}]: Error - {str(e)}")
    
    print()
    print("="*60)
    print("Summary:")
    print("  - If you see messages in 'failed' or 'error': Function encountered an error")
    print("  - If you see messages in other subscriptions: Function is progressing")
    print("  - If no messages anywhere: Function may still be running or failed silently")
    print("="*60)

if __name__ == "__main__":
    try:
        check_function_output()
    except Exception as e:
        print(f"\n[ERROR] Failed to check output: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
