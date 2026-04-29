"""
Generate Test Data for ADF Pipeline Testing
Creates a JSON file, uploads it to blob storage, and inserts a record in training_uploads table
"""

import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime
import random

# Try to import dotenv
try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False
    print("⚠️  python-dotenv not installed. Will use environment variables only.")

from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential, AzureCliCredential
from sqlalchemy import text

# Add parent directories to path
CURRENT_DIR = Path(__file__).parent
TRAINING_INGESTION_ROOT = CURRENT_DIR.parent
FUNCTION_ROOT = TRAINING_INGESTION_ROOT.parent

# Add paths for imports
if str(TRAINING_INGESTION_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAINING_INGESTION_ROOT))

# Load environment variables
if HAS_DOTENV:
    env_path = TRAINING_INGESTION_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)

# Same as check_training_upload_status.py: pick up Service Bus, storage, KEY_VAULT_URL from Functions local settings
_local_settings_path = TRAINING_INGESTION_ROOT / "local.settings.json"
if _local_settings_path.exists():
    try:
        with open(_local_settings_path, "r", encoding="utf-8") as _f:
            for _key, _val in json.load(_f).get("Values", {}).items():
                if _key not in os.environ and _val is not None:
                    os.environ[_key] = str(_val)
    except Exception as _e:
        print(f"Warning: could not load local.settings.json: {_e}")

# Import training utilities
from utils.training_key_vault_reader import TrainingKeyVaultReader, TrainingKeyVaultError
from utils.training_postgres_client import TrainingPostgresClient
from sqlalchemy import text

# Ghanaian names and data (matching existing test data generator)
GHANAIAN_FIRST_NAMES = [
    "Kwame", "Ama", "Kofi", "Akosua", "Yaw", "Efua", "Kojo", "Abena",
    "Kwaku", "Adwoa", "Fiifi", "Aba", "Kweku", "Akua", "Yaa", "Esi",
    "Kobina", "Afi", "Kwabena", "Ama", "Kofi", "Akosua", "Yaw", "Efua"
]

GHANAIAN_LAST_NAMES = [
    "Mensah", "Owusu", "Asante", "Boateng", "Osei", "Amoah", "Appiah",
    "Darko", "Adjei", "Agyeman", "Bonsu", "Danso", "Frimpong", "Gyasi",
    "Kwarteng", "Nkrumah", "Ofori", "Sarpong", "Tetteh", "Yeboah"
]

GHANAIAN_EMAIL_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "ghana.com", "mtn.com.gh", "vodafone.com.gh"
]

GHANAIAN_CITIES = [
    "Accra", "Kumasi", "Tamale", "Takoradi", "Sunyani", "Cape Coast",
    "Koforidua", "Ho", "Bolgatanga", "Wa", "Techiman", "Tema"
]

GHANAIAN_STREETS = [
    "Ring Road", "Oxford Street", "Independence Avenue", "Liberation Road",
    "Airport Road", "Spintex Road", "Tetteh Quarshie Avenue", "Cantonments Road"
]


def generate_ghanaian_phone():
    """Generate realistic Ghanaian phone number"""
    prefixes = ["020", "024", "026", "027", "050", "054", "055", "056", "057"]
    prefix = random.choice(prefixes)
    number = f"+233{prefix[1:]}{random.randint(1000000, 9999999)}"
    return number


def generate_ghanaian_email(first_name, last_name):
    """Generate email from name"""
    formats = [
        f"{first_name.lower()}.{last_name.lower()}",
        f"{first_name.lower()}{last_name.lower()}",
        f"{first_name.lower()}{random.randint(1, 999)}",
        f"{last_name.lower()}{random.randint(1, 999)}"
    ]
    username = random.choice(formats)
    domain = random.choice(GHANAIAN_EMAIL_DOMAINS)
    return f"{username}@{domain}"


def generate_national_id():
    """Generate Ghanaian National ID format (GHA-XXXXXXXX-X)"""
    return f"GHA-{random.randint(10000000, 99999999)}-{random.randint(1, 9)}"


def generate_passport_number():
    """Generate passport number format"""
    return f"G{random.randint(100000, 999999)}"


def generate_address(city):
    """Generate address"""
    street_num = random.randint(1, 999)
    street = random.choice(GHANAIAN_STREETS)
    return f"{street_num} {street}, {city}"


