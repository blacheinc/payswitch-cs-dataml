"""
File Checksum Calculator - Azure Function
Calculates SHA-256 checksum for files stored in Azure Blob Storage or Data Lake

This function:
- Accepts blob URL or storage path as input
- Downloads the file from Blob Storage/Data Lake
- Calculates SHA-256 hash
- Returns the checksum value

Used by Azure Data Factory for file integrity verification
"""

import azure.functions as func
import logging
import json
import hashlib
import os
from typing import Dict, Any, Optional
from azure.storage.blob import BlobServiceClient
from azure.storage.filedatalake import DataLakeServiceClient
from azure.identity import DefaultAzureCredential

# Configure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

class Config:
    """Configuration from environment variables"""
    
    # Storage account names (can be passed in request or from env)
    STORAGE_ACCOUNT_NAME = os.getenv('STORAGE_ACCOUNT_NAME', '')
    DATA_LAKE_ACCOUNT_NAME = os.getenv('DATA_LAKE_ACCOUNT_NAME', '')

# ============================================================
# Checksum Calculator Service
# ============================================================

class ChecksumCalculator:
    """Calculate SHA-256 checksum for Azure Storage files"""
    
    def __init__(self):
        """Initialize the Checksum Calculator"""
        self.config = Config()
        self.credential = DefaultAzureCredential()
        logger.info("Checksum Calculator initialized")
    
    def _parse_blob_url(self, blob_url: str) -> Dict[str, str]:
        """
        Parse blob URL to extract account name, container, and blob path
        
        Args:
            blob_url: Full blob URL (e.g., https://account.blob.core.windows.net/container/path/file.ext)
                     or Data Lake URL (e.g., https://account.dfs.core.windows.net/container/path/file.ext)
            
        Returns:
            Dictionary with account_name, container, blob_path
        """
        try:
            # Remove protocol
            url = blob_url.replace('https://', '').replace('http://', '')
            
            # Check if it's Data Lake (dfs.core.windows.net) or Blob Storage (blob.core.windows.net)
            if '.dfs.core.windows.net' in url:
                account_name = url.split('.dfs.core.windows.net')[0]
                path_part = url.split('.dfs.core.windows.net/')[1]
            elif '.blob.core.windows.net' in url:
                account_name = url.split('.blob.core.windows.net')[0]
                path_part = url.split('.blob.core.windows.net/')[1]
            else:
                raise ValueError(f"Invalid blob URL format: {blob_url}")
            
            # Split container and blob path
            parts = path_part.split('/', 1)
            container = parts[0]
            blob_path = parts[1] if len(parts) > 1 else ''
            
            return {
                'account_name': account_name,
                'container': container,
                'blob_path': blob_path
            }
        except Exception as e:
            logger.error(f"Error parsing blob URL: {str(e)}")
            raise ValueError(f"Invalid blob URL format: {blob_url}")
    
    def _get_blob_client(self, account_name: str, container: str, blob_path: str, is_data_lake: bool = False):
        """
        Get blob client for downloading file
        
        Args:
            account_name: Storage account name
            container: Container name
            blob_path: Path to blob within container
            is_data_lake: Whether this is Data Lake Gen2
            
        Returns:
            Blob client
        """
        account_url = f"https://{account_name}.{'dfs' if is_data_lake else 'blob'}.core.windows.net"
        
        if is_data_lake:
            service_client = DataLakeServiceClient(account_url=account_url, credential=self.credential)
            file_system_client = service_client.get_file_system_client(file_system=container)
            return file_system_client.get_file_client(file_path=blob_path)
        else:
            blob_service_client = BlobServiceClient(account_url=account_url, credential=self.credential)
            container_client = blob_service_client.get_container_client(container=container)
            return container_client.get_blob_client(blob=blob_path)
    
    def calculate_checksum(self, blob_url: str) -> str:
        """
        Calculate SHA-256 checksum for a file in Azure Storage
        
        Args:
            blob_url: Full URL to the blob file
            
        Returns:
            SHA-256 checksum as hexadecimal string
        """
        logger.info(f"Calculating checksum for: {blob_url}")
        
        try:
            # Parse URL
            parsed = self._parse_blob_url(blob_url)
            account_name = parsed['account_name']
            container = parsed['container']
            blob_path = parsed['blob_path']
            
            # Determine if Data Lake or Blob Storage
            is_data_lake = '.dfs.core.windows.net' in blob_url or account_name.endswith('dfs')
            
            # Get blob client
            if is_data_lake:
                file_client = self._get_blob_client(account_name, container, blob_path, is_data_lake=True)
                # Download file content
                download_response = file_client.download_file()
                file_content = download_response.readall()
            else:
                blob_client = self._get_blob_client(account_name, container, blob_path, is_data_lake=False)
                # Download file content
                download_stream = blob_client.download_blob()
                file_content = download_stream.readall()
            
            # Calculate SHA-256 hash
            sha256_hash = hashlib.sha256(file_content).hexdigest()
            
            logger.info(f"Checksum calculated successfully: {sha256_hash[:16]}...")
            return sha256_hash
            
        except Exception as e:
            logger.error(f"Error calculating checksum: {str(e)}", exc_info=True)
            raise

# ============================================================
# Azure Function Entry Point
# ============================================================

app = func.FunctionApp()

@app.route(route="calculate_checksum", methods=["GET", "POST"], auth_level=func.AuthLevel.FUNCTION)
def calculate_checksum_http(req: func.HttpRequest) -> func.HttpResponse:
    """
    Azure Function HTTP endpoint to calculate file checksum
    
    Query parameters or JSON body:
    - blob_url: Full URL to the blob file (required)
    
    Returns:
    - JSON with checksum value
    """
    try:
        # Get blob_url from query params or request body
        blob_url = req.params.get('blob_url')
        
        if not blob_url:
            try:
                req_body = req.get_json()
                blob_url = req_body.get('blob_url')
            except ValueError:
                pass
        
        if not blob_url:
            return func.HttpResponse(
                json.dumps({"error": "Missing required parameter: blob_url"}),
                status_code=400,
                mimetype="application/json"
            )
        
        logger.info(f"Received checksum calculation request for: {blob_url}")
        
        # Initialize calculator
        calculator = ChecksumCalculator()
        
        # Calculate checksum
        checksum = calculator.calculate_checksum(blob_url)
        
        # Return result
        result = {
            "checksum": checksum,
            "blob_url": blob_url,
            "algorithm": "SHA-256"
        }
        
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json"
        )
        
    except ValueError as e:
        logger.error(f"Invalid request: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=400,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return func.HttpResponse(
            json.dumps({"error": f"Internal server error: {str(e)}"}),
            status_code=500,
            mimetype="application/json"
        )
