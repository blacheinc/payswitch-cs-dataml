"""
PostgreSQL Client for Schema Registry
Handles database connections and operations
"""
import logging
import uuid
import os
import re
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from azure.identity import DefaultAzureCredential

try:
    from utils.key_vault_reader import KeyVaultReader, KeyVaultError
except ImportError:
    from ..utils.key_vault_reader import KeyVaultReader, KeyVaultError

logger = logging.getLogger(__name__)


class PostgresClient:
    """PostgreSQL client for Schema Registry"""
    
    # Class-level variables for singleton pattern
    _engine = None
    _SessionLocal = None
    _kv_client = None
    _key_vault_url = None
    
    def __init__(
        self,
        key_vault_url: Optional[str] = None,
        database_name: Optional[str] = None,
        exclude_environment_credential: bool = True,
        key_vault_reader: Optional[KeyVaultReader] = None
    ):
        """
        Initialize PostgreSQL client (instance-based usage)
        
        Args:
            key_vault_url: Azure Key Vault URL (if None, uses KEY_VAULT_URL env var)
            database_name: Database name (if None, gets from Key Vault PostgreSQLDatabase secret)
            exclude_environment_credential: Exclude EnvironmentCredential (default: True)
            key_vault_reader: Optional KeyVaultReader instance (if None, will create one)
        """
        # Get Key Vault URL from env var or parameter
        self.key_vault_url = key_vault_url or os.getenv('KEY_VAULT_URL')
        if not self.key_vault_url and not key_vault_reader:
            raise ValueError("Key Vault URL or KeyVaultReader must be provided")
        
        self.key_vault_reader = key_vault_reader
        self._database_name = database_name  # Will be set from Key Vault if None
        self.engine = None
        self.SessionLocal = None
        self._credential = None
        self._exclude_environment_credential = exclude_environment_credential
        self._connection_string = None
    
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
                logger.info("Key Vault reader initialized for PostgreSQLClient.")
            except Exception as e:
                logger.error(f"Failed to initialize Key Vault reader: {e}")
                raise
        return cls._kv_client
    
    @classmethod
    def get_engine(cls):
        """Get or create PostgreSQL engine (class method, lazy initialization)"""
        if cls._engine is None:
            try:
                # Create a temporary instance to get connection string
                temp_client = PostgresClient()
                conn_string = temp_client._get_connection_string()
                
                cls._engine = create_engine(
                    conn_string,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    echo=False
                )
                # Test connection
                with cls._engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                logger.info("PostgreSQL engine created and connection tested successfully.")
            except Exception as e:
                logger.error(f"Failed to connect to PostgreSQL database: {e}")
                raise
        return cls._engine
    
    @classmethod
    def get_session_local(cls):
        """Get or create session factory (class method)"""
        if cls._SessionLocal is None:
            cls.get_engine()  # Ensure engine is initialized
            cls._SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls._engine)
        return cls._SessionLocal
    
    @classmethod
    @contextmanager
    def get_db_session(cls):
        """Get database session context manager (class method)"""
        SessionLocal = cls.get_session_local()
        session = SessionLocal()
        try:
            yield session
        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            session.close()
        
    def _parse_connection_string(self, conn_string: str) -> Dict[str, str]:
        """
        Parse PostgreSQL connection string to extract components
        
        Args:
            conn_string: Connection string (format: postgresql://user:password@host:port/database)
            
        Returns:
            Dictionary with parsed components
        """
        try:
            parsed = urlparse(conn_string)
            return {
                'scheme': parsed.scheme or 'postgresql',
                'user': parsed.username,
                'password': parsed.password,
                'host': parsed.hostname,
                'port': str(parsed.port) if parsed.port else '5432',
                'database': parsed.path.lstrip('/') if parsed.path else None,
                'query': parsed.query
            }
        except Exception as e:
            logger.error(f"Failed to parse connection string: {e}")
            raise Exception(f"Failed to parse PostgreSQL connection string: {e}")
    
    def _get_connection_string(self) -> str:
        """
        Get PostgreSQL connection string from Key Vault and ensure correct database
        
        Returns:
            PostgreSQL connection string with correct database name
            
        Raises:
            Exception: If connection string cannot be retrieved or database name cannot be determined
        """
        if self._connection_string:
            return self._connection_string
        
        try:
            # Initialize credential
            credential = DefaultAzureCredential(
                exclude_environment_credential=self._exclude_environment_credential,
                exclude_shared_token_cache_credential=False,
                exclude_visual_studio_code_credential=False,
                exclude_cli_credential=False,
                exclude_powershell_credential=False,
                exclude_managed_identity_credential=False,
                exclude_interactive_browser_credential=False
            )
            self._credential = credential
            
            # Get Key Vault reader
            if self.key_vault_reader:
                kv_reader = self.key_vault_reader
            else:
                kv_reader = KeyVaultReader(key_vault_url=self.key_vault_url)
            
            # Get connection string
            conn_string = kv_reader.get_secret("PostgreSQLConnectionString")
            logger.info("Retrieved PostgreSQLConnectionString from Key Vault")
            
            # Get database name (from parameter, Key Vault, or parse from connection string)
            if self._database_name:
                database_name = self._database_name
            else:
                try:
                    database_name = kv_reader.get_secret("PostgreSQLDatabase")
                    logger.info(f"Retrieved PostgreSQLDatabase from Key Vault: {database_name}")
                except KeyVaultError:
                    # Try to parse from connection string
                    parsed = self._parse_connection_string(conn_string)
                    database_name = parsed.get('database')
                    if not database_name:
                        raise Exception("Database name not found in connection string and PostgreSQLDatabase not in Key Vault")
                    logger.info(f"Parsed database name from connection string: {database_name}")
            
            # Parse connection string and reconstruct with correct database
            parsed = self._parse_connection_string(conn_string)
            scheme = parsed.get('scheme', 'postgresql')
            final_conn_string = f"{scheme}://{parsed['user']}:{parsed['password']}@{parsed['host']}:{parsed['port']}/{database_name}"
            
            if parsed.get('query'):
                final_conn_string += f"?{parsed['query']}"
            
            self._connection_string = final_conn_string
            self._database_name = database_name
            return final_conn_string
                
        except Exception as e:
            logger.error(f"Failed to get PostgreSQL connection string: {e}")
            raise Exception(f"Failed to get PostgreSQL connection string: {e}")
    
    def connect(self):
        """Connect to PostgreSQL database (lazy initialization)"""
        try:
            if self.engine is None:
                conn_string = self._get_connection_string()
                
                # Create engine
                self.engine = create_engine(
                    conn_string,
                    pool_pre_ping=True,  # Verify connections before using
                    pool_recycle=3600,  # Recycle connections after 1 hour
                    echo=False  # Set to True for SQL logging
                )
                
                # Create session factory
                self.SessionLocal = sessionmaker(bind=self.engine)
                
                logger.info(f"Connected to PostgreSQL database: {self._database_name}")
            
            return self.engine
            
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise Exception(f"Failed to connect to PostgreSQL: {e}")
    
    def get_session(self) -> Session:
        """
        Get database session
        
        Returns:
            SQLAlchemy session
            
        Raises:
            Exception: If not connected
        """
        if self.SessionLocal is None:
            self.connect()
        
        return self.SessionLocal()
    
    def ensure_schema_exists(self):
        """Ensure schema_registry schema exists in database"""
        try:
            with self.engine.connect() as conn:
                # Create schema if it doesn't exist
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS schema_registry"))
                conn.commit()
                logger.info("Schema 'schema_registry' ensured")
        except Exception as e:
            logger.error(f"Failed to ensure schema exists: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.engine:
            self.engine.dispose()
            self.engine = None
            self.SessionLocal = None
            logger.info("PostgreSQL connection closed")
