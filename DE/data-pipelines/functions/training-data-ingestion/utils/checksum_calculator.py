"""
Checksum Calculator Utility
Embedded checksum calculation logic from file-checksum-calculator Azure Function
Calculates SHA-256 checksum for files in Azure Blob Storage or Data Lake
"""

import logging
import hashlib
from typing import Dict, Optional
from azure.storage.blob import BlobServiceClient
from azure.storage.filedatalake import DataLakeServiceClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import HttpResponseError

logger = logging.getLogger(__name__)


class ChecksumCalculator:
    """Calculate SHA-256 checksum for Azure Storage files"""
    
    def __init__(
        self, 
        credential=None, 
        blob_connection_string: Optional[str] = None, 
        datalake_connection_string: Optional[str] = None,
        datalake_storage_account_name: Optional[str] = None,
        env: str = "local"
    ):
        """
        Initialize the Checksum Calculator
        
        Args:
            credential: Azure credential (defaults based on env)
            blob_connection_string: Blob storage connection string (optional, used as fallback in Azure)
            datalake_connection_string: Data Lake connection string (optional, used as fallback in Azure)
            datalake_storage_account_name: Data Lake storage account name (used to determine which connection string to use)
            env: Environment ('local' or 'azure')
        """
        self.env = env
        self.credential = credential
        self.blob_connection_string = blob_connection_string
        self.datalake_connection_string = datalake_connection_string
        self.datalake_storage_account_name = datalake_storage_account_name
        
        if not self.credential:
            if env == "local":
                # Local: prefer connection strings, but can use Azure CLI credential
                if not blob_connection_string and not datalake_connection_string:
                    from azure.identity import AzureCliCredential
                    self.credential = AzureCliCredential()
            else:
                # Azure: use Managed Identity (DefaultAzureCredential)
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
            Blob client or file client
        """
        # In Azure: Try Managed Identity first, fall back to connection string
        # In Local: Prefer connection string if provided, otherwise use credential
        if is_data_lake:
            if self.env == "azure" and self.credential:
                # Try Managed Identity first
                try:
                    account_url = f"https://{account_name}.dfs.core.windows.net"
                    service_client = DataLakeServiceClient(account_url=account_url, credential=self.credential)
                    file_system_client = service_client.get_file_system_client(file_system=container)
                    return file_system_client.get_file_client(file_path=blob_path)
                except Exception as e:
                    logger.warning(f"Failed to get Data Lake client with Managed Identity: {str(e)}")
                    if self.datalake_connection_string:
                        logger.info("Falling back to connection string for Data Lake client")
                        service_client = DataLakeServiceClient.from_connection_string(self.datalake_connection_string)
                        file_system_client = service_client.get_file_system_client(file_system=container)
                        return file_system_client.get_file_client(file_path=blob_path)
                    else:
                        raise
            elif self.datalake_connection_string:
                # Local or explicit connection string preference
                service_client = DataLakeServiceClient.from_connection_string(self.datalake_connection_string)
                file_system_client = service_client.get_file_system_client(file_system=container)
                return file_system_client.get_file_client(file_path=blob_path)
            else:
                # Local with credential only
                account_url = f"https://{account_name}.dfs.core.windows.net"
                service_client = DataLakeServiceClient(account_url=account_url, credential=self.credential)
                file_system_client = service_client.get_file_system_client(file_system=container)
                return file_system_client.get_file_client(file_path=blob_path)
        else:
            # Blob Storage
            # If account name matches data lake account, use datalake connection string even for blob URLs
            # (because files written via Blob API to data lake still use .blob.core.windows.net URLs)
            is_datalake_account = (self.datalake_storage_account_name and 
                                   account_name == self.datalake_storage_account_name)
            
            if self.env == "azure" and self.credential:
                # Try Managed Identity first
                try:
                    account_url = f"https://{account_name}.blob.core.windows.net"
                    blob_service_client = BlobServiceClient(account_url=account_url, credential=self.credential)
                    container_client = blob_service_client.get_container_client(container=container)
                    return container_client.get_blob_client(blob=blob_path)
                except Exception as e:
                    logger.warning(f"Failed to get Blob Storage client with Managed Identity: {str(e)}")
                    # Fall back to connection string
                    if is_datalake_account and self.datalake_connection_string:
                        logger.info("Falling back to data lake connection string for blob client")
                        blob_service_client = BlobServiceClient.from_connection_string(self.datalake_connection_string)
                    elif self.blob_connection_string:
                        logger.info("Falling back to blob connection string for blob client")
                        blob_service_client = BlobServiceClient.from_connection_string(self.blob_connection_string)
                    else:
                        raise
                    container_client = blob_service_client.get_container_client(container=container)
                    return container_client.get_blob_client(blob=blob_path)
            elif is_datalake_account and self.datalake_connection_string:
                # Use data lake connection string to create blob client for data lake account
                blob_service_client = BlobServiceClient.from_connection_string(self.datalake_connection_string)
            elif self.blob_connection_string:
                blob_service_client = BlobServiceClient.from_connection_string(self.blob_connection_string)
            else:
                account_url = f"https://{account_name}.blob.core.windows.net"
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
            # If account name matches data lake account, treat as data lake even if URL uses .blob.core.windows.net
            is_data_lake = (
                '.dfs.core.windows.net' in blob_url or 
                account_name.endswith('dfs') or
                (self.datalake_storage_account_name and account_name == self.datalake_storage_account_name)
            )
            
            # Get blob client and download (with fallback on authorization errors)
            try:
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
            except HttpResponseError as auth_error:
                # If authorization error and we're in Azure, try falling back to connection string explicitly
                if (self.env == "azure" and 
                    ("AuthorizationPermissionMismatch" in str(auth_error) or 
                     "AuthorizationFailure" in str(auth_error) or
                     auth_error.error_code in ["AuthorizationPermissionMismatch", "AuthorizationFailure"])):
                    logger.warning(f"Authorization error with current auth method ({auth_error.error_code}), retrying with connection string...")
                    # Force use of connection string by temporarily clearing credential
                    original_credential = self.credential
                    self.credential = None
                    try:
                        if is_data_lake:
                            file_client = self._get_blob_client(account_name, container, blob_path, is_data_lake=True)
                            download_response = file_client.download_file()
                            file_content = download_response.readall()
                        else:
                            blob_client = self._get_blob_client(account_name, container, blob_path, is_data_lake=False)
                            download_stream = blob_client.download_blob()
                            file_content = download_stream.readall()
                    finally:
                        self.credential = original_credential
                else:
                    raise
            
            # Calculate SHA-256 hash
            sha256_hash = hashlib.sha256(file_content).hexdigest()
            
            logger.info(f"Checksum calculated successfully: {sha256_hash[:16]}...")
            return sha256_hash
            
        except Exception as e:
            logger.error(f"Error calculating checksum: {str(e)}", exc_info=True)
            raise
