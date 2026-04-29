import os
import threading
import logging
from typing import Optional
from openai import AzureOpenAI

logger = logging.getLogger(__name__)

class OpenAIClientManager:
    """
    Singleton manager for the Azure OpenAI client.
    Ensures that credentials are only fetched from Key Vault once,
    and a single client instance is shared across all LLM agents.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, key_vault_reader=None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(OpenAIClientManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, key_vault_reader=None):
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return
                
            logger.info("Initializing Singleton Azure OpenAI Client...")
            
            # Fetch credentials
            if key_vault_reader:
                logger.info("Fetching OpenAI credentials from Key Vault")
                self.api_key = key_vault_reader.get_secret("AzureOpenAIKey")
                self.endpoint = key_vault_reader.get_secret("AzureOpenAIEndpoint")
                self.api_version = key_vault_reader.get_secret("AzureOpenAIApiVersion")
                self.deployment = key_vault_reader.get_secret("AzureOpenAIDeployment")
            else:
                logger.info("Fetching OpenAI credentials from environment variables")
                self.api_key = os.getenv("AzureOpenAIKey")
                self.endpoint = os.getenv("AzureOpenAIEndpoint")
                self.api_version = os.getenv("AzureOpenAIApiVersion")
                self.deployment = os.getenv("AzureOpenAIDeployment")

            if not all([self.api_key, self.endpoint, self.api_version]):
                raise ValueError("Missing required Azure OpenAI configuration (Key, Endpoint, or API Version).")

            # Initialize client
            self.client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version
            )
            self._initialized = True
            logger.info("Singleton Azure OpenAI Client successfully initialized.")

    def get_client(self) -> AzureOpenAI:
        """Returns the active Azure OpenAI client."""
        return self.client
        
    def get_deployment_name(self) -> str:
        """Returns the default deployment model name."""
        return self.deployment or "gpt-4o-mini"
        
    def close_connection(self):
        """
        Closes the client connection and resets the singleton.
        Used by the Agent Manager if max correction loops are exceeded.
        """
        with self._lock:
            if self.client:
                self.client.close()
                self.client = None
            self._initialized = False
            OpenAIClientManager._instance = None
            logger.warning("Azure OpenAI client connection has been severed.")
