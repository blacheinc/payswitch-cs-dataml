from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, Literal

class AgentResponse(BaseModel):
    """
    Standardized response object for all LLM Agents (Coder, Judge, etc.)
    Ensures the Agent Manager can interpret results uniformly.
    """
    agent_id: str                   # Unique identifier for the specific agent instance
    agent_type: Literal["LLMCoder", "LLMJudge", "AgentManager"]  # Identifies the role of the agent
    status: Literal["SUCCESS", "NEEDS_REVISION", "FAILURE", "FATAL_ERROR"]
    content: Any                    # The actual payload (e.g., Python code string, JSON mappings, or Judge feedback)
    reasoning: str                  # Explanation of what the agent did or why it failed
    cycle_count: int = 0            # Tracks the current iteration of the correction loop
    metadata: Dict[str, Any] = Field(default_factory=dict) # Any extra context (tokens used, time taken, etc.)
