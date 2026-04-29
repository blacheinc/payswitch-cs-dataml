"""
Diagnostic script to check training_upload status in database
"""
import os
import sys
import json
from pathlib import Path

# Add paths
CURRENT_DIR = Path(__file__).parent
TRAINING_ROOT = CURRENT_DIR.parent
if str(TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_ROOT))

# Try to load from .env file
try:
    from dotenv import load_dotenv
    env_path = TRAINING_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Try to load from local.settings.json (Azure Functions local settings)
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

# Get Key Vault URL
KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
if not KEY_VAULT_URL:
    print("ERROR: KEY_VAULT_URL environment variable not set")
    print("Please set it in local.settings.json or .env file")
    sys.exit(1)

# Get training_upload_id from command line or user input
if len(sys.argv) > 1:
    training_upload_id = sys.argv[1].strip()
else:
    try:
        training_upload_id = input("Enter training_upload_id to check: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nERROR: training_upload_id is required")
        print("Usage: python check_training_upload_status.py <training_upload_id>")
        sys.exit(1)

if not training_upload_id:
    print("ERROR: training_upload_id is required")
    print("Usage: python check_training_upload_status.py <training_upload_id>")
    sys.exit(1)

try:
    # Initialize clients
    kv_reader = TrainingKeyVaultReader(key_vault_url=KEY_VAULT_URL)
    postgres_client = TrainingPostgresClient(
        key_vault_url=KEY_VAULT_URL,
        key_vault_reader=kv_reader
    )
    
    # Query database
    query = """
        SELECT 
            id,
            status,
            data_source_id,
            file_name,
            raw_file_path,
            created_at,
            updated_at
        FROM training_uploads
        WHERE id::text = :training_upload_id
    """
    
    with postgres_client.get_session() as session:
        result = session.execute(
            text(query),
            {"training_upload_id": training_upload_id}
        )
        row = result.fetchone()
        
        if not row:
            print(f"\n[ERROR] No record found with id={training_upload_id}")
        else:
            print(f"\n[SUCCESS] Record found:")
            print(f"  ID: {row[0]}")
            status_ok = row[1] == 'ingesting'
            print(f"  Status: {row[1]} {'[NOT ingesting!]' if not status_ok else '[OK]'}")
            print(f"  Data Source ID: {row[2]}")
            print(f"  File Name: {row[3]}")
            print(f"  Raw File Path: {row[4]}")
            print(f"  Created At: {row[5]}")
            print(f"  Updated At: {row[6]}")
            
            if not status_ok:
                print(f"\n[WARNING] Status is '{row[1]}', not 'ingesting'!")
                print("   The function will skip this record.")
                print(f"   To fix: UPDATE training_uploads SET status='ingesting' WHERE id='{training_upload_id}';")
    
    postgres_client.close()
    kv_reader.close()
    
except Exception as e:
    print(f"\n[ERROR] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
