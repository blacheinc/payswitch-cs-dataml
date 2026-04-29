import logging
import uuid
import json
from typing import Dict, Any, Optional
from .agent_interfaces import AgentResponse
from .openai_client_manager import OpenAIClientManager

logger = logging.getLogger(__name__)

class LLMCoder:
    """
    Acts as the Data Engineering expert.
    Reads the Silver context (schema, insights, pii metadata) and the target schema,
    then generates Python Pandas transformation code.
    """
    
    def __init__(self, client_manager: OpenAIClientManager):
        self.agent_id = f"coder-{uuid.uuid4().hex[:8]}"
        self.agent_type = "LLMCoder"
        self.client_manager = client_manager
        
    def generate_code(self, context: Dict[str, Any], target_schema: Dict[str, Any], previous_feedback: Optional[str] = None, sandbox_result: Optional[Dict[str, Any]] = None, cycle_count: int = 0) -> AgentResponse:
        client = self.client_manager.get_client()
        deployment = self.client_manager.get_deployment_name()
        
        logger.info(f"[{self.agent_id}] Starting code generation. Cycle: {cycle_count}")
        
        system_prompt = (
            "You are an expert Data Engineer specializing in Python and pandas. "
            "Your task is to write a standalone Python script that reads a parquet file, "
            "transforms its columns to match a Target Schema based on the provided Context Metadata, "
            "and saves the result to a new dataframe called 'final_df'."
        )
        
        user_prompt = f"""
        **Context Metadata (from Silver Layer):**
        {json.dumps(context, indent=2)}
        
        **Target Schema:**
        {json.dumps(target_schema, indent=2)}
        """
        
        if previous_feedback:
            user_prompt += f"\n\n**Previous Judge Feedback:**\n{previous_feedback}"
        
        if sandbox_result and sandbox_result.get("status") == "error":
            user_prompt += f"\n\n**Previous Execution Error:**\n{sandbox_result.get('error')}"
            
        user_prompt += (
            "\n\n**Instructions:**\n"
            "1. Analyze the Context Metadata (source columns) and map them to the Target Schema.\n"
            "2. Output ONLY raw, executable Python code. No markdown formatting, no explanations.\n"
            "3. Assume the input dataframe is loaded as `source_df`.\n"
            "4. The final transformed dataframe MUST be assigned to a variable named `final_df`.\n"
        )
        
        try:
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                max_tokens=2000
            )
            
            raw_code = response.choices[0].message.content.strip()
            # Strip markdown if the LLM ignores instructions
            if raw_code.startswith("```python"):
                raw_code = raw_code[9:]
            if raw_code.endswith("```"):
                raw_code = raw_code[:-3]
            raw_code = raw_code.strip()
            
            return AgentResponse(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                status="SUCCESS",
                content=raw_code,
                reasoning="Generated Pandas transformation code based on schema map.",
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
