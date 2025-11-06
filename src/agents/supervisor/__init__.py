"""
supervisor - Supervisor-based Workflow for Financial Analysis

This package implements a supervisor-based workflow with:
- Central FinancialState for tracking analysis progress
- Supervisor Agent for intelligent routing
- Specialized Task Agent Nodes for data collection, analysis, modeling, and reporting
- Deterministic + LLM-powered decision making

Core Components:
- state.py: FinancialState, PipelineConfig, enums
- supervisor.py: Routing logic and decision making
- task_agents/: Individual task agent implementations
- graph.py: LangGraph workflow assembly
- supervisor_agent.py: CLI and workflow invocation
"""

from src.agents.supervisor.state import (
    FinancialState,
    FinancialData,
    NewsAnalysis,
    FinancialModel,
    Report,
    PipelineConfig,
    AgentNode,
    PipelineStage,
    AnalysisObjective,
)

from src.agents.supervisor.supervisor import (
    route_workflow,
    route_workflow_with_llm,
)

__all__ = [
    "FinancialState",
    "FinancialData",
    "NewsAnalysis",
    "FinancialModel",
    "Report",
    "PipelineConfig",
    "AgentNode",
    "PipelineStage",
    "AnalysisObjective",
    "route_workflow",
    "route_workflow_with_llm",
]
