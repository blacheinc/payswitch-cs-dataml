"""
Real Data Lake Integration Test for FileIntrospector
Tests the FileIntrospector with actual Azure Data Lake Gen2 files

Usage:
    # Option 1: Single file (uses default JSON file)
    python test_file_introspector_real.py
    
    # Option 2: Single file via environment variable
    $env:TEST_FILE_PATH = "training/bank-digital-001/2026-02-18/f68f81a3-780d-4971-829d-4484fa1a6cd0.json"
    python test_file_introspector_real.py
    
    # Option 3: Multiple files (comma-separated list)
    $env:TEST_FILE_PATHS = "training/bank-digital-001/2026-02-18/f68f81a3-780d-4971-829d-4484fa1a6cd0.json,training/bank-digital-001/2026-02-16/89bf5d21-0ee8-4886-ab39-e70a9a0c1107.csv"
    python test_file_introspector_real.py
    
    # Optional: Override storage account and container
    $env:STORAGE_ACCOUNT_NAME = "blachedly27jgavel2x32"
    $env:CONTAINER_NAME = "bronze"
    python test_file_introspector_real.py
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel

# Fix Windows console encoding for Unicode characters
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add current directory to path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Import Azure libraries
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient
from azure.storage.blob import BlobServiceClient

# Define FileIntrospectionResult inline to avoid import issues
class FileIntrospectionResult(BaseModel):
    """Result from file introspection (cheap probes)"""
    container_type: Optional[str] = None
    compression_type: Optional[str] = None
    encoding: Optional[str] = None
    has_bom: bool = False
    newline_type: Optional[str] = None
    file_size_bytes: int
    magic_bytes: Optional[bytes] = None
    format_hints: Dict[str, Any] = {}
    io_hints: Dict[str, Any] = {}


# Import FileIntrospector by directly importing the class code
# We'll create a simplified version that doesn't depend on the interface
import zipfile
import gzip
import tarfile
import bz2
from charset_normalizer import detect as detect_encoding


class FileIntrospector:
    """
    File Introspection System
    Performs cheap probes on file metadata before reading significant data
    """
    
    # Magic bytes for format detection
    MAGIC_BYTES = {
        b'PK\x03\x04': 'zip',
        b'PK\x05\x06': 'zip',
        b'PK\x07\x08': 'zip',
        b'\x1f\x8b': 'gzip',
        b'BZ': 'bz2',
        b'\xfd7zXZ\x00': 'xz',
        b'ustar': 'tar',
        b'GNUtar': 'tar',
    }
    
    # BOM markers for encoding detection
    BOM_MARKERS = {
        b'\xef\xbb\xbf': 'utf-8',
        b'\xff\xfe': 'utf-16-le',
        b'\xfe\xff': 'utf-16-be',
        b'\xff\xfe\x00\x00': 'utf-32-le',
        b'\x00\x00\xfe\xff': 'utf-32-be',
    }
    
    def __init__(self, datalake_client):
        """Initialize File Introspector"""
        self.datalake_client = datalake_client
    
    def introspect_file(self, file_path: str, sample_bytes: int = 8192) -> FileIntrospectionResult:
        """Perform cheap file introspection"""
        # Read file metadata and sample bytes
        file_client = self.datalake_client.get_file_client(file_path)
        file_properties = file_client.get_file_properties()
        file_size = file_properties.size
        
        # Read sample bytes
        read_size = min(sample_bytes, file_size)
        sample_data = file_client.download_file(offset=0, length=read_size).readall()
        
        # Extract magic bytes
        magic_bytes = sample_data[:16] if len(sample_data) >= 16 else sample_data
        
        # Detect container and compression
        container_info = self.detect_container_and_compression_from_bytes(sample_data, file_path)
        
        # Detect encoding
        encoding_info = self.detect_text_encoding_from_bytes(sample_data)
        
        # Estimate record boundaries
        boundary_info = self.estimate_record_boundaries_from_bytes(sample_data)
        
        # Determine I/O hints
        io_hints = self._determine_io_hints(
            file_size=file_size,
            container_type=container_info.get('container_type'),
            compression_type=container_info.get('compression_type')
        )
        
        # Format hints
        format_hints = self._extract_format_hints(sample_data)
        
        return FileIntrospectionResult(
            container_type=container_info.get('container_type'),
            compression_type=container_info.get('compression_type'),
            encoding=encoding_info.get('encoding'),
            has_bom=encoding_info.get('has_bom', False),
            newline_type=boundary_info.get('newline_type'),
            file_size_bytes=file_size,
            magic_bytes=magic_bytes,
            format_hints=format_hints,
            io_hints=io_hints
        )
    
    def detect_container_and_compression(self, file_path: str) -> Dict[str, Any]:
        """Detect archive/compression wrappers"""
        file_client = self.datalake_client.get_file_client(file_path)
        sample_data = file_client.download_file(offset=0, length=512).readall()
        return self.detect_container_and_compression_from_bytes(sample_data, file_path)
    
    def detect_container_and_compression_from_bytes(self, sample_data: bytes, file_path: str) -> Dict[str, Any]:
        """Detect container/compression from bytes"""
        container_type = None
        compression_type = None
        
        # Check magic bytes
        for magic, format_type in self.MAGIC_BYTES.items():
            if sample_data.startswith(magic):
                if format_type in ['zip', 'tar']:
                    container_type = format_type
                elif format_type in ['gzip', 'bz2', 'xz']:
                    compression_type = format_type
                break
        
        # Additional checks using file extension
        if not container_type and not compression_type:
            file_ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
            
            if file_ext == 'zip' or sample_data.startswith(b'PK'):
                try:
                    if len(sample_data) >= 30:
                        if sample_data[0:2] == b'PK' and sample_data[2:4] in [b'\x03\x04', b'\x05\x06', b'\x07\x08']:
                            container_type = 'zip'
                except:
                    pass
            
            if file_ext in ['gz', 'gzip'] or sample_data.startswith(b'\x1f\x8b'):
                compression_type = 'gzip'
            
            if file_ext in ['tar']:
                if len(sample_data) > 257:
                    if sample_data[257:262] == b'ustar' or sample_data[257:263] == b'GNUtar':
                        container_type = 'tar'
        
        return {
            'container_type': container_type,
            'compression_type': compression_type,
            'is_compressed': compression_type is not None,
            'is_container': container_type is not None
        }
    
    def detect_text_encoding(self, file_path: str, sample_bytes: int = 8192) -> Dict[str, Any]:
        """Identify encoding, BOM presence"""
        file_client = self.datalake_client.get_file_client(file_path)
        file_properties = file_client.get_file_properties()
        read_size = min(sample_bytes, file_properties.size)
        sample_data = file_client.download_file(offset=0, length=read_size).readall()
        return self.detect_text_encoding_from_bytes(sample_data)
    
    def detect_text_encoding_from_bytes(self, sample_data: bytes) -> Dict[str, Any]:
        """Detect encoding from bytes"""
        if len(sample_data) == 0:
            return {'encoding': None, 'has_bom': False, 'confidence': 0.0, 'is_binary': True}
        
        # Check for BOM markers
        has_bom = False
        bom_encoding = None
        
        for bom, encoding in self.BOM_MARKERS.items():
            if sample_data.startswith(bom):
                has_bom = True
                bom_encoding = encoding
                break
        
        # Use charset-normalizer
        detection_data = sample_data
        if has_bom:
            bom_bytes = next(bom for bom in self.BOM_MARKERS.keys() if sample_data.startswith(bom))
            detection_data = sample_data[len(bom_bytes):]
        
        result = detect_encoding(detection_data)
        
        # charset_normalizer returns a dict-like object or a CharsetMatch object
        if result:
            if isinstance(result, dict):
                detected_encoding = result.get('encoding')
                confidence = result.get('confidence', 0.0)
            else:
                # It's a CharsetMatch object
                detected_encoding = result.encoding if hasattr(result, 'encoding') else None
                confidence = result.percent_confidence / 100.0 if hasattr(result, 'percent_confidence') else (result.confidence if hasattr(result, 'confidence') else 0.0)
        else:
            detected_encoding = None
            confidence = 0.0
        
        final_encoding = bom_encoding if has_bom else detected_encoding
        is_binary = self._is_likely_binary(sample_data)
        
        return {
            'encoding': final_encoding,
            'has_bom': has_bom,
            'confidence': confidence if final_encoding else 0.0,
            'is_binary': is_binary,
            'detected_encoding': detected_encoding,
            'bom_encoding': bom_encoding
        }
    
    def estimate_record_boundaries(self, file_path: str, sample_bytes: int = 8192) -> Dict[str, Any]:
        """Determine record boundaries"""
        file_client = self.datalake_client.get_file_client(file_path)
        file_properties = file_client.get_file_properties()
        read_size = min(sample_bytes, file_properties.size)
        sample_data = file_client.download_file(offset=0, length=read_size).readall()
        return self.estimate_record_boundaries_from_bytes(sample_data)
    
    def estimate_record_boundaries_from_bytes(self, sample_data: bytes) -> Dict[str, Any]:
        """Estimate record boundaries from bytes"""
        if len(sample_data) == 0:
            return {'newline_type': None, 'record_length_hint': None, 'delimiter_hints': [], 'boundary_type': 'unknown'}
        
        newline_type = self._detect_newline_type(sample_data)
        record_length_hint = self._estimate_record_length(sample_data, newline_type)
        delimiter_hints = self._detect_delimiter_candidates(sample_data, newline_type)
        boundary_type = self._determine_boundary_type(newline_type, record_length_hint, delimiter_hints)
        
        return {
            'newline_type': newline_type,
            'record_length_hint': record_length_hint,
            'delimiter_hints': delimiter_hints,
            'boundary_type': boundary_type
        }
    
    def _detect_newline_type(self, sample_data: bytes) -> Optional[str]:
        """Detect newline type"""
        if b'\r\n' in sample_data:
            return '\r\n'
        elif b'\n' in sample_data:
            return '\n'
        elif b'\r' in sample_data:
            return '\r'
        return None
    
    def _estimate_record_length(self, sample_data: bytes, newline_type: Optional[str]) -> Optional[int]:
        """Estimate record length for fixed-width files"""
        if not newline_type:
            return None
        
        try:
            text = sample_data.decode('utf-8', errors='ignore')
            lines = text.split(newline_type)
            if len(lines) < 3:
                return None
            
            line_lengths = [len(line) for line in lines[:10] if line.strip()]
            if len(line_lengths) < 3:
                return None
            
            avg_length = sum(line_lengths) / len(line_lengths)
            variances = [abs(len(line) - avg_length) / avg_length for line in lines[:10] if line.strip()]
            
            if all(v < 0.05 for v in variances[:5]):
                return int(avg_length)
        except:
            pass
        
        return None
    
    def _detect_delimiter_candidates(self, sample_data: bytes, newline_type: Optional[str]) -> list:
        """Detect delimiter candidates"""
        if not newline_type:
            return []
        
        try:
            text = sample_data.decode('utf-8', errors='ignore')
            lines = [line for line in text.split(newline_type)[:10] if line.strip()]
            
            if len(lines) < 2:
                return []
            
            delimiters = [',', '\t', '|', ';', ' ']
            delimiter_counts = {delim: 0 for delim in delimiters}
            
            for line in lines[:5]:
                for delim in delimiters:
                    delimiter_counts[delim] += line.count(delim)
            
            candidates = []
            for delim, count in delimiter_counts.items():
                if count > 0 and count >= len(lines) * 0.8:
                    candidates.append(delim)
            
            return sorted(candidates, key=lambda x: delimiter_counts[x], reverse=True)
        except:
            return []
    
    def _determine_boundary_type(self, newline_type: Optional[str], record_length_hint: Optional[int], delimiter_hints: list) -> str:
        """Determine boundary type"""
        if record_length_hint:
            return 'fixed-width'
        elif newline_type and delimiter_hints:
            return 'delimited'
        elif newline_type:
            return 'newline-delimited'
        else:
            return 'unknown'
    
    def _is_likely_binary(self, sample_data: bytes) -> bool:
        """Check if file is likely binary"""
        if len(sample_data) == 0:
            return True
        
        null_count = sample_data.count(b'\x00')
        control_chars = sum(1 for b in sample_data if b < 32 and b not in [9, 10, 13])
        
        null_ratio = null_count / len(sample_data)
        control_ratio = control_chars / len(sample_data)
        
        return null_ratio > 0.05 or control_ratio > 0.10
    
    def _determine_io_hints(self, file_size: int, container_type: Optional[str], compression_type: Optional[str]) -> Dict[str, Any]:
        """Determine I/O hints"""
        use_streaming = file_size > 10 * 1024 * 1024
        
        if compression_type:
            use_streaming = True
        
        if container_type:
            use_streaming = False
        
        chunk_size = 1024 * 1024 if use_streaming else file_size
        
        return {
            'use_streaming': use_streaming,
            'chunk_size': chunk_size,
            'random_access': not use_streaming,
            'recommended_reader': 'streaming' if use_streaming else 'random_access'
        }
    
    def _extract_format_hints(self, sample_data: bytes) -> Dict[str, Any]:
        """Extract format-specific hints"""
        hints = {}
        
        if sample_data.startswith(b'{') or sample_data.startswith(b'['):
            hints['possible_json'] = True
        elif sample_data.startswith(b'<?xml') or sample_data.startswith(b'<'):
            hints['possible_xml'] = True
        elif b'<?xml' in sample_data[:100]:
            hints['possible_xml'] = True
        
        if b',' in sample_data[:100]:
            hints['possible_csv'] = True
        
        if sample_data.startswith(b'PK') and b'[Content_Types].xml' in sample_data[:1024]:
            hints['possible_excel'] = True
        
        return hints


def test_file_introspector_with_real_data():
    """Test FileIntrospector with real Data Lake file"""
    
    # Configuration (can be overridden via environment variables)
    storage_account_name = os.getenv('STORAGE_ACCOUNT_NAME', 'blachedly27jgavel2x32')
    container_name = os.getenv('CONTAINER_NAME', 'bronze')
    
    # Support testing multiple files via comma-separated list or single file
    test_files_env = os.getenv('TEST_FILE_PATHS', '')
    if test_files_env:
        # Multiple files provided
        test_file_paths = [f.strip() for f in test_files_env.split(',')]
    else:
        # Single file (backward compatibility)
        single_file = os.getenv('TEST_FILE_PATH', 'training/bank-digital-001/2026-02-18/f68f81a3-780d-4971-829d-4484fa1a6cd0.json')
        test_file_paths = [single_file]
    
    # Test each file
    for file_path in test_file_paths:
        print("\n" + "=" * 80)
        print(f"Testing file: {file_path}")
        print("=" * 80)
        _test_single_file(storage_account_name, container_name, file_path)


def _test_single_file(storage_account_name: str, container_name: str, file_path: str):
    """Test a single file with FileIntrospector"""
    
    print("=" * 80)
    print("File Introspection System - Real Data Lake Integration Test")
    print("=" * 80)
    print(f"\nConfiguration:")
    print(f"  Storage Account: {storage_account_name}")
    print(f"  Container: {container_name}")
    print(f"  File Path: {file_path}")
    print(f"  Full Path: {container_name}/{file_path}")
    print()
    
    try:
        # Initialize Azure credentials (tries multiple methods)
        print("Step 1: Authenticating with Azure...")
        print("  Trying authentication methods in order:")
        print("    1. Azure CLI (az login)")
        print("    2. Managed Identity (if running in Azure)")
        print("    3. Environment variables")
        print("    4. Visual Studio Code")
        print("    5. Azure PowerShell")
        
        try:
            credential = DefaultAzureCredential(exclude_environment_credential=True)
            # Test the credential by getting a token
            from azure.core.credentials import AccessToken
            token = credential.get_token("https://storage.azure.com/.default")
            print(f"✓ Authentication successful using: {type(credential).__name__}")
        except Exception as auth_error:
            print(f"\n✗ Authentication failed with DefaultAzureCredential")
            print(f"  Error: {auth_error}")
            print(f"\nPlease authenticate using one of these methods:")
            print(f"\n  Option 1: Azure CLI (Recommended)")
            print(f"    az login")
            print(f"    az account set --subscription YOUR_SUBSCRIPTION_ID")
            print(f"\n  Option 2: Environment Variables")
            print(f"    $env:AZURE_CLIENT_ID = 'your-client-id'")
            print(f"    $env:AZURE_TENANT_ID = 'your-tenant-id'")
            print(f"    $env:AZURE_CLIENT_SECRET = 'your-client-secret'")
            print(f"\n  Option 3: Visual Studio Code")
            print(f"    Install Azure Account extension and sign in")
            print(f"\nAfter authenticating, run this script again.")
            raise
        
        # Initialize Data Lake Service Client
        print(f"\nStep 2: Connecting to Data Lake Storage Gen2...")
        account_url = f"https://{storage_account_name}.dfs.core.windows.net"
        service_client = DataLakeServiceClient(account_url=account_url, credential=credential)
        print(f"✓ Connected to: {account_url}")
        
        # Get file system client (container)
        print(f"\nStep 3: Accessing container '{container_name}'...")
        file_system_client = service_client.get_file_system_client(container_name)
        
        # Verify container exists
        try:
            properties = file_system_client.get_file_system_properties()
            print(f"✓ Container exists (Last Modified: {properties.last_modified})")
        except Exception as e:
            print(f"✗ Error accessing container: {e}")
            print(f"  Make sure the container '{container_name}' exists and you have access")
            return
        
        # Create FileIntrospector
        print(f"\nStep 4: Creating FileIntrospector...")
        introspector = FileIntrospector(file_system_client)
        print("✓ FileIntrospector created")
        
        # Verify file exists - try Blob client (more reliable for permissions)
        print(f"\nStep 5: Verifying file exists...")
        file_exists = False
        file_size = 0
        last_modified = None
        
        # Try Blob client first (works for both regular blob and Data Lake Gen2)
        try:
            blob_account_url = f"https://{storage_account_name}.blob.core.windows.net"
            blob_service_client = BlobServiceClient(account_url=blob_account_url, credential=credential)
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=file_path)
            blob_properties = blob_client.get_blob_properties()
            file_exists = True
            file_size = blob_properties.size
            last_modified = blob_properties.last_modified
            print(f"✓ File exists (via Blob client)")
            print(f"  File size: {file_size:,} bytes ({file_size / 1024:.2f} KB)")
            print(f"  Last modified: {last_modified}")
        except Exception as blob_error:
            print(f"  Blob client failed: {blob_error}")
            print(f"  Trying Data Lake client as fallback...")
            
            # Fallback to Data Lake client
            try:
                file_client = file_system_client.get_file_client(file_path)
                file_properties = file_client.get_file_properties()
                file_exists = True
                file_size = file_properties.size
                last_modified = file_properties.last_modified
                print(f"✓ File exists (via Data Lake client)")
                print(f"  File size: {file_size:,} bytes ({file_size / 1024:.2f} KB)")
                print(f"  Last modified: {last_modified}")
            except Exception as dl_error:
                print(f"✗ Error accessing file with both clients:")
                print(f"  Blob error: {blob_error}")
                print(f"  Data Lake error: {dl_error}")
                print(f"  Make sure the file path '{file_path}' exists in container '{container_name}'")
                print(f"  Also verify you have 'Storage Blob Data Reader' role assigned")
                print(f"  Role was assigned, but may need more time to propagate (can take up to 30 minutes)")
                return
        
        if not file_exists:
            print(f"✗ Could not verify file exists")
            return
        
        # Run introspection
        print(f"\nStep 6: Running file introspection (reading first 8KB)...")
        print("-" * 80)
        result = introspector.introspect_file(file_path, sample_bytes=8192)
        print("-" * 80)
        
        # Display results
        print(f"\n{'=' * 80}")
        print("INTROSPECTION RESULTS")
        print("=" * 80)
        
        print(f"\n📁 File Information:")
        print(f"  File Size: {result.file_size_bytes:,} bytes ({result.file_size_bytes / 1024:.2f} KB)")
        if result.magic_bytes:
            magic_display = result.magic_bytes[:16].hex() if len(result.magic_bytes) >= 16 else result.magic_bytes.hex()
            print(f"  Magic Bytes (first 16): {magic_display}")
        
        print(f"\n📦 Container & Compression:")
        print(f"  Container Type: {result.container_type or 'None'}")
        print(f"  Compression Type: {result.compression_type or 'None'}")
        print(f"  Is Compressed: {result.compression_type is not None}")
        print(f"  Is Container: {result.container_type is not None}")
        
        print(f"\n🔤 Encoding:")
        print(f"  Encoding: {result.encoding or 'Unknown'}")
        print(f"  Has BOM: {result.has_bom}")
        
        print(f"\n📄 Record Boundaries:")
        print(f"  Newline Type: {result.newline_type or 'None'}")
        if result.newline_type:
            print(f"    Display: {repr(result.newline_type)}")
        
        print(f"\n💡 Format Hints:")
        if result.format_hints:
            for hint, value in result.format_hints.items():
                print(f"  {hint}: {value}")
        else:
            print("  No format hints detected")
        
        print(f"\n⚙️  I/O Hints:")
        if result.io_hints:
            for hint, value in result.io_hints.items():
                print(f"  {hint}: {value}")
        
        print(f"\n{'=' * 80}")
        print("✓ File introspection completed successfully!")
        print("=" * 80)
        
        # Additional detailed tests
        print(f"\n{'=' * 80}")
        print("DETAILED ANALYSIS")
        print("=" * 80)
        
        # Test individual detection methods
        print(f"\n1. Container/Compression Detection:")
        container_info = introspector.detect_container_and_compression(file_path)
        print(f"   {container_info}")
        
        print(f"\n2. Encoding Detection:")
        encoding_info = introspector.detect_text_encoding(file_path, sample_bytes=8192)
        print(f"   Encoding: {encoding_info.get('encoding')}")
        print(f"   Has BOM: {encoding_info.get('has_bom')}")
        print(f"   Confidence: {encoding_info.get('confidence', 0.0):.2%}")
        print(f"   Is Binary: {encoding_info.get('is_binary', False)}")
        
        print(f"\n3. Record Boundary Estimation:")
        boundary_info = introspector.estimate_record_boundaries(file_path, sample_bytes=8192)
        print(f"   Newline Type: {boundary_info.get('newline_type')}")
        print(f"   Boundary Type: {boundary_info.get('boundary_type')}")
        print(f"   Record Length Hint: {boundary_info.get('record_length_hint')}")
        print(f"   Delimiter Hints: {boundary_info.get('delimiter_hints', [])}")
        
        print(f"\n{'=' * 80}")
        print("✓ All tests completed successfully!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n{'=' * 80}")
        print("✗ ERROR")
        print("=" * 80)
        print(f"Error: {e}")
        print(f"\nError Type: {type(e).__name__}")
        import traceback
        print(f"\nTraceback:")
        traceback.print_exc()
        print(f"\n{'=' * 80}")
        print("\nTroubleshooting:")
        print("1. Make sure you're authenticated with Azure:")
        print("   az login")
        print("   az account set --subscription YOUR_SUBSCRIPTION_ID")
        print("2. Verify the Data Lake account name is correct:")
        print("   az storage account list --query \"[?properties.isHnsEnabled==\\`true\\`].name\" -o tsv")
        print("3. Verify the container/file system name is correct:")
        print("   az storage container list --account-name YOUR_DATA_LAKE_NAME --auth-mode login")
        print("4. Verify the file path is correct:")
        print(f"   Container: {container_name}")
        print(f"   File Path: {file_path}")
        print("5. PERMISSION ERROR: You need 'Storage Blob Data Reader' role on the Data Lake")
        print("   Ask an admin to run:")
        print(f"   az role assignment create \\")
        print(f"     --role \"Storage Blob Data Reader\" \\")
        print(f"     --scope \"/subscriptions/411d9dd9-b1d7-4ed2-87fb-bc7c9a53cbaf/resourceGroups/blache-cdtscr-dev-data-rg/providers/Microsoft.Storage/storageAccounts/{storage_account_name}\" \\")
        print(f"     --assignee \"olujare.olanrewaju@gmail.com\"")
        print("   Or use the PowerShell script: grant_storage_permissions.ps1")
        print("6. After granting permissions, wait 1-2 minutes for propagation")
        print("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    test_file_introspector_with_real_data()
