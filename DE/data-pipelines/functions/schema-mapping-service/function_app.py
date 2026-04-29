"""
Schema Mapping Service - Azure Function
Orchestrates Systems 0-4 for training data transformation

This service:
- System 0: File Introspection
- System 1: Schema Detection
- System 2: Data Sampling
- System 3: Data Analysis
- System 4: PII Detection & Anonymization
"""

import azure.functions as func
import logging
import json
import os

# Configure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Import orchestrator
from orchestrator import get_orchestrator

# ============================================================
# Message filtering (subscription may receive wrong-topic payloads)
# ============================================================


def _is_schema_mapping_trigger(message_data: dict) -> bool:
    """
    True only for bronze-ingested handoffs: upload id, bank/datasource, bronze path.

    Other services sometimes publish to the same topic (e.g. quality_report,
    transformed_file_path). Those must not call run_pipeline or validation throws
    on missing bank_id and spams retries.
    """
    if not isinstance(message_data, dict):
        return False
    for key in ("transformed_file_path", "features_mapped", "quality_report"):
        if key in message_data:
            return False
    bronze = message_data.get("bronze_blob_path")
    bank = message_data.get("bank_id") or message_data.get("data_source_id")
    upload = message_data.get("training_upload_id") or message_data.get("upload_id")
    if not bronze or not str(bronze).strip():
        return False
    if not bank or not str(bank).strip():
        return False
    if not upload or not str(upload).strip():
        return False
    return True


# ============================================================
# Configuration
# ============================================================

KEY_VAULT_URL = os.getenv('KEY_VAULT_URL')
if not KEY_VAULT_URL:
    raise ValueError("KEY_VAULT_URL environment variable is required")

# ============================================================
# Azure Function Entry Point
# ============================================================

app = func.FunctionApp()

@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="data-ingested",
    subscription_name="start-transformation",
    connection="ServiceBusConnectionString"
)
def schema_mapping_orchestrator(message: func.ServiceBusMessage):
    """
    Azure Function orchestrator for Schema Mapping Pipeline (Systems 0-4)
    
    Triggered by Service Bus message from ADF when training data is uploaded.
    
    Expected message format:
    {
        "training_upload_id": "uuid",
        "bank_id": "bank-001",
        "bronze_blob_path": "bronze/training/bank-001/2026-02-24/upload-123.csv",
        "date": "2026-02-24"  # Optional, extracted from path if not provided
    }
    
    Args:
        message: Service Bus message with training upload metadata
    """
    try:
        # Parse message body - Azure Functions v2 programming model
        # The message body can be bytes, string, or already a dict depending on content_type
        message_body_raw = message.get_body()
        
        # Handle different message body types
        if isinstance(message_body_raw, bytes):
            message_body = message_body_raw.decode('utf-8')
        elif isinstance(message_body_raw, str):
            message_body = message_body_raw
        else:
            # If it's already a dict (unlikely but possible)
            message_body = str(message_body_raw)
        
        # Parse JSON
        try:
            message_data = json.loads(message_body)
        except json.JSONDecodeError:
            # If message_body is already a dict, use it directly
            if isinstance(message_body_raw, dict):
                message_data = message_body_raw
            else:
                raise
        
        logger.warning(
            "Schema mapping request: message_id=%s training_upload_id=%s",
            message.message_id,
            message_data.get("training_upload_id", "unknown"),
        )
        logger.debug(
            "Message body (first 200 chars): %s",
            message_body[:200] if isinstance(message_body, str) else str(message_body)[:200],
        )
        logger.debug(
            "Parsed message_data keys: %s",
            list(message_data.keys()) if isinstance(message_data, dict) else "NOT A DICT",
        )
        logger.debug("Parsed message_data: %s", message_data)
        
        # Skip error messages - they don't trigger transformation
        # Error messages have 'error_report' and 'status: ERROR' but no 'bank_id' or 'bronze_blob_path'
        if message_data.get('status') == 'ERROR' or 'error_report' in message_data:
            logger.debug(
                "Skipping error message for training_upload_id=%s (error notification, not transformation).",
                message_data.get("training_upload_id"),
            )
            return  # Don't process error messages

        if not _is_schema_mapping_trigger(message_data):
            logger.debug(
                "Skipping message: not a bronze start-transformation payload "
                "(need training_upload_id or upload_id, bank_id or data_source_id, bronze_blob_path). "
                "message_id=%s keys=%s",
                message.message_id,
                list(message_data.keys()),
            )
            return

        # Get orchestrator instance
        orchestrator = get_orchestrator(key_vault_url=KEY_VAULT_URL)
        
        # Run pipeline (Systems 0-4)
        result = orchestrator.run_pipeline(message_data)
        
        logger.warning(
            "Schema mapping pipeline completed: training_upload_id=%s",
            result.get("training_upload_id"),
        )
        
    except Exception as e:
        logger.error(
            f"Error in schema mapping orchestrator: {str(e)}",
            exc_info=True
        )
        # Error handling is done inside orchestrator.run_pipeline()
        # Re-raise to fail the function and trigger retry if configured
        raise
