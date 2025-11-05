"""
agentic_pipeline - Cyclical Agentic Workflow for Financial Analysis

This package implements a LangGraph-based workflow with:
- Central FinancialState for tracking analysis progress
- Supervisor Agent for intelligent routing
- Specialized Agent Nodes for data collection, analysis, modeling, and reporting
- Deterministic + LLM-powered decision making

Core Components:
- state.py: FinancialState, PipelineConfig, enums
- supervisor.py: Routing logic and decision making
- agents/: Individual agent implementations
- graph.py: LangGraph workflow assembly
- runner.py: CLI and graph invocation
"""

from src.agents.agentic_pipeline.state import (
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

from src.agents.agentic_pipeline.supervisor import (
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
