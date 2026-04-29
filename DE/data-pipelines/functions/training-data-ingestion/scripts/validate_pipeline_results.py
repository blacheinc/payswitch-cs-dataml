"""
Validate ADF Pipeline Results
Queries database and displays validation results for a pipeline run
"""

import os
import sys
from pathlib import Path
from datetime import datetime

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

# Load environment variables
if HAS_DOTENV:
    env_path = TRAINING_INGESTION_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

# Import training utilities
from utils.training_key_vault_reader import TrainingKeyVaultReader, TrainingKeyVaultError
from utils.training_postgres_client import TrainingPostgresClient
from sqlalchemy import text


def validate_training_uploads(postgres_client, training_upload_id):
    """Validate training_uploads table record"""
    print("\n" + "=" * 60)
    print("1. Validating training_uploads Table")
    print("=" * 60)
    
    with postgres_client.get_session() as session:
        query = text("""
            SELECT 
                id,
                data_source_id,
                status,
                file_name,
                file_format,
                file_size_bytes,
                raw_file_path,
                record_count,
                error_message,
                updated_at
            FROM training_uploads
            WHERE id = :training_upload_id
        """)
        
        result = session.execute(query, {"training_upload_id": training_upload_id})
        row = result.fetchone()
        
        if not row:
            print(f"❌ ERROR: No record found with training_upload_id = {training_upload_id}")
            return False
        
        print(f"\n📋 Record Details:")
        print(f"   ID: {row.id}")
        print(f"   Data Source ID: {row.data_source_id}")
        print(f"   Status: {row.status}")
        print(f"   File Name: {row.file_name}")
        print(f"   File Format: {row.file_format}")
        print(f"   File Size: {row.file_size_bytes} bytes")
        print(f"   Raw File Path: {row.raw_file_path}")
        print(f"   Record Count: {row.record_count}")
        print(f"   Error Message: {row.error_message or 'None'}")
        print(f"   Updated At: {row.updated_at}")
        
        # Validation checks
        checks_passed = 0
        total_checks = 3
        
        print(f"\n✅ Validation Checks:")
        
        # Check 1: Status should be 'ingested'
        if row.status == 'ingested':
            print(f"   ✅ Status is 'ingested' (expected)")
            checks_passed += 1
        else:
            print(f"   ❌ Status is '{row.status}' (expected 'ingested')")
        
        # Check 2: No error message
        if row.error_message is None:
            print(f"   ✅ No error message (expected)")
            checks_passed += 1
        else:
            print(f"   ⚠️  Error message present: {row.error_message}")
        
        # Check 3: Updated timestamp is recent (within last hour)
        if row.updated_at:
            time_diff = datetime.utcnow() - row.updated_at.replace(tzinfo=None)
            if time_diff.total_seconds() < 3600:  # Within 1 hour
                print(f"   ✅ Updated recently ({time_diff.total_seconds():.0f} seconds ago)")
                checks_passed += 1
            else:
                print(f"   ⚠️  Updated {time_diff.total_seconds()/60:.1f} minutes ago (may be from previous run)")
        
        print(f"\n📊 Validation Result: {checks_passed}/{total_checks} checks passed")
        return checks_passed == total_checks


