import logging
import uuid
import time
from typing import Dict, Any, Optional
from .agent_interfaces import AgentResponse

logger = logging.getLogger(__name__)

class AgentManager:
    """
    Orchestrates the LLM Agents (Coder, Judge).
    Manages the feedback loop, enforces maximum retry cycles, and tracks active agents.
    """
    
    def __init__(self, run_id: str, max_retries: int = 3):
        self.manager_id = f"mgr-{uuid.uuid4().hex[:8]}"
        self.run_id = run_id
        self.max_retries = max_retries
        self.current_cycle = 0
        self.active_agents: Dict[str, str] = {} # Maps agent_id -> agent_type
        
        logger.info(f"[run_id={self.run_id}] AgentManager {self.manager_id} initialized. Max retries: {self.max_retries}")

    def register_agent(self, agent_id: str, agent_type: str):
        """Logs an agent as active."""
        self.active_agents[agent_id] = agent_type
        logger.info(f"[run_id={self.run_id}] Agent {agent_id} ({agent_type}) registered. Active agents: {len(self.active_agents)}")

    def deregister_agent(self, agent_id: str):
        """Removes an agent from the active list."""
        if agent_id in self.active_agents:
            agent_type = self.active_agents.pop(agent_id)
            logger.info(f"[run_id={self.run_id}] Agent {agent_id} ({agent_type}) deregistered. Active agents: {len(self.active_agents)}")

    def get_active_agent_count(self) -> int:
        return len(self.active_agents)

    def sever_connection(self, client_manager):
        """Forces the Singleton Client Manager to close its connection."""
        logger.error(f"[run_id={self.run_id}] Circuit breaker triggered. Severing OpenAI connection.")
        client_manager.close_connection()

    def run_coder_judge_loop(self, coder, judge, context: Dict[str, Any], target_schema: Dict[str, Any], client_manager) -> AgentResponse:
        """
        Executes the primary workflow:
        1. Coder generates code.
        2. Code is executed in sandbox.
        3. Judge evaluates result.
        4. Repeats if Judge says NEEDS_REVISION, until SUCCESS or max_retries hit.
        """
        self.current_cycle = 0
        judge_feedback = None
        sandbox_result = None

        logger.info(f"[run_id={self.run_id}] Starting Coder-Judge execution loop...")

        while self.current_cycle <= self.max_retries:
            logger.info(f"[run_id={self.run_id}] --- Cycle {self.current_cycle} ---")
            
            # 1. Coder Phase
            self.register_agent(coder.agent_id, coder.agent_type)
            coder_response = coder.generate_code(
                context=context, 
                target_schema=target_schema, 
                previous_feedback=judge_feedback,
                sandbox_result=sandbox_result,
                cycle_count=self.current_cycle
            )
            self.deregister_agent(coder.agent_id)

            if coder_response.status in ["FAILURE", "FATAL_ERROR"]:
                logger.error(f"[run_id={self.run_id}] Coder failed: {coder_response.reasoning}")
                return coder_response

            # 2. Execution Phase (Sandbox)
            generated_code = coder_response.content
            logger.info(f"[run_id={self.run_id}] Executing generated code in sandbox...")
            
            # TODO: Replace with secure ACI execution later. Using local exec() for testing Phase 1.
            sandbox_result = self._local_sandbox_execute(generated_code)
            
            if sandbox_result.get("status") == "error":
                logger.warning(f"[run_id={self.run_id}] Sandbox execution error: {sandbox_result.get('error')}")
                # We do NOT fail here immediately. We pass the execution error to the Judge so it can feed it back to the Coder.

            # 3. Judge Phase
            self.register_agent(judge.agent_id, judge.agent_type)
            judge_response = judge.evaluate(
                generated_code=generated_code,
                sandbox_result=sandbox_result,
                target_schema=target_schema,
                cycle_count=self.current_cycle
            )
            self.deregister_agent(judge.agent_id)

            if judge_response.status == "SUCCESS":
                logger.info(f"[run_id={self.run_id}] Judge approved the code! Loop finished.")
                return AgentResponse(
                    agent_id=self.manager_id,
                    agent_type="AgentManager",
                    status="SUCCESS",
                    content=generated_code,
                    reasoning="Judge approved the generated code.",
                    cycle_count=self.current_cycle
                )
            elif judge_response.status == "NEEDS_REVISION":
                logger.info(f"[run_id={self.run_id}] Judge requested revision: {judge_response.reasoning}")
                judge_feedback = judge_response.content
                self.current_cycle += 1
                continue
            else:
                logger.error(f"[run_id={self.run_id}] Judge failed drastically: {judge_response.reasoning}")
                return judge_response

        # If we exit the loop, we hit max retries
        logger.error(f"[run_id={self.run_id}] Max retries ({self.max_retries}) exceeded.")
        self.sever_connection(client_manager)
        
        return AgentResponse(
            agent_id=self.manager_id,
            agent_type="AgentManager",
            status="FATAL_ERROR",
            content=None,
            reasoning=f"Exceeded maximum correction cycles ({self.max_retries}). Aborting.",
            cycle_count=self.current_cycle
        )

    def _local_sandbox_execute(self, code: str) -> Dict[str, Any]:
        """
        Placeholder local executor for Phase 1 testing.
        WARNING: Highly insecure. Will be replaced by ACI Container execution.
        """
        local_scope = {}
        try:
            # We wrap it to capture print statements or exceptions
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
            return {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__
            }
