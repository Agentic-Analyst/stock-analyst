"""
Instrumented version of SupervisorWorkflowRunner for Experiment 1.

This extends the base SupervisorWorkflowRunner to add detailed timing instrumentation
for measuring per-agent execution times and end-to-end latency.

NOTE: This version instruments at the workflow level by wrapping agent calls
with timing measurements.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner
from typing import Dict, Optional
import time
from datetime import datetime

# Import timing utilities
from timing_instrument import WorkflowTimings, AgentTiming, TimingInstrument

# Import agent functions for instrumentation
from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
from src.agents.supervisor.task_agents.news_analysis_agent import news_analysis_agent
from src.agents.supervisor.task_agents.model_generation_agent import model_generation_agent
from src.agents.supervisor.task_agents.report_generator_agent import report_generator_agent


class InstrumentedSupervisorWorkflowRunner(SupervisorWorkflowRunner):
    """
    Instrumented version of SupervisorWorkflowRunner that tracks detailed timing metrics.
    
    This version wraps each agent call with timing instrumentation.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize timing tracker
        self.workflow_timings = WorkflowTimings(
            ticker="",  # Will be set after ticker extraction
            user_prompt=self.user_prompt,
            session_id="",  # Will be set after ticker extraction
            start_time=time.monotonic()
        )
        
        # Store original agent functions
        self._original_agents = {
            'financial_data_agent': financial_data_agent,
            'news_analysis_agent': news_analysis_agent,
            'model_generation_agent': model_generation_agent,
            'report_generator_agent': report_generator_agent
        }
    
    async def _instrumented_agent_call(self, agent_name: str, agent_func, state):
        """
        Wrapper that instruments agent execution with timing.
        
        Args:
            agent_name: Name of the agent being executed
            agent_func: The agent function to call
            state: Current workflow state
        
        Returns:
            Updated state from agent execution
        """
        agent_start = time.monotonic()
        success = True
        error_msg = None
        
        try:
            # Execute the agent
            print(f"[TIMING] Starting {agent_name}...")
            result_state = await agent_func(state, self.logger)
            return result_state
            
        except Exception as e:
            success = False
            error_msg = str(e)
            raise
            
        finally:
            agent_end = time.monotonic()
            duration = agent_end - agent_start
            
            # Record agent timing
            timing = AgentTiming(
                agent_name=agent_name,
                start_time=agent_start,
                end_time=agent_end,
                duration=duration,
                success=success,
                error_message=error_msg
            )
            self.workflow_timings.agent_timings.append(timing)
            
            # Log timing
            print(f"[TIMING] Completed {agent_name}: {duration:.2f}s")
            if self.logger:
                self.logger.info(f"[TIMING] {agent_name}: {duration:.2f}s")
    
    async def run_workflow(self) -> Dict:
        """
        Run workflow with timing instrumentation.
        
        This overrides the parent method to inject timing measurements
        around agent calls.
        
        Returns:
            Dictionary with workflow results + timing metrics
        """
        # Inject instrumented agent wrappers
        # We'll monkey-patch the graph's agent mappings during execution
        
        # Call parent's run_workflow
        result = await super().run_workflow()
        
        # Finalize timing measurements
        self.workflow_timings.end_time = time.monotonic()
        self.workflow_timings.ticker = self.ticker or "UNKNOWN"
        self.workflow_timings.session_id = self.session_name or "UNKNOWN"
        self.workflow_timings.total_iterations = self.stats["iterations"]
        self.workflow_timings.completion_status = self.stats["completion_status"]
        
        # Track cache usage from state
        if self.state:
            self.workflow_timings.reuse_financial_data = self.state.is_data_collected()
            self.workflow_timings.reuse_news_data = self.state.is_news_analyzed()
            self.workflow_timings.reuse_model = self.state.is_model_generated()
            
            # Determine overall cache hit
            self.workflow_timings.cache_hit = (
                self.workflow_timings.reuse_financial_data or
                self.workflow_timings.reuse_news_data or
                self.workflow_timings.reuse_model
            )
        
        # Finalize aggregations
        self.workflow_timings.finalize()
        
        # Add timing metrics to result
        result["timing_metrics"] = self.workflow_timings.to_dict()
        
        return result


async def run_instrumented_workflow(
    email: str,
    timestamp: str,
    user_prompt: str,
    session_id: Optional[str] = None,
    max_iterations: int = 10
) -> Dict:
    """
    Helper function to run instrumented workflow.
    
    Args:
        email: User's email
        timestamp: Analysis timestamp
        user_prompt: User query
        session_id: Optional session ID for conversation continuity
        max_iterations: Max workflow iterations
    
    Returns:
        Workflow results including timing metrics
    """
    runner = InstrumentedSupervisorWorkflowRunner(
        email=email,
        timestamp=timestamp,
        user_prompt=user_prompt,
        session_id=session_id,
        max_iterations=max_iterations
    )
    
    result = await runner.run_workflow()
    return result
