"""
Script to reset a training_upload record status to 'ingesting'
Useful for re-testing ingestion after a record has been processed
"""

import os
import sys
from pathlib import Path

# Add paths
CURRENT_DIR = Path(__file__).parent
TRAINING_ROOT = CURRENT_DIR.parent
if str(TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_ROOT))

# Load environment
try:
    from dotenv import load_dotenv
    env_path = TRAINING_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Try to load from local.settings.json
import json
local_settings_path = TRAINING_ROOT / "local.settings.json"
if local_settings_path.exists():
    try:
        with open(local_settings_path, 'r') as f:
            local_settings = json.load(f)
            values = local_settings.get("Values", {})
            for key, value in values.items():
                if key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"Warning: Could not load local.settings.json: {e}")

from utils.training_key_vault_reader import TrainingKeyVaultReader
from utils.training_postgres_client import TrainingPostgresClient
from sqlalchemy import text

def main():
    print("=" * 60)
    print("Reset Training Upload Status to 'ingesting'")
    print("=" * 60)
    
    # Get training_upload_id
    if len(sys.argv) > 1:
        training_upload_id = sys.argv[1].strip()
    else:
        training_upload_id = input("\nEnter Training Upload ID (UUID): ").strip()
    
    if not training_upload_id:
        print("ERROR: Training Upload ID is required")
        sys.exit(1)
    
    # Get Key Vault URL
    KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
    if not KEY_VAULT_URL:
        print("ERROR: KEY_VAULT_URL environment variable not set")
        sys.exit(1)
    
    try:
        # Initialize clients
        kv_reader = TrainingKeyVaultReader(key_vault_url=KEY_VAULT_URL)
        postgres_client = TrainingPostgresClient(
            key_vault_url=KEY_VAULT_URL,
            key_vault_reader=kv_reader
        )
        
        # Update status
        print(f"\nUpdating status to 'ingesting' for: {training_upload_id}")
        
        update_query = text("""
            UPDATE training_uploads 
            SET status = 'ingesting', 
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :training_upload_id
            RETURNING id, status, file_name, raw_file_path
        """)
        
        with postgres_client.get_session() as session:
            result = session.execute(
                update_query,
                {"training_upload_id": training_upload_id}
            )
            row = result.fetchone()
            session.commit()
            
            if row:
                print("\n✅ Status updated successfully!")
                print(f"   ID: {row[0]}")
                print(f"   Status: {row[1]}")
                print(f"   File Name: {row[2]}")
                print(f"   Raw File Path: {row[3]}")
            else:
                print(f"\n⚠️  No record found with ID: {training_upload_id}")
                print("   Please verify the training_upload_id is correct")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
