"""
Key Vault Reader
Centralized Key Vault secret reader with connection management and optional caching
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, List, TYPE_CHECKING
from datetime import datetime, timedelta

if TYPE_CHECKING:
    from azure.keyvault.secrets import SecretClient
    from azure.identity import DefaultAzureCredential

try:
    from azure.keyvault.secrets import SecretClient
    from azure.identity import DefaultAzureCredential, AzureCliCredential
    from azure.core.exceptions import AzureError, ClientAuthenticationError
    KEY_VAULT_AVAILABLE = True
except ImportError:
    KEY_VAULT_AVAILABLE = False
    SecretClient = None  # type: ignore
    DefaultAzureCredential = None  # type: ignore
    AzureCliCredential = None  # type: ignore
    ClientAuthenticationError = None  # type: ignore

logger = logging.getLogger(__name__)


class KeyVaultError(Exception):
    """Exception raised for Key Vault errors"""
    pass


class CachedSecret:
    """Represents a cached secret with TTL"""
    
    def __init__(self, value: str, ttl_seconds: int = 300):
        """
        Initialize cached secret
        
        Args:
            value: Secret value
            ttl_seconds: Time-to-live in seconds (default: 5 minutes)
        """
        self.value = value
        self.expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired"""
        return datetime.utcnow() >= self.expires_at


