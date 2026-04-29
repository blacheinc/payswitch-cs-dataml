# Service Bus Message Parser - Usage Guide

## Overview

The Service Bus message parser enables systems to work with messages from the `data-ingested` topic. It extracts essential fields (`upload_id`, `bank_id`, `bronze_blob_path`) and automatically extracts the date from the path.

## Essential Fields

The parser requires only three fields:
- `upload_id`: Unique identifier for the upload (passed to ML engineer's system)
- `bank_id`: Bank identifier (e.g., "bank-digital-001")
- `bronze_blob_path`: Path to file in Bronze Layer (e.g., "bronze/training/bank-digital-001/2026-02-16/upload-id.csv")

## Usage Example

### 1. Parse Service Bus Message

```python
from utils.service_bus_parser import parse_data_ingested_message

# Raw Service Bus message
message = {
    "upload_id": "c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b",
    "bank_id": "bank-digital-001",
    "bronze_blob_path": "bronze/training/bank-digital-001/2026-02-16/c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b.csv"
}

# Parse message
parsed = parse_data_ingested_message(message)

# Returns:
# {
#     "upload_id": "c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b",
#     "bank_id": "bank-digital-001",
#     "bronze_blob_path": "bronze/training/bank-digital-001/2026-02-16/c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b.csv",
#     "date": "2026-02-16",  # Extracted from path
#     "file_format": "csv",  # Extracted from path (optional hint)
#     "original_message": {...}  # Full original message
# }
```

### 2. Use with FileIntrospector

```python
from systems import FileIntrospector
from utils.service_bus_parser import parse_data_ingested_message

# Parse message
parsed = parse_data_ingested_message(service_bus_message)

# Create introspector
introspector = FileIntrospector(datalake_client)

# Option 1: Pass parsed message (recommended)
result = introspector.introspect_file(
    file_path=parsed['bronze_blob_path'],
    parsed_message=parsed
)

# Option 2: Use bronze_blob_path directly (backward compatible)
result = introspector.introspect_file(
    file_path=parsed['bronze_blob_path']
)
```

### 3. Use with SchemaDetector

```python
from systems import SchemaDetector
from utils.service_bus_parser import parse_data_ingested_message

# Parse message
parsed = parse_data_ingested_message(service_bus_message)

# Create detector
detector = SchemaDetector(datalake_client)

# Detect format
format = detector.detect_format(
    file_path=parsed['bronze_blob_path'],
    introspection_result=introspection_result,
    parsed_message=parsed  # Optional: provides context
)

# Detect schema
schema_result = detector.detect_schema(
    file_path=parsed['bronze_blob_path'],
    format=format,
    introspection_result=introspection_result,
    parsed_message=parsed  # Optional: provides context
)
```

### 4. Use with DataSampler

```python
from systems import DataSampler
from utils.service_bus_parser import parse_data_ingested_message

# Parse message
parsed = parse_data_ingested_message(service_bus_message)

# Create sampler
sampler = DataSampler(datalake_client)

# Load and sample
sampling_result = sampler.load_and_sample_from_datalake(
    bronze_path=parsed['bronze_blob_path'],
    format=schema_result.format,
    encoding=schema_result.encoding,
    schema_result=schema_result,
    parsed_message=parsed  # Optional: provides context
)
```

## Message Context

When `parsed_message` is provided, systems store context in `_message_context`:

```python
# Access context (if parsed_message was provided)
if hasattr(introspector, '_message_context') and introspector._message_context:
    upload_id = introspector._message_context['upload_id']
    bank_id = introspector._message_context['bank_id']
    date = introspector._message_context['date']
```

This context can be used for:
- Schema Registry lookups (bank-specific mappings)
- Logging and tracking
- Error correlation
- Passing to downstream systems (e.g., ML engineer's system)

## Error Handling

```python
from utils.service_bus_parser import parse_data_ingested_message, ServiceBusMessageError

try:
    parsed = parse_data_ingested_message(message)
except ServiceBusMessageError as e:
    # Handle parsing errors
    print(f"Invalid message: {e}")
```

## Helper Functions

### Extract Date from Path

```python
from utils.service_bus_parser import extract_date_from_bronze_path

date = extract_date_from_bronze_path("bronze/training/bank-001/2026-02-16/file.csv")
# Returns: "2026-02-16"
```

### Build Bronze Path

```python
from utils.service_bus_parser import build_bronze_path

path = build_bronze_path(
    bank_id="bank-digital-001",
    date="2026-02-16",
    upload_id="c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b",
    file_format="csv"
)
# Returns: "bronze/training/bank-digital-001/2026-02-16/c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b.csv"
```

### Extract File Info

```python
from utils.service_bus_parser import extract_file_info_from_path

info = extract_file_info_from_path("bronze/training/bank-001/2026-02-16/file.csv")
# Returns: {
#     "bank_id": "bank-001",
#     "date": "2026-02-16",
#     "upload_id": "file",
#     "file_format": "csv"
# }
```

## Backward Compatibility

All systems maintain backward compatibility. You can still call them without `parsed_message`:

```python
# Old way (still works)
result = introspector.introspect_file(file_path="bronze/training/...")

# New way (with Service Bus integration)
parsed = parse_data_ingested_message(message)
result = introspector.introspect_file(
    file_path=parsed['bronze_blob_path'],
    parsed_message=parsed
)
```
