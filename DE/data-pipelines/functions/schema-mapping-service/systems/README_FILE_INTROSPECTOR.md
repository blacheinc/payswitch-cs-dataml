# File Introspection System (System 0)

## Overview

The File Introspection System performs **cheap probes** on file metadata **before** reading any significant data. It reads only small bytes (typically 8KB) to detect container/compression, encoding, format signatures, and record boundary hints.

## Purpose

- **Efficiency**: Avoids reading large files before knowing format
- **Safety**: Detects compression bombs, encoding issues early
- **Context**: Provides hints to Schema Detection System for more accurate detection

## Usage

### Basic Usage

```python
from azure.storage.filedatalake import DataLakeServiceClient
from azure.identity import DefaultAzureCredential
from systems.file_introspector import FileIntrospector

# Initialize Data Lake client
account_url = "https://YOUR_STORAGE_ACCOUNT.dfs.core.windows.net"
credential = DefaultAzureCredential()
service_client = DataLakeServiceClient(account_url=account_url, credential=credential)
file_system_client = service_client.get_file_system_client("data")

# Create introspector
introspector = FileIntrospector(file_system_client)

# Introspect file
result = introspector.introspect_file(
    file_path="bronze/raw/bank-001/2026-02-16/upload-123.json",
    sample_bytes=8192
)

# Access results
print(f"Encoding: {result.encoding}")
print(f"Has BOM: {result.has_bom}")
print(f"Container: {result.container_type}")
print(f"Compression: {result.compression_type}")
print(f"Newline type: {result.newline_type}")
print(f"Format hints: {result.format_hints}")
print(f"I/O hints: {result.io_hints}")
```

### Individual Detection Methods

```python
# Detect container/compression only
container_info = introspector.detect_container_and_compression("path/to/file.zip")

# Detect encoding only
encoding_info = introspector.detect_text_encoding("path/to/file.csv", sample_bytes=8192)

# Estimate record boundaries only
boundary_info = introspector.estimate_record_boundaries("path/to/file.csv", sample_bytes=8192)
```

## What It Detects

### Container Types
- **ZIP** files (PK\x03\x04 signature)
- **TAR** files (ustar, gnutar signatures)

### Compression Types
- **GZIP** (\x1f\x8b signature)
- **BZ2** (BZ signature)
- **XZ** (\xfd7zXZ signature)

### Encodings
- **UTF-8** (with/without BOM)
- **UTF-16** (LE/BE with BOM)
- **UTF-32** (LE/BE with BOM)
- **Latin-1**, **Windows-1252**, and others (via charset-normalizer)

### Record Boundaries
- **Newline-delimited** (\n, \r\n, \r)
- **Fixed-width** (consistent line lengths)
- **Delimiter hints** (comma, tab, pipe, semicolon candidates)

### Format Hints
- **JSON** (starts with { or [)
- **XML** (starts with <?xml or <)
- **CSV** (contains commas)
- **Excel** (ZIP structure with [Content_Types].xml)

## Testing

### Run Unit Tests
```bash
cd data-pipelines/functions/schema-mapping-service
pytest tests/test_file_introspector.py -v
```

### Test Locally with main.py
```bash
python main.py --test-file-introspection
```

### Test with Real Data Lake File
```bash
python main.py --test-file-introspection --file-path bronze/raw/bank-001/2026-02-16/upload-123.json
```

## Dependencies

- `azure-storage-file-datalake` - Data Lake Gen2 client
- `charset-normalizer` - Encoding detection
- Standard library: `zipfile`, `gzip`, `tarfile`, `bz2`

## Next System

After File Introspection, proceed to **System 1: Schema Detection System**, which uses the introspection hints for efficient format detection.