def validate_bronze_ingestion_log(postgres_client, training_upload_id):
    """Validate bronze_ingestion_log table record"""
    print("\n" + "=" * 60)
    print("2. Validating bronze_ingestion_log Table")
    print("=" * 60)
    
    with postgres_client.get_session() as session:
        query = text("""
            SELECT 
                id,
                training_upload_id,
                run_id,
                source_blob_path,
                bronze_blob_path,
                source_checksum_sha256,
                bronze_checksum_sha256,
                source_file_size_bytes,
                bronze_file_size_bytes,
                ingestion_status,
                error_message,
                ingested_at,
                created_at
            FROM bronze_ingestion_log
            WHERE training_upload_id = :training_upload_id
            ORDER BY ingested_at DESC
            LIMIT 1
        """)
        
        result = session.execute(query, {"training_upload_id": training_upload_id})
        row = result.fetchone()
        
        if not row:
            print(f"❌ ERROR: No record found in bronze_ingestion_log for training_upload_id = {training_upload_id}")
            return False
        
        print(f"\n📋 Log Record Details:")
        print(f"   ID: {row.id}")
        print(f"   Training Upload ID: {row.training_upload_id}")
        print(f"   Run ID: {row.run_id}")
        print(f"   Source Blob Path: {row.source_blob_path}")
        print(f"   Bronze Blob Path: {row.bronze_blob_path}")
        print(f"   Source Checksum: {row.source_checksum_sha256[:16]}...")
        print(f"   Bronze Checksum: {row.bronze_checksum_sha256[:16]}...")
        print(f"   Source File Size: {row.source_file_size_bytes} bytes")
        print(f"   Bronze File Size: {row.bronze_file_size_bytes} bytes")
        print(f"   Ingestion Status: {row.ingestion_status}")
        print(f"   Error Message: {row.error_message or 'None'}")
        print(f"   Ingested At: {row.ingested_at}")
        
        # Validation checks
        checks_passed = 0
        total_checks = 4
        
        print(f"\n✅ Validation Checks:")
        
        # Check 1: Ingestion status should be 'success'
        if row.ingestion_status == 'success':
            print(f"   ✅ Ingestion status is 'success' (expected)")
            checks_passed += 1
        else:
            print(f"   ❌ Ingestion status is '{row.ingestion_status}' (expected 'success')")
        
        # Check 2: Checksums should match
        if row.source_checksum_sha256 == row.bronze_checksum_sha256:
            print(f"   ✅ Checksums match (expected)")
            checks_passed += 1
        else:
            print(f"   ❌ Checksums do not match!")
            print(f"      Source: {row.source_checksum_sha256[:32]}...")
            print(f"      Bronze: {row.bronze_checksum_sha256[:32]}...")
        
        # Check 3: File sizes should match
        if row.source_file_size_bytes == row.bronze_file_size_bytes:
            print(f"   ✅ File sizes match ({row.source_file_size_bytes} bytes)")
            checks_passed += 1
        else:
            print(f"   ❌ File sizes do not match!")
            print(f"      Source: {row.source_file_size_bytes} bytes")
            print(f"      Bronze: {row.bronze_file_size_bytes} bytes")
        
        # Check 4: Bronze path format
        expected_path_pattern = f"bronze/training/{row.training_upload_id.split('-')[0]}"
        if "bronze/training" in row.bronze_blob_path:
            print(f"   ✅ Bronze path format is correct")
            checks_passed += 1
        else:
            print(f"   ⚠️  Bronze path format may be incorrect: {row.bronze_blob_path}")
        
        print(f"\n📊 Validation Result: {checks_passed}/{total_checks} checks passed")
        return checks_passed == total_checks


def main():
    """Main validation function"""
    if len(sys.argv) < 2:
        print("Usage: python validate_pipeline_results.py <training_upload_id>")
        sys.exit(1)
    
    training_upload_id = sys.argv[1]
    
    print("=" * 60)
    print("ADF Pipeline Results Validation")
    print("=" * 60)
    print(f"\n🔍 Validating pipeline run for training_upload_id: {training_upload_id}")
    
    # Load environment variables
    if HAS_DOTENV:
        env_path = TRAINING_INGESTION_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    
    # Configuration
    KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
    if not KEY_VAULT_URL:
        raise ValueError("KEY_VAULT_URL environment variable is required")
    
    # Initialize PostgreSQL client
    print("\n🗄️  Connecting to PostgreSQL...")
    try:
        postgres_client = TrainingPostgresClient(key_vault_url=KEY_VAULT_URL)
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ ERROR: Failed to connect to PostgreSQL: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    try:
        # Validate training_uploads
        training_uploads_valid = validate_training_uploads(postgres_client, training_upload_id)
        
        # Validate bronze_ingestion_log
        bronze_log_valid = validate_bronze_ingestion_log(postgres_client, training_upload_id)
        
        # Final summary
        print("\n" + "=" * 60)
        print("📊 Final Validation Summary")
        print("=" * 60)
        print(f"   training_uploads: {'✅ PASSED' if training_uploads_valid else '❌ FAILED'}")
        print(f"   bronze_ingestion_log: {'✅ PASSED' if bronze_log_valid else '❌ FAILED'}")
        
        if training_uploads_valid and bronze_log_valid:
            print("\n✅ All validations passed! Pipeline executed successfully.")
        else:
            print("\n❌ Some validations failed. Please check the details above.")
        
        print("\n📝 Next Steps:")
        print("   1. Verify file exists in Data Lake at the bronze_blob_path")
        print("   2. Check Service Bus topic 'data-ingested' for success message")
        print("   3. Verify message format matches expected structure")
        print("=" * 60)
        
    finally:
        postgres_client.close()


if __name__ == "__main__":
    main()
