"""
Training Data Ingestion - Azure Function
Processes messages from data-awaits-ingestion topic and performs file ingestion to bronze layer

This function:
- Receives messages from Service Bus topic 'data-awaits-ingestion' subscription 'temp-peek-subscription'
- Processes messages in batch mode (peeks all, queries DB, processes sequentially)
- Copies files from blob storage to Data Lake Gen2 bronze layer
- Verifies checksums and updates database status
- Publishes success messages to data-ingested topic
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
    'azure.servicebus._pyamqp',
    'azure.servicebus._servicebus_receiver',
    'azure.servicebus._servicebus_sender',
    'azure.core.pipeline.policies.http_logging_policy',
    'azure.identity',
    'urllib3.connectionpool'
]
for logger_name in azure_loggers:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Add paths for imports (same pattern as run_training_ingestion.py)
# Note: Path setup is deferred to avoid import-time errors during function discovery
CURRENT_DIR = Path(__file__).parent
FUNCTION_ROOT = CURRENT_DIR.parent

# Add current directory (training-data-ingestion) to path - this is where utils/ lives
# This MUST be added before any imports from scripts/ that import from utils/
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# ============================================================
# Azure Function Entry Point
# ============================================================

app = func.FunctionApp()

# NOTE: We import the handler inside the function to avoid import-time errors
# if KEY_VAULT_URL is not set during function discovery

@app.service_bus_topic_trigger(
    arg_name="message",
    topic_name="data-awaits-ingestion",
    subscription_name="temp-peek-subscription",
    connection="ServiceBusConnectionString"
)
def training_data_ingestion(message: func.ServiceBusMessage):
    """
    Azure Function for Training Data Ingestion Pipeline (per-message mode)
    
    Triggered by a single Service Bus message from data-awaits-ingestion topic.
    This function:
    - Does NOT peek or receive additional messages.
    - Parses the incoming message body.
    - Delegates to run_single_message_from_function, which:
        * Checks training_uploads for id with status='ingesting'.
        * If not found, logs and returns without touching DB.
        * If found, runs the ingestion pipeline and updates DB / bronze_ingestion_log.
    All errors are logged; no exceptions are propagated so the message is treated as
    successfully handled (Log + Complete semantics).
    """
    # CRITICAL: Ensure path is set up before importing
    # The utils/ directory is in the same directory as function_app.py
    # We need to add the training-data-ingestion directory to sys.path
    # BEFORE importing run_training_ingestion, which imports from utils/
    
    # Get absolute path to training-data-ingestion directory
    func_app_file = Path(__file__).resolve()
    training_root = func_app_file.parent.resolve()
    training_root_str = str(training_root)
    
    # Ensure it's at the front of sys.path
    if training_root_str in sys.path:
        sys.path.remove(training_root_str)
    sys.path.insert(0, training_root_str)
    
    # Verify utils exists
    utils_dir = training_root / "utils"
    if not utils_dir.exists():
        logger.error(f"❌ Utils directory not found at: {utils_dir}")
        logger.error(f"   Function app file: {func_app_file}")
        logger.error(f"   Training root: {training_root}")
        logger.error(f"   sys.path[0:3]: {sys.path[0:3]}")
        raise FileNotFoundError(f"Utils directory not found at: {utils_dir}")
    
    # Import here to avoid import-time errors during function discovery
    try:
        from scripts.run_training_ingestion import run_single_message_from_function
    except ImportError as e:
        logger.error(f"❌ Failed to import run_single_message_from_function: {e}", exc_info=True)
        logger.error(f"   Training root in sys.path: {training_root_str in sys.path}")
        logger.error(f"   sys.path[0:5]: {sys.path[0:5]}")
        logger.error(f"   Utils dir exists: {utils_dir.exists()}")
        logger.error(f"   Utils files: {list(utils_dir.glob('training_*.py'))}")
        raise
    
    # Verify KEY_VAULT_URL is set (only check at runtime, not import time)
    KEY_VAULT_URL = os.getenv('KEY_VAULT_URL')
    if not KEY_VAULT_URL:
        logger.error("KEY_VAULT_URL environment variable is required")
        return

    def _parse_message_body(msg: func.ServiceBusMessage) -> Dict[str, Any]:
        body_bytes = msg.get_body()
        if isinstance(body_bytes, (bytes, bytearray)):
            body_str = body_bytes.decode("utf-8")
        else:
            body_str = str(body_bytes)
        return json.loads(body_str)

    try:
        logger.warning(
            "Training data ingestion trigger: message_id=%s",
            message.message_id,
        )

        message_data = _parse_message_body(message)
        logger.warning(
            "Ingestion parsed: training_upload_id=%s data_source_id=%s",
            message_data.get("training_upload_id"),
            message_data.get("data_source_id"),
        )
        
        result = run_single_message_from_function(message_data)
        
        if result:
            logger.warning("Training data ingestion completed successfully")
        else:
            logger.warning("Training data ingestion returned False (likely skipped)")

    except Exception as e:
        # Log but DO NOT re-raise – we want Log + Complete semantics
        logger.error(
            f"Error in training data ingestion function: {str(e)}",
            exc_info=True,
        )
