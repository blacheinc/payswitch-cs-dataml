"""
Redis Client for Schema Registry Caching (optional).

Schema-registry Redis is **opt-in** so data-engineering deployments do not need
Azure Cache for Redis or the `RedisConnectionString` Key Vault secret.

Enable only when you want the cache layer (e.g. backend / high-churn workloads):
  SCHEMA_REGISTRY_ENABLE_REDIS=1   (or true/yes)

Still respected:
  INFERENCE_SKIP_REDIS=1           — skip Redis for this worker scope (inference path)
  SCHEMA_REGISTRY_DISABLE_REDIS=1 — force off even if ENABLE is set
"""
import logging
import os
from typing import Optional
import redis
from azure.identity import DefaultAzureCredential

try:
    from utils.key_vault_reader import KeyVaultReader, KeyVaultError
except ImportError:
    from ..utils.key_vault_reader import KeyVaultReader, KeyVaultError

logger = logging.getLogger(__name__)


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


class RedisClient:
    """Redis client for caching"""
    
    # Class-level variables for singleton pattern
    _redis_client = None
    _is_available = False
    _kv_client = None
    _key_vault_url = None
    # After one failed connect/ping, skip Redis for this worker (inference/training cold path).
    _redis_permanently_unavailable = False

    @classmethod
    def _is_redis_enabled(cls) -> bool:
        """Redis is off unless explicitly enabled; avoids Key Vault reads when unused."""
        if _env_truthy("INFERENCE_SKIP_REDIS"):
            return False
        if _env_truthy("SCHEMA_REGISTRY_DISABLE_REDIS"):
            return False
        return _env_truthy("SCHEMA_REGISTRY_ENABLE_REDIS")

    def __init__(
        self,
        key_vault_url: Optional[str] = None,
        exclude_environment_credential: bool = True,
        key_vault_reader: Optional[KeyVaultReader] = None
    ):
        """
        Initialize Redis client (instance-based usage)
        
        Args:
            key_vault_url: Azure Key Vault URL (if None, uses KEY_VAULT_URL env var)
            exclude_environment_credential: Exclude EnvironmentCredential (default: True)
            key_vault_reader: Optional KeyVaultReader instance (if None, will create one)
        """
        # Get Key Vault URL from env var or parameter
        self.key_vault_url = key_vault_url or os.getenv('KEY_VAULT_URL')
        if not self.key_vault_url and not key_vault_reader:
            raise ValueError("Key Vault URL or KeyVaultReader must be provided")
        
        self.key_vault_reader = key_vault_reader
        self._exclude_environment_credential = exclude_environment_credential
        self._redis_client: Optional[redis.Redis] = None
        self._is_available = False
    
    @classmethod
    def _get_key_vault_reader(cls) -> KeyVaultReader:
        """Get or create Key Vault reader (class method)"""
        if cls._kv_client is None:
            key_vault_url = os.getenv('KEY_VAULT_URL')
            if not key_vault_url:
                raise ValueError("KEY_VAULT_URL environment variable must be set")
            cls._key_vault_url = key_vault_url
            try:
                cls._kv_client = KeyVaultReader(key_vault_url=key_vault_url)
                logger.info("Key Vault reader initialized for RedisClient.")
            except Exception as e:
                logger.error(f"Failed to initialize Key Vault reader: {e}")
                raise
        return cls._kv_client
    
    @classmethod
    def _get_connection_string(cls) -> str:
        """Get Redis connection string from Key Vault (class method)"""
        kv_reader = cls._get_key_vault_reader()
        try:
            conn_string = kv_reader.get_secret("RedisConnectionString")
            logger.info("Retrieved RedisConnectionString from Key Vault.")
            return conn_string
        except KeyVaultError as e:
            logger.error(f"Failed to retrieve RedisConnectionString from Key Vault: {e}")
            raise
    
    @classmethod
    def _normalize_connection_string(cls, conn_string: str, require_ssl: bool = True) -> str:
        """
        Normalize Redis connection string to use proper protocol for SSL.
        
        Args:
            conn_string: Original connection string
            require_ssl: Whether SSL is required (default: True for Azure Cache for Redis)
        
        Returns:
            Normalized connection string with proper protocol
        """
        # If connection string already uses rediss://, it's already SSL-enabled
        if conn_string.startswith("rediss://"):
            return conn_string
        
        # If connection string uses redis:// and we need SSL, convert to rediss://
        if conn_string.startswith("redis://") and require_ssl:
            normalized = conn_string.replace("redis://", "rediss://", 1)
            logger.debug(f"Converted connection string to use SSL: redis:// -> rediss://")
            return normalized
        
        # If connection string doesn't start with a protocol, assume redis:// and convert if needed
        if not conn_string.startswith(("redis://", "rediss://")):
            protocol = "rediss://" if require_ssl else "redis://"
            normalized = f"{protocol}{conn_string}"
            logger.debug(f"Added protocol to connection string: {normalized}")
            return normalized
        
        return conn_string
    
    @classmethod
    def _redis_timeouts_from_env(cls) -> tuple[float, float]:
        """(socket_connect_timeout, socket_timeout) in seconds — fail fast when cache is unreachable."""
        try:
            connect_s = float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "3"))
        except ValueError:
            connect_s = 3.0
        try:
            sock_s = float(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
        except ValueError:
            sock_s = 5.0
        return max(0.5, connect_s), max(0.5, sock_s)

    @classmethod
    def get_redis_client(cls):
        """Get or create Redis client (class method, lazy initialization). Returns None if disabled/unavailable."""
        if not cls._is_redis_enabled():
            return None
        if cls._redis_permanently_unavailable:
            return None
        if cls._redis_client is not None:
            return cls._redis_client
        try:
            conn_string = cls._get_connection_string()
            normalized_conn_string = cls._normalize_connection_string(conn_string, require_ssl=True)
            connect_timeout, socket_timeout = cls._redis_timeouts_from_env()
            cls._redis_client = redis.from_url(
                normalized_conn_string,
                decode_responses=True,
                socket_connect_timeout=connect_timeout,
                socket_timeout=socket_timeout,
            )
            cls._redis_client.ping()
            cls._is_available = True
            logger.info(
                "Redis client initialized and connection tested successfully "
                "(connect_timeout=%ss, socket_timeout=%ss).",
                connect_timeout,
                socket_timeout,
            )
        except Exception as e:
            logger.error("An unexpected error during Redis client creation: %s", e)
            cls._redis_permanently_unavailable = True
            cls._redis_client = None
            cls._is_available = False
            return None
        return cls._redis_client
    
    def connect(self) -> bool:
        """
        Connect to Redis (lazy initialization) - instance method
        
        Returns:
            True if connected successfully, False otherwise
        """
        if not self._is_redis_enabled():
            self._is_available = False
            self._redis_client = None
            return False
        try:
            if self._redis_client is None:
                # Use class method to get connection string
                conn_string = RedisClient._get_connection_string()
                
                # Normalize connection string to use rediss:// for SSL (Azure Cache for Redis)
                normalized_conn_string = RedisClient._normalize_connection_string(conn_string, require_ssl=True)
                
                # Create Redis client from connection string
                # Note: In redis 5.0+, SSL is indicated by rediss:// protocol, not ssl=True parameter
                self._redis_client = redis.from_url(normalized_conn_string, decode_responses=True)
                
                # Test connection
                self._redis_client.ping()
                self._is_available = True
                logger.info("Connected to Redis")
            
            return True
            
        except Exception as e:
            logger.warning(f"Failed to connect to Redis (will skip caching): {e}")
            self._is_available = False
            self._redis_client = None
            return False
    
    def is_available(self) -> bool:
        """Check if Redis is available"""
        if self._redis_client is None:
            return self.connect()
        return self._is_available
    
    @classmethod
    def get(cls, key: str) -> Optional[str]:
        """
        Retrieve a value from Redis (class method).
        
        Args:
            key: Redis key
            
        Returns:
            Value if found, None otherwise
        """
        try:
            client = cls.get_redis_client()
            if client is None:
                return None
            value = client.get(key)
            if value:
                logger.debug(f"Cache hit for key: {key}")
            else:
                logger.debug(f"Cache miss for key: {key}")
            return value
        except redis.exceptions.RedisError as e:
            logger.warning(f"Redis GET operation failed for key {key}: {e}")
            return None  # Fail gracefully
        except Exception as e:
            logger.warning(f"Unexpected error during Redis GET for key {key}: {e}")
            return None
    
    @classmethod
    def set(cls, key: str, value: str, ttl: int = 3600) -> None:
        """
        Store a value in Redis with an optional TTL (in seconds) (class method).
        
        Args:
            key: Redis key
            value: Value to store
            ttl: Time to live in seconds (default: 3600 = 1 hour)
        """
        try:
            client = cls.get_redis_client()
            if client is None:
                return
            client.set(key, value, ex=ttl)
            logger.debug(f"Cache set for key: {key} with TTL: {ttl}s")
        except redis.exceptions.RedisError as e:
            logger.warning(f"Redis SET operation failed for key {key}: {e}")
            # Fail gracefully, do not re-raise
        except Exception as e:
            logger.warning(f"Unexpected error during Redis SET for key {key}: {e}")
    
    def delete(self, key: str) -> bool:
        """
        Delete key from Redis
        
        Args:
            key: Redis key
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available():
            return False
        
        try:
            self._redis_client.delete(key)
            return True
        except Exception as e:
            logger.warning(f"Failed to delete from Redis: {e}")
            return False
    
    def close(self):
        """Close Redis connection"""
        if self._redis_client:
            self._redis_client.close()
            self._redis_client = None
            self._is_available = False
            logger.info("Redis connection closed")