class KeyVaultReader:
    """
    Centralized Key Vault secret reader with connection management and optional caching
    
    Features:
    - Lazy initialization of SecretClient
    - Context manager support for automatic cleanup
    - Optional in-memory caching (5-minute TTL by default)
    - Batch secret retrieval
    - Proper error handling and logging
    """
    
    DEFAULT_CACHE_TTL = 300  # 5 minutes in seconds
    
    def __init__(
        self,
        key_vault_url: str,
        credential=None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        enable_cache: bool = True
    ):
        """
        Initialize Key Vault Reader
        
        Args:
            key_vault_url: Key Vault URL (e.g., "https://myvault.vault.azure.net/")
            credential: Optional Azure credential (if None, uses DefaultAzureCredential)
            cache_ttl: Cache time-to-live in seconds (default: 300 = 5 minutes)
            enable_cache: Enable in-memory caching (default: True)
        """
        if not KEY_VAULT_AVAILABLE:
            raise KeyVaultError(
                "Azure Key Vault SDK not available. Install with: pip install azure-keyvault-secrets"
            )
        
        if not key_vault_url:
            raise KeyVaultError("key_vault_url is required and cannot be empty")
        
        # Ensure URL ends with /
        if not key_vault_url.endswith('/'):
            key_vault_url = key_vault_url + '/'
        
        self.key_vault_url = key_vault_url
        self._credential = credential
        self.cache_ttl = cache_ttl
        self.enable_cache = enable_cache
        
        self._client: Optional[SecretClient] = None
        self._cache: Dict[str, CachedSecret] = {}
        # Track whether we've already excluded EnvironmentCredential due to tenant issues
        # Used by get_secret() to decide if we should retry with a different credential configuration
        self._credential_excludes_env: bool = False
    
    def _get_credential(self):
        """Get or create credential.

        Behavior:
        - When ENVIRONMENT=local (default), use AzureCliCredential so that
          local az login is the single source of truth.
        - Otherwise (e.g. in Azure), use DefaultAzureCredential so that
          Managed Identity and other mechanisms can be used.
        """
        if self._credential is None:
            import os

            env = os.getenv("ENVIRONMENT", "local").lower()

            if env == "local":
                # Local development: rely on Azure CLI login only.
                if AzureCliCredential is None:
                    raise KeyVaultError(
                        "AzureCliCredential not available. Install azure-identity and azure-cli."
                    )
                self._credential = AzureCliCredential()
                logger.debug("Created AzureCliCredential for local environment")
            else:
                # Non-local (e.g., Azure Function App) - use DefaultAzureCredential
                self._credential = DefaultAzureCredential()
                logger.debug("Created DefaultAzureCredential for non-local environment")
        
        return self._credential
    
    def _get_client(self) -> SecretClient:
        """Get or create SecretClient (lazy initialization)"""
        if self._client is None:
            try:
                credential = self._get_credential()
                self._client = SecretClient(
                    vault_url=self.key_vault_url,
                    credential=credential
                )
                logger.debug(f"Initialized SecretClient for {self.key_vault_url}")
            except Exception as e:
                raise KeyVaultError(
                    f"Failed to initialize SecretClient: {str(e)}"
                ) from e
        
        return self._client
    
    def _get_from_cache(self, secret_name: str) -> Optional[str]:
        """Get secret from cache if available and not expired"""
        if not self.enable_cache:
            return None
        
        cached = self._cache.get(secret_name)
        if cached is None:
            return None
        
        if cached.is_expired():
            # Remove expired entry
            del self._cache[secret_name]
            logger.debug(f"Cache expired for secret: {secret_name}")
            return None
        
        logger.debug(f"Cache hit for secret: {secret_name}")
        return cached.value
    
    def _set_cache(self, secret_name: str, value: str) -> None:
        """Store secret in cache"""
        if not self.enable_cache:
            return
        
        self._cache[secret_name] = CachedSecret(value, self.cache_ttl)
        logger.debug(f"Cached secret: {secret_name} (TTL: {self.cache_ttl}s)")
    
    def get_secret(
        self,
        secret_name: str,
        use_cache: bool = True
    ) -> str:
        """
        Get secret value from Key Vault
        
        Args:
            secret_name: Name of the secret in Key Vault
            use_cache: Whether to use cache (if enabled) (default: True)
            
        Returns:
            Secret value as string
            
        Raises:
            KeyVaultError: If secret cannot be retrieved
        """
        if not secret_name:
            raise KeyVaultError("secret_name is required and cannot be empty")
        
        # Check cache first
        if use_cache:
            cached_value = self._get_from_cache(secret_name)
            if cached_value is not None:
                return cached_value
        
        # Retrieve from Key Vault
        try:
            client = self._get_client()
            secret = client.get_secret(secret_name)
            value = secret.value
            
            if value is None:
                raise KeyVaultError(f"Secret '{secret_name}' exists but has no value")
            
            # Cache the value
            if use_cache:
                self._set_cache(secret_name, value)
            
            logger.debug(f"Retrieved secret: {secret_name} from Key Vault")
            return value
            
        except (ClientAuthenticationError, AzureError) as e:
            # Check if this is the EnvironmentCredential error
            error_str = str(e)
            if (not self._credential_excludes_env and 
                "EnvironmentCredential" in error_str and 
                "not configured to acquire tokens for tenant" in error_str):
                # Try again with EnvironmentCredential excluded
                logger.warning(
                    f"EnvironmentCredential error detected. Retrying with EnvironmentCredential excluded..."
                )
                # Reset credential and client to force recreation
                self._credential = None
                self._client = None
                self._credential_excludes_env = True
                
                # Retry with excluded credential
                try:
                    client = self._get_client()
                    secret = client.get_secret(secret_name)
                    value = secret.value
                    
                    if value is None:
                        raise KeyVaultError(f"Secret '{secret_name}' exists but has no value")
                    
                    # Cache the value
                    if use_cache:
                        self._set_cache(secret_name, value)
                    
                    logger.info(f"Successfully retrieved secret '{secret_name}' after excluding EnvironmentCredential")
                    return value
                except Exception as retry_e:
                    error_msg = f"Failed to retrieve secret '{secret_name}' from Key Vault (after retry): {str(retry_e)}"
                    logger.error(error_msg)
                    raise KeyVaultError(error_msg) from retry_e
            else:
                # Not the EnvironmentCredential error, or already excluded - raise normally
                error_msg = f"Failed to retrieve secret '{secret_name}' from Key Vault: {str(e)}"
                logger.error(error_msg)
                raise KeyVaultError(error_msg) from e
        except Exception as e:
            error_msg = f"Unexpected error retrieving secret '{secret_name}': {str(e)}"
            logger.error(error_msg)
            raise KeyVaultError(error_msg) from e
    
    def get_secrets(
        self,
        secret_names: List[str],
        use_cache: bool = True
    ) -> Dict[str, str]:
        """
        Get multiple secrets in one call
        
        Args:
            secret_names: List of secret names to retrieve
            use_cache: Whether to use cache (if enabled) (default: True)
            
        Returns:
            Dictionary mapping secret_name -> secret_value
            
        Raises:
            KeyVaultError: If any secret cannot be retrieved
        """
        if not secret_names:
            return {}
        
        results = {}
        errors = []
        
        for secret_name in secret_names:
            try:
                value = self.get_secret(secret_name, use_cache=use_cache)
                results[secret_name] = value
            except KeyVaultError as e:
                errors.append(f"{secret_name}: {str(e)}")
        
        if errors:
            raise KeyVaultError(
                f"Failed to retrieve some secrets:\n" + "\n".join(errors)
            )
        
        return results
    
    def clear_cache(self, secret_name: Optional[str] = None) -> None:
        """
        Clear cache (all or specific secret)
        
        Args:
            secret_name: Optional secret name to clear (if None, clears all)
        """
        if secret_name:
            if secret_name in self._cache:
                del self._cache[secret_name]
                logger.debug(f"Cleared cache for secret: {secret_name}")
        else:
            self._cache.clear()
            logger.debug("Cleared all cached secrets")
    
    def close(self) -> None:
        """Close SecretClient connection"""
        if self._client:
            # SecretClient doesn't have an explicit close method, but we can clear the reference
            self._client = None
            logger.debug("Closed SecretClient connection")
    
    def __enter__(self) -> 'KeyVaultReader':
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close connection"""
        self.close()
