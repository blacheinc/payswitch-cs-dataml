"""
Storage Client Utility
Handles blob storage and data lake operations for file copying
"""

import logging
import io
from datetime import datetime
from typing import Optional
from azure.storage.blob import BlobServiceClient
from azure.storage.filedatalake import DataLakeServiceClient, FileSystemClient
from azure.identity import DefaultAzureCredential, AzureCliCredential
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

logger = logging.getLogger(__name__)


class StorageClient:
    """Client for Azure Blob Storage and Data Lake operations"""
    
    def __init__(
        self,
        blob_storage_account_name: Optional[str] = None,
        datalake_storage_account_name: Optional[str] = None,
        blob_connection_string: Optional[str] = None,
        datalake_connection_string: Optional[str] = None,
        credential=None,
        env: str = "local"
    ):
        """
        Initialize Storage Client
        
        Args:
            blob_storage_account_name: Blob storage account name
            datalake_storage_account_name: Data Lake storage account name
            blob_connection_string: Blob storage connection string (optional)
            datalake_connection_string: Data Lake connection string (optional)
            credential: Azure credential (defaults based on env)
            env: Environment ('local' or 'prod')
        """
        self.env = env
        self.credential = credential
        self.blob_connection_string = blob_connection_string
        self.datalake_connection_string = datalake_connection_string
        
        if not self.credential:
            if env == "local":
                self.credential = AzureCliCredential()
            else:
                self.credential = DefaultAzureCredential()
        
        # Initialize blob storage client (for reading from source)
        # In Azure: Try Managed Identity first, fall back to connection string
        # In Local: Prefer connection string if provided, otherwise use credential
        if env == "azure" and blob_storage_account_name:
            # Try Managed Identity first
            try:
                account_url = f"https://{blob_storage_account_name}.blob.core.windows.net"
                test_client = BlobServiceClient(account_url=account_url, credential=self.credential)
                # Test with a lightweight operation (list containers - iterate first item only)
                try:
                    next(iter(test_client.list_containers()), None)
                except Exception:
                    # If list fails, try to create the client anyway - actual operations will handle fallback
                    pass
                self.blob_service_client = test_client
                logger.info("Blob storage client initialized with Managed Identity")
            except Exception as e:
                logger.warning(f"Failed to initialize blob storage client with Managed Identity: {str(e)}")
                if blob_connection_string:
                    logger.info("Falling back to connection string for blob storage")
                    self.blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)
                else:
                    logger.error("Managed Identity failed and no connection string provided for blob storage")
                    raise ValueError(f"Cannot initialize blob storage client: {str(e)}")
        elif blob_connection_string:
            # Local or explicit connection string preference
            self.blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)
            logger.info("Blob storage client initialized with connection string")
        elif blob_storage_account_name:
            # Local with credential only
            account_url = f"https://{blob_storage_account_name}.blob.core.windows.net"
            self.blob_service_client = BlobServiceClient(account_url=account_url, credential=self.credential)
            logger.info("Blob storage client initialized with credential")
        else:
            self.blob_service_client = None
        
        # Initialize data lake blob service client (for writing to data lake via Blob API)
        # This is separate from blob_service_client because they point to different storage accounts
        # In Azure: Try Managed Identity first, fall back to connection string
        # In Local: Prefer connection string if provided, otherwise use credential
        if env == "azure" and datalake_storage_account_name:
            # Try Managed Identity first
            try:
                account_url = f"https://{datalake_storage_account_name}.blob.core.windows.net"
                test_client = BlobServiceClient(account_url=account_url, credential=self.credential)
                # Test with a lightweight operation (list containers - iterate first item only)
                try:
                    next(iter(test_client.list_containers()), None)
                except Exception:
                    # If list fails, try to create the client anyway - actual operations will handle fallback
                    pass
                self.datalake_blob_service_client = test_client
                logger.info("Data Lake blob service client initialized with Managed Identity")
            except Exception as e:
                logger.warning(f"Failed to initialize data lake blob service client with Managed Identity: {str(e)}")
                if datalake_connection_string:
                    logger.info("Falling back to connection string for data lake")
                    self.datalake_blob_service_client = BlobServiceClient.from_connection_string(datalake_connection_string)
                else:
                    logger.error("Managed Identity failed and no connection string provided for data lake")
                    raise ValueError(f"Cannot initialize data lake blob service client: {str(e)}")
        elif datalake_connection_string:
            # Local or explicit connection string preference
            self.datalake_blob_service_client = BlobServiceClient.from_connection_string(datalake_connection_string)
            logger.info("Data Lake blob service client initialized with connection string")
        elif datalake_storage_account_name:
            # Local with credential only
            account_url = f"https://{datalake_storage_account_name}.blob.core.windows.net"
            self.datalake_blob_service_client = BlobServiceClient(account_url=account_url, credential=self.credential)
            logger.info("Data Lake blob service client initialized with credential")
        else:
            self.datalake_blob_service_client = None
        
        # Initialize data lake client (for DFS API - not currently used but kept for future)
        # In Azure: Try Managed Identity first, fall back to connection string
        # In Local: Prefer connection string if provided, otherwise use credential
        if env == "azure" and datalake_storage_account_name:
            # Try Managed Identity first
            try:
                account_url = f"https://{datalake_storage_account_name}.dfs.core.windows.net"
                self.datalake_service_client = DataLakeServiceClient(account_url=account_url, credential=self.credential)
                logger.info("Data Lake DFS client initialized with Managed Identity")
            except Exception as e:
                logger.warning(f"Failed to initialize Data Lake DFS client with Managed Identity: {str(e)}")
                if datalake_connection_string:
                    logger.info("Falling back to connection string for Data Lake DFS client")
                    self.datalake_service_client = DataLakeServiceClient.from_connection_string(datalake_connection_string)
                else:
                    logger.warning("Managed Identity failed and no connection string provided for Data Lake DFS client")
                    self.datalake_service_client = None
        elif datalake_connection_string:
            # Local or explicit connection string preference
            try:
                self.datalake_service_client = DataLakeServiceClient.from_connection_string(datalake_connection_string)
                logger.info("Data Lake DFS client initialized with connection string")
            except Exception as e:
                logger.error(f"Failed to initialize Data Lake DFS client with connection string: {e}")
                raise
        elif datalake_storage_account_name:
            # Local with credential only
            account_url = f"https://{datalake_storage_account_name}.dfs.core.windows.net"
            self.datalake_service_client = DataLakeServiceClient(account_url=account_url, credential=self.credential)
            logger.info("Data Lake DFS client initialized with credential")
        else:
            self.datalake_service_client = None
        
        logger.info("Storage Client initialized")
    
    def copy_blob_to_datalake(
        self,
        source_container: str,
        source_blob_path: str,
        destination_filesystem: str,
        destination_path: str,
        overwrite: bool = True
    ) -> tuple[bool, str]:
        """
        Copy file from blob storage to data lake
        
        Args:
            source_container: Source blob container name
            source_blob_path: Source blob path (e.g., "bank_id/upload_id.csv")
            destination_filesystem: Destination data lake file system (e.g., "bronze")
            destination_path: Destination path (e.g., "training/bank_id/2026-03-10/upload_id.csv")
            overwrite: Whether to overwrite if file exists
            
        Returns:
            (used_blob_api: bool, bronze_path: str)
            - used_blob_api: True if Blob API was used, False if DFS API was used
            - bronze_path: The full path to the bronze file (for checksum calculation)
            
        Raises:
            ValueError: If clients are not initialized
            Exception: If copy operation fails
            
        Note:
            Azure SDK automatically retries transient failures (network errors, throttling, etc.)
            with exponential backoff. No explicit retry logic is needed.
        """
        if not self.blob_service_client:
            raise ValueError("Blob service client not initialized")
        
        logger.info(f"Copying blob '{source_container}/{source_blob_path}' to data lake '{destination_filesystem}/{destination_path}'")
        
        # Helper function to perform the copy operation with given clients
        def _perform_copy(source_client, dest_client, dest_container_client):
            # Check if source blob exists
            source_blob_client = source_client.get_blob_client(
                container=source_container,
                blob=source_blob_path
            )
            if not source_blob_client.exists():
                raise FileNotFoundError(f"Source blob not found: {source_container}/{source_blob_path}")
            
            # Download file content
            logger.info("Downloading from blob storage...")
            download_stream = source_blob_client.download_blob()
            file_content = download_stream.readall()
            
            # Upload to destination
            logger.info(f"Uploading to data lake via Blob API ({len(file_content)} bytes)...")
            destination_blob_client = dest_client.get_blob_client(
                container=destination_filesystem,
                blob=destination_path
            )
            
            # Ensure container exists
            if not dest_container_client.exists():
                logger.info(f"Container '{destination_filesystem}' does not exist. Creating it...")
                dest_container_client.create_container()
            
            destination_blob_client.upload_blob(data=file_content, overwrite=overwrite)
            
            # Verify the file was actually written
            if not destination_blob_client.exists():
                raise Exception(f"File upload reported success but file does not exist: {destination_filesystem}/{destination_path}")
            
            bronze_path = f"{destination_filesystem}/{destination_path}"
            logger.info(f"Successfully copied file to '{bronze_path}' using Blob API")
            return bronze_path
        
        if not self.datalake_blob_service_client:
            raise ValueError("Data Lake blob service client not initialized. Cannot write to data lake.")
        
        try:
            # Try with current clients (Managed Identity if in Azure)
            container_client = self.datalake_blob_service_client.get_container_client(container=destination_filesystem)
            bronze_path = _perform_copy(self.blob_service_client, self.datalake_blob_service_client, container_client)
            return (True, bronze_path)
            
        except HttpResponseError as auth_error:
            # If authorization error in Azure and we have connection strings, retry with connection strings
            if (self.env == "azure" and 
                ("AuthorizationPermissionMismatch" in str(auth_error) or 
                 "AuthorizationFailure" in str(auth_error) or
                 auth_error.error_code in ["AuthorizationPermissionMismatch", "AuthorizationFailure"])):
                logger.warning(f"Authorization error with current auth method ({auth_error.error_code}), retrying with connection strings...")
                
                # Retry with connection strings
                if not self.blob_connection_string:
                    raise ValueError("Authorization failed and no blob connection string available for fallback")
                if not self.datalake_connection_string:
                    raise ValueError("Authorization failed and no data lake connection string available for fallback")
                
                # Create new clients with connection strings
                blob_service_client_fallback = BlobServiceClient.from_connection_string(self.blob_connection_string)
                datalake_blob_service_client_fallback = BlobServiceClient.from_connection_string(self.datalake_connection_string)
                
                # Retry the operation with connection strings
                container_client_fallback = datalake_blob_service_client_fallback.get_container_client(container=destination_filesystem)
                bronze_path = _perform_copy(blob_service_client_fallback, datalake_blob_service_client_fallback, container_client_fallback)
                logger.info("Successfully completed copy operation using connection string fallback")
                return (True, bronze_path)
            else:
                raise
        except Exception as e:
            logger.error(f"Error copying file: {str(e)}", exc_info=True)
            raise
    
    def get_file_size(self, filesystem: str, file_path: str, use_blob_api: bool = False) -> int:
        """
        Get file size from data lake
        
        Args:
            filesystem: File system name
            file_path: File path within file system
            use_blob_api: If True, use Blob API. If False, use DFS API.
            
        Returns:
            File size in bytes
        """
        if use_blob_api:
            # Use Blob API (same as what was used to write the file)
            # IMPORTANT: Use datalake_blob_service_client, not blob_service_client (different storage accounts!)
            if not self.datalake_blob_service_client:
                raise ValueError("Data Lake blob service client not initialized")
            
            try:
                blob_client = self.datalake_blob_service_client.get_blob_client(
                    container=filesystem,
                    blob=file_path
                )
                properties = blob_client.get_blob_properties()
                return properties.size
            except HttpResponseError as auth_error:
                # If authorization error in Azure and we have connection string, retry with connection string
                if (self.env == "azure" and 
                    ("AuthorizationPermissionMismatch" in str(auth_error) or 
                     "AuthorizationFailure" in str(auth_error) or
                     auth_error.error_code in ["AuthorizationPermissionMismatch", "AuthorizationFailure"])):
                    logger.warning(f"Authorization error getting file size ({auth_error.error_code}), retrying with connection string...")
                    
                    if not self.datalake_connection_string:
                        raise ValueError("Authorization failed and no data lake connection string available for fallback")
                    
                    # Create new client with connection string
                    datalake_blob_service_client_fallback = BlobServiceClient.from_connection_string(self.datalake_connection_string)
                    blob_client = datalake_blob_service_client_fallback.get_blob_client(
                        container=filesystem,
                        blob=file_path
                    )
                    properties = blob_client.get_blob_properties()
                    return properties.size
                else:
                    raise
        else:
            # Use DFS API
            if not self.datalake_service_client:
                raise ValueError("Data Lake service client not initialized")
            
            try:
                fs_client = self.datalake_service_client.get_file_system_client(file_system=filesystem)
                file_client = fs_client.get_file_client(file_path=file_path)
                properties = file_client.get_file_properties()
                return properties.size
            except HttpResponseError as auth_error:
                # If authorization error in Azure and we have connection string, retry with connection string
                if (self.env == "azure" and 
                    ("AuthorizationPermissionMismatch" in str(auth_error) or 
                     "AuthorizationFailure" in str(auth_error) or
                     auth_error.error_code in ["AuthorizationPermissionMismatch", "AuthorizationFailure"])):
                    logger.warning(f"Authorization error getting file size via DFS ({auth_error.error_code}), retrying with connection string...")
                    
                    if not self.datalake_connection_string:
                        raise ValueError("Authorization failed and no data lake connection string available for fallback")
                    
                    # Fall back to Blob API with connection string
                    datalake_blob_service_client_fallback = BlobServiceClient.from_connection_string(self.datalake_connection_string)
                    blob_client = datalake_blob_service_client_fallback.get_blob_client(
                        container=filesystem,
                        blob=file_path
                    )
                    properties = blob_client.get_blob_properties()
                    return properties.size
                else:
                    raise
    
    def delete_file(self, filesystem: str, file_path: str) -> None:
        """
        Delete file from data lake
        
        Args:
            filesystem: File system name
            file_path: File path within file system
        """
        try:
            if self.datalake_service_client:
                fs_client = self.datalake_service_client.get_file_system_client(file_system=filesystem)
                file_client = fs_client.get_file_client(file_path=file_path)
                file_client.delete_file()
                logger.info(f"Deleted file '{filesystem}/{file_path}'")
                return
            else:
                raise ValueError("Data Lake service client not initialized")
        except HttpResponseError as e:
            # If DFS endpoint doesn't support account features, use Blob API instead
            if "EndpointUnsupportedAccountFeatures" in str(e) or e.error_code == "EndpointUnsupportedAccountFeatures":
                logger.warning(f"DFS endpoint not supported, using Blob API for file deletion")
                if not self.datalake_blob_service_client:
                    raise ValueError("Data Lake blob service client not initialized")
                blob_client = self.datalake_blob_service_client.get_blob_client(
                    container=filesystem,
                    blob=file_path
                )
                blob_client.delete_blob()
                logger.info(f"Deleted file '{filesystem}/{file_path}' using Blob API")
                return
            else:
                raise
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}", exc_info=True)
            raise
