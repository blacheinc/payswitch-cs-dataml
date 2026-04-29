"""
Anonymization Mappings Storage
Handles storage and retrieval of anonymization mappings in PostgreSQL and Redis, including versioning
"""
import logging
from typing import Optional, Dict, List
import json
import uuid
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

# Use absolute imports for better compatibility
try:
    from schema_registry.postgres_client import PostgresClient as PostgreSQLClient
    from schema_registry.redis_client import RedisClient
    from schema_registry.models import AnonymizationMapping as AnonymizationMappingModel
except ImportError:
    from .postgres_client import PostgresClient as PostgreSQLClient
    from .redis_client import RedisClient
    from .models import AnonymizationMapping as AnonymizationMappingModel

# Note: calculate_schema_hash is not imported here to avoid triggering the full systems package import chain
# The schema_hash is passed as a parameter to store() method, so no calculation is needed in this module

logger = logging.getLogger(__name__)


class AnonymizationMappingStore:
    """
    Manages storage and retrieval of anonymization mappings in PostgreSQL and Redis.
    Implements versioning logic for mappings.
    """
    REDIS_TTL_SECONDS = 3600  # 1 hour as requested

    @classmethod
    def get(cls, bank_id: str, schema_hash: str) -> Optional[Dict[str, str]]:
        """
        Retrieves the latest active anonymization mapping for a given bank_id and schema_hash.
        Checks Redis first, then PostgreSQL.
        
        Args:
            bank_id: Bank identifier (mandatory)
            schema_hash: Schema hash (SHA-256 hex digest)
            
        Returns:
            Dictionary mapping column name -> anonymization method, or None
            
        Raises:
            ValueError: If bank_id is missing
            Exception: If PostgreSQL is down (fail fast)
        """
        if not bank_id:
            raise ValueError("bank_id is mandatory and cannot be empty or None")
        
        redis_key = f"anonymization_mapping:{bank_id}:{schema_hash}"
        
        # 1. Try Redis cache
        try:
            cached_mapping_json = RedisClient.get(redis_key)
            if cached_mapping_json:
                logger.info(f"Cache hit for AnonymizationMapping (Redis) for bank_id: {bank_id}, schema_hash: {schema_hash}")
                return json.loads(cached_mapping_json)
        except Exception as e:
            logger.warning(f"Error accessing Redis for AnonymizationMapping: {e}. Falling back to PostgreSQL.")

        # 2. Try PostgreSQL
        try:
            with PostgreSQLClient.get_db_session() as session:
                # Get the latest version for the given schema_hash
                db_record = session.query(AnonymizationMappingModel).filter_by(
                    bank_id=bank_id,
                    schema_hash=schema_hash
                ).order_by(
                    AnonymizationMappingModel.mapping_version.desc(),
                    AnonymizationMappingModel.mini_version.desc()
                ).first()
                
                if db_record:
                    logger.info(f"Cache hit for AnonymizationMapping (PostgreSQL) for bank_id: {bank_id}, schema_hash: {schema_hash}, version: {db_record.mapping_version}.{db_record.mini_version}")
                    mapping = db_record.anonymization_methods
                    # Store in Redis for future fast access
                    try:
                        RedisClient.set(redis_key, json.dumps(mapping), ttl=cls.REDIS_TTL_SECONDS)
                    except Exception as e:
                        logger.warning(f"Failed to cache AnonymizationMapping in Redis after PG lookup: {e}")
                    return mapping
        except SQLAlchemyError as e:
            logger.error(f"Failed to retrieve AnonymizationMapping from PostgreSQL for bank_id: {bank_id}, schema_hash: {schema_hash}: {e}")
            raise  # Fail fast if PG is down
        except Exception as e:
            logger.warning(f"Unexpected error during PG lookup for AnonymizationMapping: {e}. Continuing without cache.")
            # Continue normal execution if lookup fails unexpectedly

        logger.info(f"Cache miss for AnonymizationMapping for bank_id: {bank_id}, schema_hash: {schema_hash}")
        return None

    @classmethod
    def store(
        cls, 
        bank_id: str, 
        schema_hash: str, 
        anonymization_methods: Dict[str, str],
        current_column_names: List[str],
        current_column_types: Dict[str, str]
    ) -> None:
        """
        Stores an anonymization mapping in PostgreSQL and Redis, handling versioning.
        
        Args:
            bank_id: Bank identifier (mandatory)
            schema_hash: Schema hash (SHA-256 hex digest)
            anonymization_methods: Dictionary mapping column name -> anonymization method
            current_column_names: Current column names (for versioning comparison)
            current_column_types: Current column types (for versioning comparison)
            
        Raises:
            ValueError: If bank_id is missing
            Exception: If PostgreSQL is down (fail fast)
        """
        if not bank_id:
            raise ValueError("bank_id is mandatory and cannot be empty or None")
        
        redis_key = f"anonymization_mapping:{bank_id}:{schema_hash}"
        
        try:
            with PostgreSQLClient.get_db_session() as session:
                # Check for existing mapping to determine versioning
                latest_mapping = session.query(AnonymizationMappingModel).filter_by(
                    bank_id=bank_id,
                    schema_hash=schema_hash
                ).order_by(
                    AnonymizationMappingModel.mapping_version.desc(),
                    AnonymizationMappingModel.mini_version.desc()
                ).first()

                new_mapping_version = "1.0"
                new_mini_version = 0

                if latest_mapping:
                    # Compare current schema with the schema that generated the latest mapping
                    # For simplicity, we'll assume if schema_hash is the same, it's a minor update
                    # More sophisticated logic would involve comparing actual column_names/types
                    # to determine if it's a major version bump.
                    
                    # If schema_hash is the same, it's a mini-version increment
                    new_mapping_version = latest_mapping.mapping_version
                    new_mini_version = latest_mapping.mini_version + 1
                    logger.info(f"Incrementing mini-version for existing anonymization mapping (bank_id: {bank_id}, schema_hash: {schema_hash}) to {new_mapping_version}.{new_mini_version}")
                else:
                    logger.info(f"Creating new anonymization mapping (bank_id: {bank_id}, schema_hash: {schema_hash}) with version {new_mapping_version}.{new_mini_version}")

                db_record = AnonymizationMappingModel(
                    id=str(uuid.uuid4()),
                    bank_id=bank_id,
                    schema_hash=schema_hash,
                    mapping_version=new_mapping_version,
                    mini_version=new_mini_version,
                    anonymization_methods=anonymization_methods,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(db_record)
                session.commit()
            logger.info(f"Stored AnonymizationMapping in PostgreSQL for bank_id: {bank_id}, schema_hash: {schema_hash}, version: {new_mapping_version}.{new_mini_version}")
        except SQLAlchemyError as e:
            logger.error(f"Failed to store AnonymizationMapping in PostgreSQL for bank_id: {bank_id}, schema_hash: {schema_hash}: {e}")
            raise  # Fail fast if PG is down
        except Exception as e:
            logger.warning(f"Unexpected error during PG store for AnonymizationMapping: {e}. Continuing without cache.")
            # Continue normal execution if store fails unexpectedly

        # 2. Store in Redis
        try:
            RedisClient.set(redis_key, json.dumps(anonymization_methods), ttl=cls.REDIS_TTL_SECONDS)
            logger.info(f"Stored AnonymizationMapping in Redis for bank_id: {bank_id}, schema_hash: {schema_hash}")
        except Exception as e:
            logger.warning(f"Failed to store AnonymizationMapping in Redis: {e}. Continuing without cache.")
