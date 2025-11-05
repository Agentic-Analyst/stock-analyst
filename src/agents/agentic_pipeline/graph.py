"""
LangGraph Workflow Assembly

This module builds the cyclical LangGraph workflow that orchestrates the agentic pipeline.

Architecture:
- StateGraph with FinancialState as the state type
- Supervisor node as the entry point (makes routing decisions)
- 4 specialized agent nodes (financial_data, news_analysis, model_generation, report_generator)
- Conditional edges from supervisor to all agents (based on routing logic)
- Edges from all agents back to supervisor for next decision
- Terminal __end__ node (when all work complete)

The workflow is cyclical: Supervisor → Agent → Supervisor → Agent → ... → __end__
"""

import sys
import pathlib
from typing import Literal

# Add src directory to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent.parent))

from langgraph.graph import StateGraph, END
from langgraph.types import Command

from agents.agentic_pipeline.state import FinancialState, PipelineStage, PipelineConfig
from agents.agentic_pipeline.supervisor import route_workflow_with_llm
from agents.agentic_pipeline.agents import (
    financial_data_agent,
    news_analysis_agent,
    model_generation_agent,
    report_generator_agent,
)


def supervisor_node(state: FinancialState) -> FinancialState:
    """
    Supervisor node that decides routing.
    
    The supervisor reads the current state and uses route_workflow_with_llm() to determine
    the next agent to execute (or __end__ if complete). This enables flexible routing
    where the LLM can choose any available agent, not just sequential execution.
    
    Args:
        state: Current FinancialState
        
    Returns:
        Same state (routing decision is embedded in return for LangGraph)
    """
    # Use LLM-powered flexible routing
    next_node = route_workflow_with_llm(state)
    state.log_action(
        "supervisor",
        f"Routing decision: {next_node}"
    )
    return state


async def build_workflow_graph(config: PipelineConfig = None) -> callable:
    """
    Build the LangGraph workflow.
    
    Creates a StateGraph with the following structure:
    
    Entry Point: supervisor
    ├─ supervisor → (routes to one of):
    │  ├─ financial_data_agent → supervisor
    │  ├─ news_analysis_agent → supervisor
    │  ├─ model_generation_agent → supervisor
    │  ├─ report_generator_agent → supervisor
    │  └─ __end__ (terminal)
    │
    └─ All agents loop back to supervisor for next decision
    
    Args:
        config: Optional PipelineConfig for agent parameters
        
    Returns:
        Compiled runnable graph
    """
    
    # Create StateGraph with FinancialState
    graph = StateGraph(FinancialState)
    
    # ==================== ADD NODES ====================
    
    # Supervisor node
    graph.add_node("supervisor", supervisor_node)
    
    # Agent nodes
    graph.add_node(
        "financial_data_agent",
        lambda state: financial_data_agent(state, config)
    )
    graph.add_node(
        "news_analysis_agent",
        lambda state: news_analysis_agent(state, config)
    )
    graph.add_node(
        "model_generation_agent",
        lambda state: model_generation_agent(state, config)
    )
    graph.add_node(
        "report_generator_agent",
        lambda state: report_generator_agent(state, config)
    )
    
    # ==================== SET ENTRY POINT ====================
    
    # Supervisor is the entry point
    graph.set_entry_point("supervisor")
    
    # ==================== ADD CONDITIONAL EDGES ====================
    
    # From supervisor, route to next agent based on state
    # Uses LLM-powered flexible routing that allows skipping ahead
    graph.add_conditional_edges(
        "supervisor",
        route_workflow_with_llm,
        {
            "financial_data_agent": "financial_data_agent",
            "news_analysis_agent": "news_analysis_agent",
            "model_generation_agent": "model_generation_agent",
            "report_generator_agent": "report_generator_agent",
            "__end__": END,
        }
    )
    
    # ==================== ADD AGENT FEEDBACK EDGES ====================
    
    # All agents send results back to supervisor for next routing decision
    graph.add_edge("financial_data_agent", "supervisor")
    graph.add_edge("news_analysis_agent", "supervisor")
    graph.add_edge("model_generation_agent", "supervisor")
    graph.add_edge("report_generator_agent", "supervisor")
    
    # ==================== COMPILE GRAPH ====================
    
    # Compile the graph to make it runnable
    compiled_graph = graph.compile()
    
    return compiled_graph


def get_workflow_graph(config: PipelineConfig = None):
    """
    Get a compiled workflow graph (synchronous wrapper).
    
    For use in synchronous contexts. For async, use build_workflow_graph().
    
    Args:
        config: Optional PipelineConfig for agent parameters
        
    Returns:
        Compiled runnable graph
    """
    import asyncio
    
    try:
        # Try to get running event loop
        loop = asyncio.get_running_loop()
        # If we're already in async context, create task
        task = loop.create_task(build_workflow_graph(config))
        return task
    except RuntimeError:
        # No running loop, create new one
        return asyncio.run(build_workflow_graph(config))


# ==================== GRAPH INVOCATION ====================