def generate_test_json_data(num_rows=10):
    """Generate test data with PII and financial columns (matching existing structure)"""
    data = []
    
    for i in range(num_rows):
        first_name = random.choice(GHANAIAN_FIRST_NAMES)
        last_name = random.choice(GHANAIAN_LAST_NAMES)
        city = random.choice(GHANAIAN_CITIES)
        
        record = {
            # PII Columns
            "customer_name": f"{first_name} {last_name}",
            "first_name": first_name,
            "last_name": last_name,
            "email_address": generate_ghanaian_email(first_name, last_name),
            "contact_email": generate_ghanaian_email(first_name, last_name),
            "phone_number": generate_ghanaian_phone(),
            "mobile_number": generate_ghanaian_phone(),
            "national_id": generate_national_id(),
            "passport_number": generate_passport_number(),
            "home_address": generate_address(city),
            "billing_address": generate_address(city),
            "city": city,
            "postal_code": f"GA{random.randint(100, 999)}",
            
            # Non-PII Columns (credit scoring related)
            "age": random.randint(18, 80),
            "monthly_income": round(random.uniform(1000, 50000), 2),
            "loan_amount": round(random.uniform(5000, 100000), 2),
            "loan_tenure_months": random.choice([12, 18, 24, 36, 48, 60]),
            "employment_years": round(random.uniform(0.5, 30), 1),
            "employment_type": random.choice(["Salaried", "Self-Employed", "Government"]),
            "account_balance": round(random.uniform(1000, 200000), 2),
            "savings_balance": round(random.uniform(500, 150000), 2),
            "existing_loans_balance": round(random.uniform(0, 100000), 2),
            "monthly_loan_repayment": round(random.uniform(0, 5000), 2),
            "account_age_months": random.randint(1, 240),
            "monthly_transactions_count": random.randint(5, 200),
            "credit_history_months": random.randint(0, 240),
            "num_credit_inquiries": random.randint(0, 10),
            "num_late_payments": random.randint(0, 12),
            "credit_score": random.randint(300, 850),
            "debt_to_income_ratio": round(random.uniform(0.1, 0.8), 2),
            "loan_to_value_ratio": round(random.uniform(0.1, 0.9), 2)
        }
        
        data.append(record)
    
    return data


def upload_to_blob_storage(blob_service_client, container_name, blob_path, file_content):
    """Upload file content to blob storage"""
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_path)
    
    # Upload the file
    blob_client.upload_blob(file_content, overwrite=True)
    print(f"✅ Uploaded file to: {container_name}/{blob_path}")
    
    # Get file size
    blob_properties = blob_client.get_blob_properties()
    file_size = blob_properties.size
    
    return file_size


def insert_training_upload_record(
    postgres_client,
    training_upload_id,
    data_source_id,
    file_name,
    file_format,
    file_size_bytes,
    raw_file_path,
    record_count
):
    """Insert record into training_uploads table"""
    with postgres_client.get_session() as session:
        try:
            # Use ON CONFLICT to handle partial runs
            query = text("""
                INSERT INTO training_uploads (
                    id, data_source_id, status, file_name, file_format, 
                    file_size_bytes, raw_file_path, record_count, 
                    created_at, updated_at
                )
                VALUES (
                    :id, :data_source_id, 'ingesting', :file_name, :file_format,
                    :file_size_bytes, :raw_file_path, :record_count,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = 'ingesting',
                    file_name = EXCLUDED.file_name,
                    file_format = EXCLUDED.file_format,
                    file_size_bytes = EXCLUDED.file_size_bytes,
                    raw_file_path = EXCLUDED.raw_file_path,
                    record_count = EXCLUDED.record_count,
                    updated_at = CURRENT_TIMESTAMP
            """)
            
            session.execute(query, {
                "id": training_upload_id,
                "data_source_id": data_source_id,
                "file_name": file_name,
                "file_format": file_format,
                "file_size_bytes": file_size_bytes,
                "raw_file_path": raw_file_path,
                "record_count": record_count
            })
            
            session.commit()
            print(f"✅ Inserted/updated record in training_uploads table")
            return True
            
        except Exception as e:
            session.rollback()
            print(f"❌ ERROR: Failed to insert record: {str(e)}")
            raise


