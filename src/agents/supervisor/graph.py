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

from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.types import Command

from src.agents.supervisor.state import FinancialState, PipelineStage, PipelineConfig, AgentNode
from src.agents.supervisor.supervisor import route_workflow_with_llm
from src.agents.supervisor.task_agents import (
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
            AgentNode.FINANCIAL_DATA_AGENT.value: AgentNode.FINANCIAL_DATA_AGENT.value,
            AgentNode.NEWS_ANALYSIS_AGENT.value: AgentNode.NEWS_ANALYSIS_AGENT.value,
            AgentNode.MODEL_GENERATION_AGENT.value: AgentNode.MODEL_GENERATION_AGENT.value,
            AgentNode.REPORT_GENERATOR_AGENT.value: AgentNode.REPORT_GENERATOR_AGENT.value,
            AgentNode.END.value: END,
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
    
    For async contexts, use build_workflow_graph() directly with await.
    For sync contexts, use asyncio.run(build_workflow_graph()).
    
    Args:
        config: Optional PipelineConfig for agent parameters
        
    Returns:
        Compiled runnable graph
    """
    import asyncio
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
    from src.logger import get_logger
    
    logger = get_logger()
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
                if logger:
                    logger.info(f"🤖 Supervisor → {next_node}")
            else:
                if logger:
                    logger.info(f"✅ {node_name} completed")
                    if node_state.current_stage:
                        logger.info(f"   Stage: {node_state.current_stage}")


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
    from datetime import datetime
    from src.path_utils import get_analysis_path, ensure_analysis_paths
    from src.logger import setup_logger
    
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
            analysis_path=analysis_path
        )
        
        # Create config
        config = PipelineConfig(llm_model="gpt-4o-mini")
        
        # Show graph structure
        if logger:
            logger.info("")
            logger.info("="*80)
            logger.info("LANGGRAPH WORKFLOW STRUCTURE")
            logger.info("="*80)
            logger.info(visualize_graph(config))
        
        # Invoke workflow
        if logger:
            logger.info("")
            logger.info("="*80)
            logger.info("RUNNING WORKFLOW")
            logger.info("="*80)
        
        final_state = await invoke_workflow(state, config, verbose=True)
        
        # Show results
        if logger:
            logger.info("")
            logger.info("="*80)
            logger.info("WORKFLOW RESULTS")
            logger.info("="*80)
            logger.info(f"Final Stage: {final_state.current_stage}")
            logger.info(f"Financial Data: {'✅' if final_state.financial_data else '❌'}")
            logger.info(f"News Analysis: {'✅' if final_state.news_analysis else '❌'}")
            logger.info(f"Financial Model: {'✅' if final_state.financial_model else '❌'}")
            logger.info(f"Report: {'✅' if final_state.report else '❌'}")
            logger.info(f"Total LLM Cost: ${final_state.total_llm_cost:.4f}")
            logger.info(f"Execution Log Entries: {len(final_state.execution_log)}")
    
    # Run
    asyncio.run(main())
