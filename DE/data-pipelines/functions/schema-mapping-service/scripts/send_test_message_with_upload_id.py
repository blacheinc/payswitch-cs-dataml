"""
Quick script to send a test message with a specific upload_id
Usage: python scripts/send_test_message_with_upload_id.py <upload_id> [bank_id] [bronze_path]
"""

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.send_test_message import send_test_message

if __name__ == "__main__":
    # Get upload_id from command line or use default
    if len(sys.argv) > 1:
        upload_id = sys.argv[1]
    else:
        upload_id = "00895565-8385-4756-8a4b-532a46e5c841"
    
    # Get bank_id from command line or use default
    bank_id = sys.argv[2] if len(sys.argv) > 2 else "bank-digital-001"
    
    # Get bronze_path from command line or use default
    if len(sys.argv) > 3:
        bronze_path = sys.argv[3]
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        bronze_path = f"bronze/training/{bank_id}/{date_str}/test_data_with_pii.csv"
    
    KEY_VAULT_URL = os.getenv(
        "KEY_VAULT_URL",
        "https://blachekvruhclai6km.vault.azure.net/"
    )
    
    print(f"Using Upload ID: {upload_id}")
    print(f"Using Bank ID: {bank_id}")
    print(f"Using Bronze Path: {bronze_path}")
    print()
    
    try:
        send_test_message(
            key_vault_url=KEY_VAULT_URL,
            training_upload_id=upload_id,
            bank_id=bank_id,
            bronze_blob_path=bronze_path
        )
    except Exception as e:
        print(f"\n[ERROR] Failed to send message: {str(e)}")
        sys.exit(1)
