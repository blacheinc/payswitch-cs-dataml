"""
Standalone script to test the new Agent Manager logic locally.
Listens to the 'transformed' Service Bus subscription, 
downloads 'llm_context.json' and the Parquet data,
and runs the LLMCoder and LLMJudge to generate the final script.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from azure.servicebus import ServiceBusClient
from azure.storage.filedatalake import DataLakeServiceClient
from azure.identity import AzureCliCredential, DefaultAzureCredential
import pandas as pd
import io

from utils.key_vault_reader import KeyVaultReader
from agents.openai_client_manager import OpenAIClientManager
from agents.agent_manager import AgentManager
from agents.llm_coder import LLMCoder
from agents.llm_judge import LLMJudge

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def load_dotenv(dotenv_path: str = None) -> None:
    if dotenv_path is None:
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dotenv_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(dotenv_path):
        return
    with open(dotenv_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"): continue
            if "=" not in line: continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

def main():
    load_dotenv()
    env = os.getenv("ENVIRONMENT", "local")
    key_vault_url = os.getenv("KEY_VAULT_URL", "https://blachekvruhclai6km.vault.azure.net/")
    
    # 1. Setup Singleton OpenAI Client
    # Always try to use Key Vault first for the API keys since they might not be in .env
    kv_reader = KeyVaultReader(key_vault_url)
    openai_manager = OpenAIClientManager(key_vault_reader=kv_reader)
    
    # 2. Get Service Bus
    sb_conn_str = os.getenv("ServiceBusConnectionString")
    if not sb_conn_str:
        with KeyVaultReader(key_vault_url) as kv:
            sb_conn_str = kv.get_secret("ServiceBusConnectionString")
            
    # 3. Get Data Lake
    account_url = f"https://{os.getenv('DATALAKE_STORAGE_ACCOUNT_NAME')}.dfs.core.windows.net"
    credential = AzureCliCredential() if env == "local" else DefaultAzureCredential()
    dl_client = DataLakeServiceClient(account_url=account_url, credential=credential)
    silver_fs = dl_client.get_file_system_client("silver")

    logger.info("Connecting to Service Bus (topic: data-ingested, sub: transformed)...")
    sb_client = ServiceBusClient.from_connection_string(sb_conn_str)
        receiver = sb_client.get_subscription_receiver(topic_name="data-ingested", subscription_name="transformed")
    
    # Load target schema
    target_schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agents", "target_schema.json")
    with open(target_schema_path, "r") as f:
        target_schema = json.load(f)

    with receiver:
        logger.info("Waiting for a message...")
        messages = receiver.receive_messages(max_message_count=1, max_wait_time=30)
        
        if not messages:
            logger.info("No messages found. Exiting.")
            return
            
        message = messages[0]
        try:
            body = b"".join(message.body).decode("utf-8")
            parsed_msg = json.loads(body)
            run_id = parsed_msg.get("run_id")
            
            logger.info(f"[run_id={run_id}] Received TRANSFORMED message. Downloading context from Silver...")
            
            silver_path = parsed_msg.get("transformed_file_path")
            if not silver_path:
                logger.error(f"[run_id={run_id}] 'transformed_file_path' missing from message. Full parsed message: {parsed_msg}")
                # We complete it to clear out the bad test message
                receiver.complete_message(message)
                return

            # Deduce context path
            context_path = silver_path.replace(silver_path.split("/")[-1], "llm_context.json")
            
            # Download Context
            context_client = silver_fs.get_file_client(context_path)
            context_bytes = context_client.download_file().readall()
            context_data = json.loads(context_bytes)
            
            # Download Parquet File (Sandbox Data)
            parquet_client = silver_fs.get_file_client(silver_path)
            parquet_bytes = parquet_client.download_file().readall()
            source_df = pd.read_parquet(io.BytesIO(parquet_bytes))
            logger.info(f"[run_id={run_id}] Downloaded source_df with shape {source_df.shape}")

            # 4. Initialize Agents
            manager = AgentManager(run_id=run_id, max_retries=3)
            coder = LLMCoder(client_manager=openai_manager)
            judge = LLMJudge(client_manager=openai_manager)

            # 5. Inject DataFrame into local scope so the sandbox can use it
            # The sandbox uses local_scope which we can seed.
            # We'll monkey-patch the manager's sandbox to use this source_df.
            original_sandbox = manager._local_sandbox_execute
            def _injected_sandbox(code: str):
                local_scope = {"source_df": source_df.copy(), "pd": pd}
                try:
                    import time
                    start_time = time.time()
                    exec(code, {}, local_scope)
                    end_time = time.time()
                    
                    # Get actual data types from the final_df if it exists
                    final_df = local_scope.get("final_df")
                    if final_df is not None and hasattr(final_df, 'dtypes'):
                        column_info = {
                            col: str(dtype) for col, dtype in final_df.dtypes.items()
                        }
                    else:
                        column_info = "Warning: 'final_df' not found in scope"
                    
                    return {
                        "status": "success",
                        "execution_time_ms": round((end_time - start_time) * 1000, 2),
                        "output_columns": list(final_df.columns) if final_df is not None else "Warning: 'final_df' not found in scope",
                        "output_dtypes": column_info,
                        "row_count": len(final_df) if final_df is not None else 0
                    }
                except Exception as e:
                    return {"status": "error", "error": str(e), "error_type": type(e).__name__}
            
            manager._local_sandbox_execute = _injected_sandbox

            # 6. RUN THE LOOP
            logger.info(f"[run_id={run_id}] --- STARTING AGENT WORKFLOW ---")
            final_response = manager.run_coder_judge_loop(
                coder=coder,
                judge=judge,
                context=context_data,
                target_schema=target_schema,
                client_manager=openai_manager
            )
            
            if final_response.status == "SUCCESS":
                logger.info(f"[run_id={run_id}] Workflow Complete. Generated Code:\n{final_response.content}")
            else:
                logger.error(f"[run_id={run_id}] Workflow Failed: {final_response.reasoning}")

            receiver.complete_message(message)
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            receiver.abandon_message(message)

if __name__ == "__main__":
    main()
