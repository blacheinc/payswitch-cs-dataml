"""
Service Bus Message Generator
Creates JSON messages for testing schema mapping pipeline
"""

import json
from pathlib import Path
from datetime import datetime

# Configuration
BANK_ID = "Bank-001"
DATE = "2026-02-24"
BASE_UPLOAD_ID = "test-upload-001"

# File formats and their extensions
FORMATS = {
    "csv": "csv",
    "json": "json",
    "jsonl": "jsonl",
    "parquet": "parquet",
    "excel": "xlsx",
    "tsv": "tsv"
}


def build_bronze_path(bank_id: str, date: str, upload_id: str, file_format: str) -> str:
    """Build bronze blob path"""
    return f"bronze/training/{bank_id}/{date}/{upload_id}.{file_format}"


def generate_service_bus_message(upload_id: str, file_format: str) -> dict:
    """Generate Service Bus message for a test file"""
    bronze_path = build_bronze_path(BANK_ID, DATE, upload_id, file_format)
    
    message = {
        "upload_id": upload_id,
        "bank_id": BANK_ID,
        "bronze_blob_path": bronze_path,
        # Optional fields (for reference)
        "ingestion_timestamp": datetime.utcnow().isoformat() + "Z",
        "status": "ingested"
    }
    
    return message


def main():
    """Generate Service Bus messages for all test files"""
    output_dir = Path(__file__).parent / "service_bus_messages"
    output_dir.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("Generating Service Bus Messages")
    print("=" * 60)
    
    messages = []
    
    # Generate one message per format
    for idx, (format_name, extension) in enumerate(FORMATS.items(), start=1):
        upload_id = f"{BASE_UPLOAD_ID}-{format_name}"
        message = generate_service_bus_message(upload_id, extension)
        messages.append(message)
        
        # Save individual message file
        message_file = output_dir / f"message_{format_name}.json"
        with open(message_file, 'w', encoding='utf-8') as f:
            json.dump(message, f, indent=2)
        print(f"Created: {message_file}")
    
    # Save combined messages file
    combined_file = output_dir / "all_messages.json"
    with open(combined_file, 'w', encoding='utf-8') as f:
        json.dump(messages, f, indent=2)
    print(f"\nCreated combined file: {combined_file}")
    
    print("\n" + "=" * 60)
    print("Service Bus message generation complete!")
    print(f"Messages created in: {output_dir}")
    print("=" * 60)
    
    # Print summary
    print("\nMessage Summary:")
    for msg in messages:
        print(f"  {msg['upload_id']}: {msg['bronze_blob_path']}")


if __name__ == "__main__":
    main()
