"""
Schema Detection Results Storage
Handles storage and retrieval of schema detection results in PostgreSQL and Redis
"""
import logging
from typing import Optional
import json

from sqlalchemy.exc import SQLAlchemyError

# Use absolute imports for better compatibility
try:
    from schema_registry.postgres_client import PostgresClient as PostgreSQLClient
    from schema_registry.redis_client import RedisClient
    from schema_registry.models import SchemaDetectionResult as SchemaDetectionResultModel
    from system_interfaces import SchemaDetectionResult
except ImportError:
    from .postgres_client import PostgresClient as PostgreSQLClient
    from .redis_client import RedisClient
    from .models import SchemaDetectionResult as SchemaDetectionResultModel
    from ..system_interfaces import SchemaDetectionResult

logger = logging.getLogger(__name__)


class SchemaDetectionStore:
    """
    Manages storage and retrieval of SchemaDetectionResult in PostgreSQL and Redis.
    """
    REDIS_TTL_SECONDS = 86400  # 24 hours

    @classmethod
    def get(cls, bank_id: str, schema_hash: str) -> Optional[SchemaDetectionResult]:
        """
        Retrieves a SchemaDetectionResult from Redis cache or PostgreSQL.
        If found in PG, it's also stored in Redis.
        
        Args:
            bank_id: Bank identifier (mandatory)
            schema_hash: Schema hash (SHA-256 hex digest)
            
        Returns:
            SchemaDetectionResult if found, None otherwise
            
        Raises:
            ValueError: If bank_id is missing
            Exception: If PostgreSQL is down (fail fast)
        """
        if not bank_id:
            raise ValueError("bank_id is mandatory and cannot be empty or None")
        
        redis_key = f"schema_detection:{bank_id}:{schema_hash}"
        
        # 1. Try Redis cache
        try:
            cached_result_json = RedisClient.get(redis_key)
            if cached_result_json:
                logger.info(f"Cache hit for SchemaDetectionResult (Redis) for bank_id: {bank_id}, schema_hash: {schema_hash}")
                return SchemaDetectionResult.parse_raw(cached_result_json)
        except Exception as e:
            logger.warning(f"Error accessing Redis for SchemaDetectionResult: {e}. Falling back to PostgreSQL.")

        # 2. Try PostgreSQL
        try:
            with PostgreSQLClient.get_db_session() as session:
                db_record = session.query(SchemaDetectionResultModel).filter_by(
                    bank_id=bank_id,
                    schema_hash=schema_hash
                ).first()
                
                if db_record:
                    logger.info(f"Cache hit for SchemaDetectionResult (PostgreSQL) for bank_id: {bank_id}, schema_hash: {schema_hash}")
                    result = SchemaDetectionResult.parse_raw(json.dumps(db_record.result_json))
                    # Store in Redis for future fast access
                    try:
                        RedisClient.set(redis_key, result.model_dump_json(), ttl=cls.REDIS_TTL_SECONDS)
                    except Exception as e:
                        logger.warning(f"Failed to cache SchemaDetectionResult in Redis after PG lookup: {e}")
                    return result
        except SQLAlchemyError as e:
            logger.error(f"Failed to retrieve SchemaDetectionResult from PostgreSQL for bank_id: {bank_id}, schema_hash: {schema_hash}: {e}")
            raise  # Fail fast if PG is down
        except Exception as e:
            logger.warning(f"Unexpected error during PG lookup for SchemaDetectionResult: {e}. Continuing without cache.")
            # Continue normal execution if lookup fails unexpectedly

        logger.info(f"Cache miss for SchemaDetectionResult for bank_id: {bank_id}, schema_hash: {schema_hash}")
        return None

    @classmethod
    def store(cls, bank_id: str, schema_hash: str, result: SchemaDetectionResult) -> None:
        """
        Stores a SchemaDetectionResult in PostgreSQL and Redis.
        
        Args:
            bank_id: Bank identifier (mandatory)
            schema_hash: Schema hash (SHA-256 hex digest)
            result: SchemaDetectionResult to store
            
        Raises:
            ValueError: If bank_id is missing
            Exception: If PostgreSQL is down (fail fast)
        """
        if not bank_id:
            raise ValueError("bank_id is mandatory and cannot be empty or None")
        
        redis_key = f"schema_detection:{bank_id}:{schema_hash}"
        
        # 1. Store in PostgreSQL
        try:
            with PostgreSQLClient.get_db_session() as session:
                # Check if record already exists
                existing = session.query(SchemaDetectionResultModel).filter_by(
                    bank_id=bank_id,
                    schema_hash=schema_hash
                ).first()
                
                result_json = json.loads(result.json())  # Store Pydantic model as JSONB
                
                if existing:
                    existing.result_json = result_json
                    session.commit()
                    logger.info(f"Updated SchemaDetectionResult in PostgreSQL for bank_id: {bank_id}, schema_hash: {schema_hash}")
                else:
                    import uuid
                    db_record = SchemaDetectionResultModel(
                        id=str(uuid.uuid4()),
                        bank_id=bank_id,
                        schema_hash=schema_hash,
                        result_json=result_json
                    )
                    session.add(db_record)
                    session.commit()
                    logger.info(f"Stored SchemaDetectionResult in PostgreSQL for bank_id: {bank_id}, schema_hash: {schema_hash}")
        except SQLAlchemyError as e:
            logger.error(f"Failed to store SchemaDetectionResult in PostgreSQL for bank_id: {bank_id}, schema_hash: {schema_hash}: {e}")
            raise  # Fail fast if PG is down
        except Exception as e:
            logger.warning(f"Unexpected error during PG store for SchemaDetectionResult: {e}. Continuing without cache.")
            # Continue normal execution if store fails unexpectedly

        # 2. Store in Redis
        try:
            RedisClient.set(redis_key, result.model_dump_json(), ttl=cls.REDIS_TTL_SECONDS)
            logger.info(f"Stored SchemaDetectionResult in Redis for bank_id: {bank_id}, schema_hash: {schema_hash}")
        except Exception as e:
            logger.warning(f"Failed to store SchemaDetectionResult in Redis: {e}. Continuing without cache.")
