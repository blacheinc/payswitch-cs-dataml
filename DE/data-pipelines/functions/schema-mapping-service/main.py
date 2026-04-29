"""
Main entry point for local testing of Schema Mapping Service
Run this file directly to test the service before deploying to Azure Functions

Usage:
    python main.py --test  # Run test suite
    python main.py --test-file-introspection --file-path bronze/raw/bank-001/2026-02-16/upload-123.json
"""

import argparse
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from entities.data_file import DataFile
from internal_schemas import validate_internal_schema, InternalSchemaV1, InternalSchemaV2, InternalSchemaV3
from systems.file_introspector import FileIntrospector
from datetime import datetime


def test_schema_validation():
    """Test schema validation with sample data"""
    print("Testing schema validation...")
    
    # Test with valid schema (12 fields)
    sample_data_v1 = InternalSchemaV1(
        approved=1,
        age=35,
        monthly_income=5000,
        loan_amount_requested=10000,
        loan_tenure_months=24,
        existing_loans_balance=0,
        monthly_loan_repayment=0,
        employment_years=5,
        account_balance=3000,
        savings_balance=5000,
        account_age_months=36,
        credit_history_months=48
    )
    
    is_valid, field_count, error = validate_internal_schema(sample_data_v1, min_fields=12)
    print(f"✓ Valid schema: {is_valid}, Fields: {field_count}")
    if error:
        print(f"  Error: {error}")
    
    # Test with invalid schema (less than 12 fields)
    invalid_data = InternalSchemaV1(
        approved=1,
        age=35,
        monthly_income=5000,
        loan_amount_requested=10000,
        loan_tenure_months=24,
        existing_loans_balance=0,
        monthly_loan_repayment=0,
        employment_years=5,
        account_balance=3000,
        savings_balance=5000
        # Missing account_age_months and credit_history_months
    )
    
    is_valid, field_count, error = validate_internal_schema(invalid_data, min_fields=12)
    print(f"✗ Invalid schema: {is_valid}, Fields: {field_count}")
    if error:
        print(f"  Error: {error}")


def test_data_file_entity():
    """Test DataFile entity"""
    print("\nTesting DataFile entity...")
    
    data_file = DataFile(
        file_path="bronze/raw/bank-001/2026-02-16/upload-123.json",
        bank_id="bank-001",
        upload_id="upload-123",
        date="2026-02-16",
        format="json",
        encoding="utf-8"
    )
    
    print(f"✓ Created DataFile: {data_file.file_name}")
    print(f"  Bronze path: {data_file.bronze_path}")
    print(f"  Staging internal path: {data_file.staging_internal_path}")
    print(f"  Silver path: {data_file.silver_path}")
    print(f"  Gold path: {data_file.gold_path}")


def test_file_introspector():
    """Test FileIntrospector with sample data"""
    print("\nTesting FileIntrospector...")
    
    # Create mock Data Lake client
    mock_datalake_client = Mock()
    mock_file_client = Mock()
    mock_file_properties = Mock()
    mock_file_properties.size = 8192
    
    # Sample CSV data with UTF-8 BOM
    sample_data = b'\xef\xbb\xbfcol1,col2,col3\nval1,val2,val3\nval4,val5,val6'
    
    mock_file_client.get_file_properties.return_value = mock_file_properties
    mock_file_client.download_file.return_value.readall.return_value = sample_data
    mock_datalake_client.get_file_client.return_value = mock_file_client
    
    # Create introspector and test
    introspector = FileIntrospector(mock_datalake_client)
    
    # Test container/compression detection
    container_result = introspector.detect_container_and_compression_from_bytes(
        sample_data, 'test.csv'
    )
    print(f"✓ Container detection: {container_result}")
    
    # Test encoding detection
    encoding_result = introspector.detect_text_encoding_from_bytes(sample_data)
    print(f"✓ Encoding detection: {encoding_result['encoding']}, BOM: {encoding_result['has_bom']}")
    
    # Test record boundary estimation
    boundary_result = introspector.estimate_record_boundaries_from_bytes(sample_data)
    print(f"✓ Record boundaries: {boundary_result['newline_type']}, Type: {boundary_result['boundary_type']}")
    print(f"  Delimiter hints: {boundary_result['delimiter_hints']}")
    
    # Test full introspection
    full_result = introspector.introspect_file('test/path/file.csv', sample_bytes=8192)
    print(f"✓ Full introspection complete:")
    print(f"  File size: {full_result.file_size_bytes} bytes")
    print(f"  Encoding: {full_result.encoding}")
    print(f"  Has BOM: {full_result.has_bom}")
    print(f"  Newline type: {full_result.newline_type}")
    print(f"  Format hints: {full_result.format_hints}")
    print(f"  I/O hints: {full_result.io_hints}")


def test_file_introspector_with_real_data(file_path: str):
    """Test FileIntrospector with real Data Lake file (requires Azure credentials)"""
    print(f"\nTesting FileIntrospector with real file: {file_path}")
    
    try:
        from azure.identity import DefaultAzureCredential
        from azure.storage.filedatalake import DataLakeServiceClient
        
        # Initialize Data Lake client
        account_name = "YOUR_STORAGE_ACCOUNT_NAME"  # Replace with actual
        account_url = f"https://{account_name}.dfs.core.windows.net"
        credential = DefaultAzureCredential()
        
        service_client = DataLakeServiceClient(account_url=account_url, credential=credential)
        file_system_client = service_client.get_file_system_client("data")  # Replace with actual container
        
        # Create introspector
        introspector = FileIntrospector(file_system_client)
        
        # Run introspection
        result = introspector.introspect_file(file_path, sample_bytes=8192)
        
        print(f"✓ Introspection complete:")
        print(f"  Container: {result.container_type}")
        print(f"  Compression: {result.compression_type}")
        print(f"  Encoding: {result.encoding}")
        print(f"  Has BOM: {result.has_bom}")
        print(f"  Newline type: {result.newline_type}")
        print(f"  File size: {result.file_size_bytes} bytes")
        print(f"  Format hints: {result.format_hints}")
        print(f"  I/O hints: {result.io_hints}")
        
    except ImportError:
        print("✗ Azure libraries not installed. Install with: pip install azure-storage-file-datalake azure-identity")
    except Exception as e:
        print(f"✗ Error: {e}")


def main():
    """Main function for local testing"""
    parser = argparse.ArgumentParser(description="Test Schema Mapping Service locally")
    parser.add_argument("--bank-id", type=str, help="Bank ID")
    parser.add_argument("--upload-id", type=str, help="Upload ID")
    parser.add_argument("--bronze-path", type=str, help="Path to bronze layer file")
    parser.add_argument("--test", action="store_true", help="Run all test suite")
    parser.add_argument("--test-file-introspection", action="store_true", help="Test FileIntrospector")
    parser.add_argument("--file-path", type=str, help="File path for introspection test")
    
    args = parser.parse_args()
    
    if args.test:
        print("Running test suite...\n")
        test_schema_validation()
        test_data_file_entity()
        test_file_introspector()
        print("\n✓ All tests passed!")
    elif args.test_file_introspection:
        if args.file_path:
            test_file_introspector_with_real_data(args.file_path)
        else:
            test_file_introspector()
    else:
        print("Schema Mapping Service - Local Testing")
        print("\nAvailable commands:")
        print("  --test                          Run all tests")
        print("  --test-file-introspection        Test FileIntrospector with mock data")
        print("  --test-file-introspection --file-path <path>  Test with real Data Lake file")
        print("\nExample:")
        print("  python main.py --test")
        print("  python main.py --test-file-introspection")


if __name__ == "__main__":
    main()

