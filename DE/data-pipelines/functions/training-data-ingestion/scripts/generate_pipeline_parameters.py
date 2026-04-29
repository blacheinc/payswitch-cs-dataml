"""
Generate ADF Pipeline Parameters JSON
Creates a JSON file with all required parameters for manual pipeline trigger
"""

import json
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

# Ensure project root is on sys.path so `utils` can be imported when run as a script
if str(TRAINING_INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_INGESTION_ROOT))

# Load environment variables
if HAS_DOTENV:
    env_path = TRAINING_INGESTION_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

# Import training utilities
from utils.training_key_vault_reader import TrainingKeyVaultReader, TrainingKeyVaultError


def main():
    """Main function to generate pipeline parameters"""
    print("=" * 60)
    print("Generate ADF Pipeline Parameters")
    print("=" * 60)
    
    # Load environment variables
    if HAS_DOTENV:
        env_path = TRAINING_INGESTION_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    
    # Configuration
    KEY_VAULT_URL = os.getenv("KEY_VAULT_URL")
    if not KEY_VAULT_URL:
        raise ValueError("KEY_VAULT_URL environment variable is required")
    
    # Constants
    DATA_SOURCE_ID = "b4ed5120-65f4-46c5-b687-dc895a1d6bbf"
    
    print("\n📋 Enter test data information:")
    print("   (Run generate_adf_test_data.py first to get these values)")
    
    training_upload_id = input("   Training Upload ID (UUID): ").strip()
    if not training_upload_id:
        print("   ❌ ERROR: training_upload_id is required")
        sys.exit(1)
    
    file_name = input("   File Name (e.g., test_ingestion_20260315_120000.json): ").strip()
    if not file_name:
        print("   ❌ ERROR: file_name is required")
        sys.exit(1)
    
    file_size_bytes_str = input("   File Size (bytes): ").strip()
    if not file_size_bytes_str:
        print("   ❌ ERROR: file_size_bytes is required")
        sys.exit(1)
    try:
        file_size_bytes = int(file_size_bytes_str)
    except ValueError:
        print("   ❌ ERROR: file_size_bytes must be an integer")
        sys.exit(1)
    
    file_format = input("   File Format (default: json): ").strip() or "json"
    
    # Build raw_file_path
    raw_file_path = f"{DATA_SOURCE_ID}/{file_name}"
    
    # Initialize Key Vault reader
    try:
        kv_reader = TrainingKeyVaultReader(key_vault_url=KEY_VAULT_URL)
        print("\n✅ Key Vault reader initialized")
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Key Vault reader: {str(e)}")
        sys.exit(1)
    
    # Get Service Bus namespace
    print("\n📦 Getting Service Bus namespace...")
    service_bus_namespace = input("   Service Bus Namespace (or press Enter to get from Key Vault): ").strip()
    if not service_bus_namespace:
        try:
            # Try to get from Key Vault
            service_bus_namespace = kv_reader.get_secret("ServiceBusNamespace")
            print(f"✅ Retrieved Service Bus namespace from Key Vault: {service_bus_namespace}")
        except Exception as e:
            print(f"⚠️  WARNING: Could not get Service Bus namespace from Key Vault: {str(e)}")
            service_bus_namespace = input("   Please enter Service Bus Namespace: ").strip()
            if not service_bus_namespace:
                print("   ❌ ERROR: Service Bus namespace is required")
                sys.exit(1)
    
    # Get File Checksum Calculator Function URL
    print("\n📦 Getting File Checksum Calculator Function URL...")
    function_base_url = input("   File Checksum Calculator Base URL (or press Enter to get from Key Vault): ").strip()
    if not function_base_url:
        try:
            function_base_url = kv_reader.get_secret("FileChecksumCalculatorFunctionBaseUrl")
            print(f"✅ Retrieved function base URL from Key Vault: {function_base_url}")
        except Exception as e:
            print(f"⚠️  WARNING: Could not get function URL from Key Vault: {str(e)}")
            function_base_url = input("   Please enter File Checksum Calculator Base URL: ").strip()
            if not function_base_url:
                print("   ❌ ERROR: File Checksum Calculator Base URL is required")
                sys.exit(1)
    
    # Get File Checksum Calculator Function Key
    print("\n📦 Getting File Checksum Calculator Function Key...")
    function_key = input("   File Checksum Calculator Key (or press Enter to get from Key Vault): ").strip()
    if not function_key:
        try:
            function_key = kv_reader.get_secret("FileChecksumCalculatorFunctionKey")
            print(f"✅ Retrieved function key from Key Vault")
        except Exception as e:
            print(f"⚠️  WARNING: Could not get function key from Key Vault: {str(e)}")
            function_key = input("   Please enter File Checksum Calculator Key: ").strip()
            if not function_key:
                print("   ❌ ERROR: File Checksum Calculator Key is required")
                sys.exit(1)
    
    # Generate run_id
    run_id = str(uuid.uuid4())
    
    # Build parameters
    parameters = {
        "training_upload_id": training_upload_id,
        "data_source_id": DATA_SOURCE_ID,
        "file_format": file_format,
        "file_size_bytes": file_size_bytes,
        "raw_file_path": raw_file_path,
        "serviceBusNamespace": service_bus_namespace,
        "fileChecksumCalculatorBaseUrl": function_base_url,
        "fileChecksumCalculatorKey": function_key,
        "run_id": run_id,
        "dataAwaitsIngestionTopic": "data-awaits-ingestion",
        "dataIngestedTopic": "data-ingested"
    }
    
    # Print parameters
    print("\n" + "=" * 60)
    print("✅ Pipeline Parameters Generated")
    print("=" * 60)
    print("\n📋 Parameters JSON:")
    print(json.dumps(parameters, indent=2))
    
    # Save to file
    output_file = CURRENT_DIR / "pipeline_parameters.json"
    with open(output_file, 'w') as f:
        json.dump(parameters, f, indent=2)
    
    print(f"\n💾 Parameters saved to: {output_file}")
    
    print("\n📝 Next Steps:")
    print("   1. Copy the JSON above or use the saved file")
    print("   2. Go to Azure Portal → Data Factory → Pipelines")
    print("   3. Select 'pipeline-training-data-ingestion'")
    print("   4. Click 'Add trigger' → 'Trigger now'")
    print("   5. Paste the JSON in the Parameters section")
    print("   6. Click 'OK' to start the pipeline")
    print("=" * 60)


if __name__ == "__main__":
    main()
