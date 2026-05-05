"""
Script 2: Insert Record into training_uploads Table
Inserts a new record with status='ingesting' for the test file
"""

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
)
from utils.training_postgres_client import (
    TrainingPostgresClient as PostgresClient,
)

from sqlalchemy import text


def main():
    """Main function to insert training upload record"""
    print("=" * 60)
    print("Script 2: Insert Record into training_uploads Table")
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
    
    # Initialize Key Vault reader
    try:
        kv_reader = KeyVaultReader(key_vault_url=KEY_VAULT_URL)
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Key Vault reader: {str(e)}")
        sys.exit(1)
    
    # Get values from Script 1 (or prompt user)
    print("\n📋 Enter values from Script 1 (or press Enter to use defaults from last run):")
    print("   (If you just ran Script 1, copy the values from its output)")
    
    data_source_id = input("   Data Source ID (UUID): ").strip()
    if not data_source_id:
        print("   ⚠️  No data_source_id provided. Please run Script 1 first or provide the UUID.")
        sys.exit(1)
    
    file_name = input("   File Name (default: test_ingestion_1.json): ").strip() or "test_ingestion_1.json"
    raw_file_path = input("   Raw File Path (e.g., <data_source_id>/test_ingestion_1.json): ").strip()
    if not raw_file_path:
        raw_file_path = f"{data_source_id}/{file_name}"
    
    file_size_bytes_str = input("   File Size (bytes): ").strip()
    if not file_size_bytes_str:
        print("   ⚠️  No file_size_bytes provided.")
        sys.exit(1)
    try:
        file_size_bytes = int(file_size_bytes_str)
    except ValueError:
        print("   ⚠️  Invalid file_size_bytes. Must be an integer.")
        sys.exit(1)
    
    record_count_str = input("   Record Count (default: 10): ").strip() or "10"
    try:
        record_count = int(record_count_str)
    except ValueError:
        record_count = 10
    
    # Generate or accept training_upload_id
    training_upload_id_input = input("   Training Upload ID (leave blank to auto-generate): ").strip()
    if training_upload_id_input:
        training_upload_id = training_upload_id_input
        print(f"\n📝 Using provided Training Upload ID: {training_upload_id}")
    else:
        training_upload_id = str(uuid.uuid4())
        print(f"\n📝 Generated Training Upload ID: {training_upload_id}")
    print(f"   Data Source ID: {data_source_id}")
    print(f"   File Name: {file_name}")
    print(f"   Raw File Path: {raw_file_path}")
    print(f"   File Size: {file_size_bytes} bytes")
    print(f"   Record Count: {record_count}")
    
    # Initialize PostgreSQL client
    print("\n🔌 Connecting to PostgreSQL...")
    try:
        postgres_client = PostgresClient(
            key_vault_url=KEY_VAULT_URL,
            key_vault_reader=kv_reader
        )
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize PostgreSQL client: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Insert record
    print("\n💾 Inserting record into training_uploads table...")
    
    insert_query = """
        INSERT INTO training_uploads (
            id,
            data_source_id,
            status,
            file_name,
            file_format,
            file_size_bytes,
            raw_file_path,
            record_count,
            created_at,
            updated_at
        ) VALUES (
            :id,
            :data_source_id,
            'ingesting',
            :file_name,
            'json',
            :file_size_bytes,
            :raw_file_path,
            :record_count,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
    """
    
    try:
        with postgres_client.get_session() as session:
            session.execute(
                text(insert_query),
                {
                    "id": training_upload_id,
                    "data_source_id": data_source_id,
                    "file_name": file_name,
                    "file_size_bytes": file_size_bytes,
                    "raw_file_path": raw_file_path,
                    "record_count": record_count
                }
            )
            session.commit()
        
        print("✅ Record inserted successfully!")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to insert record: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Print summary for next script
    print("\n" + "=" * 60)
    print("✅ Script 2 Complete - Summary")
    print("=" * 60)
    print("Use these values in Script 3 (send_test_ingestion_message_v2.py):")
    print(f"  TRAINING_UPLOAD_ID = {training_upload_id}")
    print(f"  DATA_SOURCE_ID = {data_source_id}")
    print(f"  FILE_FORMAT = json")
    print(f"  FILE_SIZE_BYTES = {file_size_bytes}")
    print(f"  RAW_FILE_PATH = {raw_file_path}")
    print("\n💡 Tip: Save these values or run Script 3 immediately after this one.")
    print("=" * 60)


if __name__ == "__main__":
    main()
