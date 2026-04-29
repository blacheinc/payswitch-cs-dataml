import logging
import uuid
import json
from typing import Dict, Any, Optional
from .agent_interfaces import AgentResponse
from .openai_client_manager import OpenAIClientManager

logger = logging.getLogger(__name__)

class LLMJudge:
    """
    Acts as the Quality Assurance expert.
    Reviews the generated code and the sandbox execution results to ensure
    the target schema was perfectly met.
    """
    
    def __init__(self, client_manager: OpenAIClientManager):
        self.agent_id = f"judge-{uuid.uuid4().hex[:8]}"
        self.agent_type = "LLMJudge"
        self.client_manager = client_manager
        
    def evaluate(self, generated_code: str, sandbox_result: Dict[str, Any], target_schema: Dict[str, Any], cycle_count: int = 0) -> AgentResponse:
        client = self.client_manager.get_client()
        deployment = self.client_manager.get_deployment_name()
        
        logger.info(f"[{self.agent_id}] Starting code evaluation. Cycle: {cycle_count}")
        
        # Immediate failure if execution crashed
        if sandbox_result.get("status") == "error":
            logger.warning(f"[{self.agent_id}] Execution failed. Sending back to Coder.")
            return AgentResponse(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                status="NEEDS_REVISION",
                content=f"Execution Error: {sandbox_result.get('error')}",
                reasoning="The code caused a Python exception in the sandbox.",
                cycle_count=cycle_count
            )

        # If execution succeeded, evaluate the output columns
        system_prompt = (
            "You are an expert Data Quality Assurance Engineer. "
            "Your job is to review Python Pandas transformation code and its execution results, "
            "verifying that the final output perfectly matches a specified Target Schema."
        )
        
        user_prompt = f"""
        **Target Schema:**
        {json.dumps(target_schema, indent=2)}
        
        **Generated Code:**
        ```python
        {generated_code}
        ```
        
        **Sandbox Execution Results:**
        Execution Time (ms): {sandbox_result.get('execution_time_ms')}
        Row Count: {sandbox_result.get('row_count', 0)}
        Output Columns: {sandbox_result.get('output_columns')}
        Output Data Types: {json.dumps(sandbox_result.get('output_dtypes', {}), indent=2)}
        
        **Instructions:**
        1. Compare the Output Columns against the required columns in the Target Schema.
        2. Are all required columns present? Check both column names.
        3. Are the data types correct? Compare the actual output data types against the target schema types:
           - Target "string" should map to pandas "object" or "string"
           - Target "integer" should map to pandas "int64" or "int32"
           - Target "float" should map to pandas "float64" or "float32"
           - Target "boolean" should map to pandas "bool"
        4. If everything is perfect (all columns present AND data types match), output EXACTLY the word "SUCCESS".
        5. If there are missing columns, incorrect data types, or logic errors, output EXACTLY "NEEDS_REVISION" followed by a newline, and then detailed instructions on how the Coder should fix the code.
        """
        
        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.0, # Judge needs to be strict and deterministic
                max_tokens=1000
            )
            
            evaluation = response.choices[0].message.content.strip()
            
            if evaluation.startswith("SUCCESS"):
                return AgentResponse(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    status="SUCCESS",
                    content=None,
                    reasoning="All required columns and transformations are present.",
                    cycle_count=cycle_count
                )
            else:
                # Strip the "NEEDS_REVISION" prefix to pass just the feedback
                feedback = evaluation.replace("NEEDS_REVISION", "").strip()
                return AgentResponse(
                    agent_id=self.agent_id,
                    agent_type=self.agent_type,
                    status="NEEDS_REVISION",
                    content=feedback,
                    reasoning="Output schema did not match Target Schema or logic error detected.",
                    cycle_count=cycle_count
                )
                
        except Exception as e:
            logger.error(f"[{self.agent_id}] LLM API Call Failed: {str(e)}")
            return AgentResponse(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                status="FAILURE",
                content=None,
                reasoning=f"LLM API Call Failed: {str(e)}",
                cycle_count=cycle_count
            )
