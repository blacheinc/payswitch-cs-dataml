"""
ADF Pipeline Trigger Script
Retrieves Key Vault secrets and triggers ADF pipeline via REST API
"""

import json
import logging
import os
import uuid
from typing import Any, Dict, Optional

try:
    from azure.identity import DefaultAzureCredential, AzureCliCredential
    from azure.keyvault.secrets import SecretClient
    from azure.core.exceptions import AzureError
    from azure.mgmt.datafactory import DataFactoryManagementClient
    DEPENDENCIES_AVAILABLE = True
except ImportError as e:
    DEPENDENCIES_AVAILABLE = False
    logging.warning(f"Some dependencies not available: {e}")

logger = logging.getLogger(__name__)


class KeyVaultReader:
    """Simple Key Vault reader for this function"""
    
    def __init__(self, key_vault_url: str, credential=None):
        """Initialize Key Vault reader"""
        if not DEPENDENCIES_AVAILABLE:
            raise ImportError("Azure SDK dependencies not available")
        
        if not key_vault_url:
            raise ValueError("key_vault_url is required")
        
        # Ensure URL doesn't end with /
        if key_vault_url.endswith('/'):
            key_vault_url = key_vault_url.rstrip('/')
        
        self.key_vault_url = key_vault_url
        self._credential = credential or DefaultAzureCredential()
        self._client = None
    
    @property
    def client(self):
        """Lazy initialization of SecretClient"""
        if self._client is None:
            from azure.keyvault.secrets import SecretClient
            self._client = SecretClient(vault_url=self.key_vault_url, credential=self._credential)
        return self._client
    
    def get_secret(self, secret_name: str) -> str:
        """Get secret from Key Vault"""
        try:
            secret = self.client.get_secret(secret_name)
            return secret.value
        except Exception as e:
            logger.error(f"Failed to retrieve secret '{secret_name}' from Key Vault: {str(e)}")
            raise


def get_environment() -> str:
    """Determine environment (local or azure)"""
    env = os.getenv("ENVIRONMENT", "local").lower()
    if env not in ["local", "azure"]:
        env = "local"
    return env


def trigger_adf_pipeline_from_message(
    message_data: Dict[str, Any],
    key_vault_url: str,
    subscription_id: str,
    resource_group: str,
    factory_name: str,
    pipeline_name: str
) -> Optional[Dict[str, Any]]:
    """
    Trigger ADF pipeline with parameters from Service Bus message and Key Vault
    
    Args:
        message_data: Parsed Service Bus message body
        key_vault_url: Key Vault URL
        subscription_id: Azure subscription ID
        resource_group: Resource group name
        factory_name: Data Factory name
        pipeline_name: Pipeline name
    
    Returns:
        Dict with runId if successful, None otherwise
    """
    env = get_environment()
    
    # Initialize credential
    if env == "local":
        credential = AzureCliCredential()
    else:
        credential = DefaultAzureCredential()
    
    # Initialize Key Vault reader
    try:
        kv_reader = KeyVaultReader(key_vault_url=key_vault_url, credential=credential)
    except Exception as e:
        logger.error(f"Failed to initialize Key Vault reader: {str(e)}")
        return None
    
    # Retrieve Key Vault secrets
    logger.info("Retrieving Key Vault secrets...")
    try:
        service_bus_namespace = kv_reader.get_secret("ServiceBusNamespace")
        logger.info("Retrieved ServiceBusNamespace from Key Vault")
        
        file_checksum_base_url = kv_reader.get_secret("FileChecksumCalculatorFunctionBaseUrl")
        logger.info("Retrieved FileChecksumCalculatorFunctionBaseUrl from Key Vault")
        
        file_checksum_key = kv_reader.get_secret("FileChecksumCalculatorFunctionKey")
        logger.info("Retrieved FileChecksumCalculatorFunctionKey from Key Vault")
    except Exception as e:
        logger.error(f"Failed to retrieve Key Vault secrets: {str(e)}")
        return None
    
    # Extract message data
    training_upload_id = message_data.get("training_upload_id")
    data_source_id = message_data.get("data_source_id")
    file_format = message_data.get("file_format")
    file_size_bytes = message_data.get("file_size_bytes")
    raw_file_path = message_data.get("raw_file_path")
    
    if not training_upload_id:
        logger.error("Missing required field: training_upload_id")
        return None
    
    # Generate run_id (UUID)
    run_id = str(uuid.uuid4())
    logger.info(f"Generated run_id: {run_id}")
    
    # Prepare ADF pipeline parameters
    pipeline_parameters = {
        "training_upload_id": training_upload_id,
        "data_source_id": data_source_id,
        "file_format": file_format,
        "file_size_bytes": file_size_bytes,
        "raw_file_path": raw_file_path,
        "serviceBusNamespace": service_bus_namespace,
        "fileChecksumCalculatorBaseUrl": file_checksum_base_url,
        "fileChecksumCalculatorKey": file_checksum_key,
        "run_id": run_id
    }
    
    # Log parameter values (masking sensitive data)
    logger.info("Prepared pipeline parameters:")
    for key, value in pipeline_parameters.items():
        if key in ["fileChecksumCalculatorKey"]:
            logger.info(f"  {key}: {'*' * min(len(str(value)) if value else 0, 20)} (masked)")
        else:
            logger.info(f"  {key}: {value}")
    
    # Remove None values - but keep empty strings and 0 as they are valid values
    # Only remove actual None values
    pipeline_parameters = {k: v for k, v in pipeline_parameters.items() if v is not None}
    
    # Ensure file_size_bytes is an integer, not a string
    if "file_size_bytes" in pipeline_parameters:
        try:
            pipeline_parameters["file_size_bytes"] = int(pipeline_parameters["file_size_bytes"])
        except (ValueError, TypeError):
            logger.warning(f"Could not convert file_size_bytes to integer: {pipeline_parameters.get('file_size_bytes')}")
    
    logger.info(f"Triggering ADF pipeline '{pipeline_name}' with {len(pipeline_parameters)} parameters: {list(pipeline_parameters.keys())}")
    
    # Use Azure SDK for Python (official SDK - handles serialization correctly)
    try:
        # Initialize Data Factory Management Client
        adf_client = DataFactoryManagementClient(credential, subscription_id)
        
        logger.info(f"Calling ADF SDK: factory={factory_name}, pipeline={pipeline_name}")
        logger.info(f"Parameters: {json.dumps({k: (v[:50] + '...' if isinstance(v, str) and len(v) > 50 else v) for k, v in pipeline_parameters.items()}, indent=2)}")
        
        # Trigger pipeline using SDK (this handles all serialization correctly)
        # The SDK expects parameters as a dict, which it will serialize properly
        run_response = adf_client.pipelines.create_run(
            resource_group_name=resource_group,
            factory_name=factory_name,
            pipeline_name=pipeline_name,
            parameters=pipeline_parameters
        )
        
        run_id_from_adf = run_response.run_id
        
        if not run_id_from_adf:
            logger.error(f"No runId in ADF response: {run_response}")
            return None
        
        logger.info(f"ADF pipeline triggered successfully. Run ID: {run_id_from_adf}")
        
        return {
            "runId": run_id_from_adf,
            "pipelineName": pipeline_name,
            "parameters": pipeline_parameters
        }
        
    except Exception as e:
        logger.error(f"Failed to trigger ADF pipeline via SDK: {str(e)}", exc_info=True)
        return None