async def invoke_workflow(
    state: FinancialState,
    config: PipelineConfig = None,
    verbose: bool = True
) -> FinancialState:
    """
    Invoke the workflow with a given initial state.
    
    This runs the complete cyclical workflow: Supervisor makes routing decisions,
    agents execute, results feed back to supervisor, repeat until complete.
    
    Args:
        state: Initial FinancialState
        config: Optional PipelineConfig for agent parameters
        verbose: Whether to log progress
        
    Returns:
        Final FinancialState after workflow completion
    """
    
    if verbose:
        state.log_action(
            "workflow",
            f"Starting workflow for {state.ticker}..."
        )
    
    # Build the graph
    graph = await build_workflow_graph(config)
    
    # Invoke the graph with initial state
    # The graph returns the final state after all nodes have executed
    final_state = await graph.ainvoke(state)
    
    if verbose:
        state.log_action(
            "workflow",
            f"Workflow completed. Final stage: {final_state.current_stage}"
        )
    
    return final_state


async def stream_workflow(
    state: FinancialState,
    config: PipelineConfig = None,
) -> None:
    """
    Stream workflow execution with real-time updates.
    
    Streams each node's execution, useful for monitoring progress in real-time.
    
    Args:
        state: Initial FinancialState
        config: Optional PipelineConfig for agent parameters
    """
    
    state.log_action("workflow", f"Starting workflow stream for {state.ticker}...")
    
    # Build the graph
    graph = await build_workflow_graph(config)
    
    # Stream execution
    # Each node's output is yielded as it completes
    async for step in graph.astream(state, stream_mode="updates"):
        # Each step contains node name and updated state
        for node_name, node_state in step.items():
            if node_name == "supervisor":
                next_node = route_workflow_with_llm(node_state)
                print(f"🤖 Supervisor → {next_node}")
            else:
                print(f"✅ {node_name} completed")
                if node_state.current_stage:
                    print(f"   Stage: {node_state.current_stage}")


# ==================== GRAPH VISUALIZATION ====================

def visualize_graph(config: PipelineConfig = None) -> str:
    """
    Generate ASCII visualization of the workflow graph.
    
    Useful for documentation and understanding the workflow structure.
    
    Args:
        config: Optional PipelineConfig (used for graph building)
        
    Returns:
        ASCII representation of the graph
    """
    import asyncio
    
    # Build graph in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    graph = loop.run_until_complete(build_workflow_graph(config))
    loop.close()
    
    # Get Mermaid diagram if available
    try:
        return graph.get_graph().draw_mermaid()
    except Exception:
        # Fallback to simple ASCII diagram
        return """
        Workflow Architecture:
        
        Entry → [Supervisor]
                    ↓ (route_workflow)
            ┌───┬───┬───┬────┐
            ↓   ↓   ↓   ↓    ↓
        [FD] [NA] [MG] [RG] [END]
            ↓   ↓   ↓   ↓
            └───┴───┴───┘
                ↓
            [Supervisor] → (decision)
        
        Legend:
        FD  = financial_data_agent
        NA  = news_analysis_agent
        MG  = model_generation_agent
        RG  = report_generator_agent
        END = Terminal node
        """


# ==================== EXAMPLE USAGE ====================

if __name__ == "__main__":
    """
    Example: Run the workflow
    
    python src/agents/agentic_pipeline/graph.py
    """
    
    import asyncio
    from path_utils import get_analysis_path, ensure_analysis_paths
    from logger import setup_logger
    from datetime import datetime
    
    async def main():
        # Setup
        ticker = "NVDA"
        company = "NVIDIA"
        email = "test@example.com"
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        analysis_path = get_analysis_path(email, ticker, timestamp)
        ensure_analysis_paths(analysis_path)
        
        logger = setup_logger(ticker, base_path=analysis_path)
        
        # Initialize state
        state = FinancialState(
            user_query=f"Analyze {company}",
            ticker=ticker,
            company_name=company,
            email=email,
            analysis_path=analysis_path,
            logger=logger
        )
        
        # Create config
        config = PipelineConfig(llm_model="gpt-4o-mini")
        
        # Show graph structure
        print("\n" + "="*80)
        print("LANGGRAPH WORKFLOW STRUCTURE")
        print("="*80)
        print(visualize_graph(config))
        
        # Invoke workflow
        print("\n" + "="*80)
        print("RUNNING WORKFLOW")
        print("="*80)
        
        final_state = await invoke_workflow(state, config, verbose=True)
        
        # Show results
        print("\n" + "="*80)
        print("WORKFLOW RESULTS")
        print("="*80)
        print(f"Final Stage: {final_state.current_stage}")
        print(f"Financial Data: {'✅' if final_state.financial_data else '❌'}")
        print(f"News Analysis: {'✅' if final_state.news_analysis else '❌'}")
        print(f"Financial Model: {'✅' if final_state.financial_model else '❌'}")
        print(f"Report: {'✅' if final_state.report else '❌'}")
        print(f"Total LLM Cost: ${final_state.total_llm_cost:.4f}")
        print(f"Execution Log Entries: {len(final_state.execution_log)}")
    
    # Run
    asyncio.run(main())