def main():
    """Main function to generate test data"""
    print("=" * 60)
    print("Generate Test Data for ADF Pipeline Testing")
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
    DATA_SOURCE_ID = "b4ed5120-65f4-46c5-b687-dc895a1d6bbf"  # Constant data source ID
    CONTAINER_NAME = "data"
    NUM_RECORDS = 10  # Number of records in JSON file
    
    # Generate unique training_upload_id
    training_upload_id = str(uuid.uuid4())
    
    # Generate file name with timestamp for uniqueness
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"test_ingestion_{timestamp}.json"
    raw_file_path = f"{DATA_SOURCE_ID}/{file_name}"
    
    print(f"\n📋 Test Data Configuration:")
    print(f"   Training Upload ID: {training_upload_id}")
    print(f"   Data Source ID: {DATA_SOURCE_ID}")
    print(f"   File Name: {file_name}")
    print(f"   Raw File Path: {raw_file_path}")
    print(f"   Number of Records: {NUM_RECORDS}")
    
    # Initialize Key Vault reader
    try:
        kv_reader = TrainingKeyVaultReader(key_vault_url=KEY_VAULT_URL)
        print("\n✅ Key Vault reader initialized")
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize Key Vault reader: {str(e)}")
        sys.exit(1)
    
    # Blob connection: prefer env (local.settings.json is merged above). Key Vault can hang on auth/network.
    print("\n📦 Resolving blob storage connection string...")
    blob_connection_string = None
    for env_key in (
        "BlobStorageConnectionString",
        "AzureWebJobsStorage",
        "DATALAKE_STORAGE_CONNECTION_STRING",
    ):
        candidate = os.getenv(env_key)
        if candidate and str(candidate).strip():
            blob_connection_string = str(candidate).strip()
            print(f"✅ Using {env_key} from environment")
            break
    if not blob_connection_string:
        print(
            "📦 No blob connection in env; calling Key Vault for secret 'BlobStorageConnectionString'...",
            flush=True,
        )
        print(
            "   If this hangs: run `az login`, check VPN/firewall, or put the connection string in local.settings.json "
            "as BlobStorageConnectionString, AzureWebJobsStorage, or DATALAKE_STORAGE_CONNECTION_STRING.",
            flush=True,
        )
        try:
            blob_connection_string = kv_reader.get_secret("BlobStorageConnectionString")
            print("✅ Retrieved blob storage connection string from Key Vault")
        except Exception as e:
            print(f"❌ ERROR: Failed to get blob storage connection string: {str(e)}")
            sys.exit(1)
    
    # Generate test data
    print(f"\n📝 Generating {NUM_RECORDS} test records...")
    test_data = generate_test_json_data(num_rows=NUM_RECORDS)
    
    # Convert to JSON string
    json_content = json.dumps(test_data, indent=2)
    file_size_bytes = len(json_content.encode('utf-8'))
    print(f"✅ Generated JSON data ({file_size_bytes} bytes)")
    
    # Upload to blob storage
    print(f"\n☁️  Uploading to blob storage...")
    try:
        blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)
        uploaded_size = upload_to_blob_storage(
            blob_service_client,
            CONTAINER_NAME,
            raw_file_path,
            json_content
        )
        
        if uploaded_size != file_size_bytes:
            print(f"⚠️  WARNING: File size mismatch. Expected: {file_size_bytes}, Uploaded: {uploaded_size}")
        
    except Exception as e:
        print(f"❌ ERROR: Failed to upload to blob storage: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # PostgreSQL: client is lazy — first query opens TCP + may call Key Vault for secrets
    print(
        "\n🗄️  Preparing PostgreSQL client...",
        flush=True,
    )
    try:
        postgres_client = TrainingPostgresClient(
            key_vault_url=KEY_VAULT_URL,
            key_vault_reader=kv_reader,
        )
        print(
            "   (Connection is opened on first query; set PostgreSQLConnectionString in local.settings.json "
            "to skip Key Vault for DB.)",
            flush=True,
        )
    except Exception as e:
        print(f"❌ ERROR: Failed to create PostgreSQL client: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Insert record into training_uploads table
    print(
        "\n💾 Inserting record into training_uploads table (Key Vault + network + possible row locks)...",
        flush=True,
    )
    try:
        insert_training_upload_record(
            postgres_client,
            training_upload_id,
            DATA_SOURCE_ID,
            file_name,
            "json",
            file_size_bytes,
            raw_file_path,
            NUM_RECORDS
        )
    except Exception as e:
        print(f"❌ ERROR: Failed to insert database record: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        postgres_client.close()
    
    # Print summary
    print("\n" + "=" * 60)
    print("✅ Test Data Generation Complete!")
    print("=" * 60)
    print(f"\n📋 Generated Test Data Summary:")
    print(f"   Training Upload ID: {training_upload_id}")
    print(f"   Data Source ID: {DATA_SOURCE_ID}")
    print(f"   File Name: {file_name}")
    print(f"   File Format: json")
    print(f"   File Size: {file_size_bytes} bytes")
    print(f"   Raw File Path: {raw_file_path}")
    print(f"   Record Count: {NUM_RECORDS}")
    print(f"   Blob Storage: {CONTAINER_NAME}/{raw_file_path}")
    print(f"   Database Status: 'ingesting'")
    
    print(f"\n📝 Next Steps:")
    print(f"   1. Use the following parameters to trigger the ADF pipeline manually:")
    print(f"      - training_upload_id: {training_upload_id}")
    print(f"      - data_source_id: {DATA_SOURCE_ID}")
    print(f"      - file_format: json")
    print(f"      - file_size_bytes: {file_size_bytes}")
    print(f"      - raw_file_path: {raw_file_path}")
    print(f"   2. See ADF_PIPELINE_TESTING_GUIDE.md for complete testing instructions")
    print("=" * 60)


if __name__ == "__main__":
    main()
