"""
ADF Pipeline Trigger - Azure Function
Triggers Azure Data Factory pipeline when Service Bus message is received

This function:
- Receives messages from Service Bus topic 'data-awaits-ingestion' subscription 'adf-trigger-subscription'
- Retrieves Key Vault secrets (ServiceBusNamespace, FileChecksumCalculatorFunctionBaseUrl, FileChecksumCalculatorFunctionKey)
- Triggers ADF pipeline via REST API with all required parameters
"""

import azure.functions as func
import logging
import os
import sys
import json
from pathlib import Path
from typing import Any, Dict

# Configure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Suppress verbose Azure SDK logs
azure_loggers = [
    'azure.identity',
    'azure.core.pipeline.policies.http_logging_policy',
    'urllib3.connectionpool'
]
for logger_name in azure_loggers:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Add paths for imports
CURRENT_DIR = Path(__file__).parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# ============================================================
# Azure Function Entry Point
# ============================================================

app = func.FunctionApp()

@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="data-awaits-ingestion",
    subscription_name="adf-trigger-subscription",
    connection="ServiceBusConnectionString"
)
def adf_pipeline_trigger(message: func.ServiceBusMessage):
    """
    Azure Function for triggering ADF pipeline
    
    Triggered by a Service Bus message from data-awaits-ingestion topic.
    This function:
    - Parses the incoming message body
    - Retrieves Key Vault secrets
    - Triggers ADF pipeline via REST API with all parameters
    """
    # Import here to avoid import-time errors during function discovery
    try:
        from scripts.trigger_adf_pipeline import trigger_adf_pipeline_from_message
    except ImportError as e:
        logger.error(f"Failed to import trigger_adf_pipeline_from_message: {e}", exc_info=True)
        raise

    # Verify required environment variables
    KEY_VAULT_URL = os.getenv('KEY_VAULT_URL')
    if not KEY_VAULT_URL:
        logger.error("KEY_VAULT_URL environment variable is required")
        return

    ADF_SUBSCRIPTION_ID = os.getenv('ADF_SUBSCRIPTION_ID')
    ADF_RESOURCE_GROUP = os.getenv('ADF_RESOURCE_GROUP')
    ADF_FACTORY_NAME = os.getenv('ADF_FACTORY_NAME')
    ADF_PIPELINE_NAME = os.getenv('ADF_PIPELINE_NAME', 'pipeline-training-data-ingestion')

    if not all([ADF_SUBSCRIPTION_ID, ADF_RESOURCE_GROUP, ADF_FACTORY_NAME]):
        logger.error("ADF configuration missing. Required: ADF_SUBSCRIPTION_ID, ADF_RESOURCE_GROUP, ADF_FACTORY_NAME")
        return

    def _parse_message_body(msg: func.ServiceBusMessage) -> Dict[str, Any]:
        """Parse Service Bus message body to dictionary"""
        body_bytes = msg.get_body()
        if isinstance(body_bytes, (bytes, bytearray)):
            body_str = body_bytes.decode("utf-8")
        else:
            body_str = str(body_bytes)
        return json.loads(body_str)

    try:
        logger.warning(
            "ADF pipeline trigger: message_id=%s",
            message.message_id,
        )

        message_data = _parse_message_body(message)
        logger.warning(
            "ADF trigger parsed: training_upload_id=%s data_source_id=%s",
            message_data.get("training_upload_id"),
            message_data.get("data_source_id"),
        )
        logger.debug("Full message data: %s", json.dumps(message_data, indent=2))

        # Trigger ADF pipeline
        result = trigger_adf_pipeline_from_message(
            message_data=message_data,
            key_vault_url=KEY_VAULT_URL,
            subscription_id=ADF_SUBSCRIPTION_ID,
            resource_group=ADF_RESOURCE_GROUP,
            factory_name=ADF_FACTORY_NAME,
            pipeline_name=ADF_PIPELINE_NAME
        )

        if result:
            logger.warning(
                "ADF pipeline triggered: run_id=%s",
                result.get("runId"),
            )
        else:
            logger.error("Failed to trigger ADF pipeline")

    except Exception as e:
        # Log but DO NOT re-raise – we want Log + Complete semantics
        logger.error(
            f"Error in ADF pipeline trigger function: {str(e)}",
            exc_info=True,
        )
