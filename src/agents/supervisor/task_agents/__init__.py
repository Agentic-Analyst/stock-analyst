"""
Supervisor Task Agent Nodes

This package contains the specialized task agent node implementations that wrap
domain-specific agents and integrate with the supervisor workflow.

Each task agent node:
- Accepts FinancialState as input
- Performs domain-specific work
- Updates FinancialState with results
- Returns updated state for supervisor routing
"""

from .financial_data_agent import financial_data_agent
from .news_analysis_agent import news_analysis_agent
from .model_generation_agent import model_generation_agent
from .report_generator_agent import report_generator_agent

__all__ = [
    'financial_data_agent',
    'news_analysis_agent',
    'model_generation_agent',
    'report_generator_agent',
]

__version__ = '1.0.0'
