"""
state.py - State Management for Supervisor Workflow

Defines the core data structures and state machine for the supervisor-based
agentic workflow.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
from src.logger import get_logger
from src.config import MAX_ARTICLES, MIN_SCORE, MIN_CONFIDENCE


class AgentNode(str, Enum):
    """Enum for all agent nodes in the workflow."""
    SUPERVISOR = "supervisor"
    FINANCIAL_DATA_AGENT = "financial_data_agent"
    NEWS_ANALYSIS_AGENT = "news_analysis_agent"
    MODEL_GENERATION_AGENT = "model_generation_agent"
    REPORT_GENERATOR_AGENT = "report_generator_agent"
    END = "__end__"


class PipelineStage(str, Enum):
    """Enum for pipeline execution stages."""
    INITIALIZED = "initialized"
    FINANCIAL_DATA_COLLECTED = "financial_data_collected"
    NEWS_ANALYSIS_COMPLETED = "news_analysis_completed"
    MODEL_GENERATED = "model_generated"
    REPORT_GENERATED = "report_generated"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisObjective(str, Enum):
    """User's analysis objective."""
    COMPREHENSIVE = "comprehensive"  # Full 7-step pipeline
    QUICK_NEWS = "quick_news"  # News analysis only
    MODEL_ONLY = "model_only"  # Financial model only
    SCREEN_ONLY = "screen_only"  # Article screening only
    CUSTOM = "custom"  # User-specified stages


@dataclass
class FinancialData:
    """Structured container for financial statement data."""
    ticker: str
    company_name: str
    json_path: Optional[str] = None  # Path to financials_annual_modeling_latest.json
    scraped_at: Optional[datetime] = None
    data_completeness: Dict[str, bool] = field(default_factory=dict)  # e.g., {"income_statement": True, "balance_sheet": False}
    key_metrics: Dict[str, Any] = field(default_factory=dict)  # Revenue, margins, growth rates, etc.
    raw_data: Dict[str, Any] = field(default_factory=dict)  # Full financial data JSON
    error: Optional[str] = None


@dataclass
class NewsAnalysis:
    """Structured container for news and screening data."""
    ticker: str
    articles_count: int = 0
    catalysts: List[Dict[str, Any]] = field(default_factory=list)
    risks: List[Dict[str, Any]] = field(default_factory=list)
    mitigations: List[Dict[str, Any]] = field(default_factory=list)
    overall_sentiment: str = "neutral"  # bullish, neutral, bearish
    key_themes: List[str] = field(default_factory=list)
    screening_data_path: Optional[str] = None  # Path to screening_data.json
    llm_cost: float = 0.0
    error: Optional[str] = None


@dataclass
class FinancialModel:
    """Structured container for generated financial model."""
    ticker: str
    model_type: str = "comprehensive dcf"  # Type of model generated
    excel_path: Optional[str] = None  # Path to Excel file
    json_computed_values_path: Optional[str] = None  # Path to computed values JSON
    valuation_metrics: Dict[str, float] = field(default_factory=dict)  # {perpetual_price, exit_multiple_price, average_price, upside_vs_market}
    assumptions: Dict[str, float] = field(default_factory=dict)  # {wacc, terminal_growth, exit_multiple}
    projections: Dict[str, List[float]] = field(default_factory=dict)  # {revenue_fy1_to_fy5, ebitda_fy1_to_fy5, fcf_fy1_to_fy5}
    adjusted_model_path: Optional[str] = None  # Path to adjusted model (if news-adjusted)
    error: Optional[str] = None


@dataclass
class Report:
    """Structured container for generated report."""
    ticker: str
    report_type: str = "professional_analyst"
    report_path: Optional[str] = None  # Path to Markdown report
    content: Optional[str] = None  # Full report content
    generated_at: Optional[datetime] = None
    llm_cost: float = 0.0
    error: Optional[str] = None


@dataclass
class ComparisonReport:
    """Comparison report for multiple tickers (NEW)."""
    tickers: List[str]
    report_path: Optional[str] = None  # Path to comparison report
    content: Optional[str] = None  # Full comparison content
    generated_at: Optional[datetime] = None
    llm_cost: float = 0.0
    
    # Comparison metrics
    relative_valuations: Dict[str, float] = field(default_factory=dict)  # Ticker -> relative valuation score
    risk_rankings: Dict[str, int] = field(default_factory=dict)  # Ticker -> risk rank (1=lowest risk)
    growth_rankings: Dict[str, int] = field(default_factory=dict)  # Ticker -> growth rank (1=highest growth)
    recommendation_summary: Dict[str, str] = field(default_factory=dict)  # Ticker -> recommendation
    error: Optional[str] = None


@dataclass
class FinancialState:
    """
    Central state machine that tracks all workflow progress and data.
    
    This is passed between all agents and updated as the workflow progresses.
    It represents the complete history and current snapshot of the analysis.
    """
    
    # User input & context
    user_query: str  # User's natural language request (e.g., "Analyze NVIDIA's financial health")
    ticker: str  # Stock ticker (e.g., "NVDA")
    company_name: str  # Full company name (e.g., "NVIDIA")
    email: str  # User email for data organization
    timestamp: str  # Timestamp for this analysis run
    objective: AnalysisObjective = AnalysisObjective.COMPREHENSIVE
    
    # Analysis base path (where all outputs are saved)
    analysis_path: Optional[str] = None
    
    # Pipeline execution tracking
    current_stage: PipelineStage = PipelineStage.INITIALIZED
    completed_stages: List[PipelineStage] = field(default_factory=list)
    next_agent: AgentNode = AgentNode.SUPERVISOR
    
    # Collected data (mutually exclusive stages)
    financial_data: Optional[FinancialData] = None
    news_analysis: Optional[NewsAnalysis] = None
    financial_model: Optional[FinancialModel] = None
    report: Optional[Report] = None
    
    # Execution metadata
    execution_log: List[Dict[str, Any]] = field(default_factory=list)  # Log of agent actions
    routing_history: List[Dict[str, Any]] = field(default_factory=list)  # History of supervisor routing decisions
    total_llm_cost: float = 0.0  # Cumulative LLM cost
    total_execution_time: float = 0.0  # Total time elapsed (seconds)
    
    # Error tracking
    errors: List[Dict[str, Any]] = field(default_factory=list)  # List of errors encountered
    last_error: Optional[str] = None
    
    # Configuration overrides (use centralized config defaults)
    max_articles: int = MAX_ARTICLES
    min_score: float = MIN_SCORE
    min_confidence: float = MIN_CONFIDENCE
    llm_model: str = "gpt-4o-mini"
    cost_limit_usd: Optional[float] = None  # Max budget for LLM calls
    
    def __post_init__(self):
        """Validate and initialize state."""
        if not self.ticker:
            raise ValueError("ticker is required")
        if not self.company_name:
            raise ValueError("company_name is required")
        if not self.email:
            raise ValueError("email is required")
    
    @property
    def logger(self):
        """
        Get the logger for the current context.
        Returns the global logger if available, otherwise creates a basic logger with custom methods.
        """
        # Try to get the global logger first (StockAnalystLogger)
        global_logger = get_logger()
        if global_logger is not None:
            return global_logger
        
        # Fallback: create a basic logger with custom methods to match StockAnalystLogger
        import logging
        logger = logging.getLogger(f"stock_analyst.{self.ticker}")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        
        # Add custom methods that StockAnalystLogger has
        if not hasattr(logger, 'scraping_progress'):
            def scraping_progress(url: str, status: str):
                """Fallback scraping_progress method."""
                logger.info(f"Scraping progress: {url} - {status}")
            logger.scraping_progress = scraping_progress
        
        if not hasattr(logger, 'set_logger'):
            def set_logger(new_logger):
                """Fallback set_logger method (no-op)."""
                pass
            logger.set_logger = set_logger
        
        return logger
    
    def is_financial_data_collected(self) -> bool:
        """Check if financial data has been collected."""
        return self.financial_data is not None and self.financial_data.error is None
    
    def is_news_analyzed(self) -> bool:
        """Check if news analysis is complete."""
        return self.news_analysis is not None and self.news_analysis.error is None
    
    def is_model_generated(self) -> bool:
        """Check if financial model has been generated."""
        return self.financial_model is not None and self.financial_model.error is None
    
    def is_report_generated(self) -> bool:
        """Check if report has been generated."""
        return self.report is not None and self.report.error is None
    
    def get_effective_logger(self, agent_name: Optional[str] = None):
        """
        Get the effective logger (always returns state logger).
        
        Args:
            agent_name: Optional agent name (kept for compatibility, not used)
            
        Returns:
            Logger instance from state
        """
        return self.logger
    
    def should_stop(self) -> bool:
        """Determine if workflow should terminate."""
        # Stop if in error state
        if self.current_stage == PipelineStage.FAILED:
            return True
        # Stop if report is generated and objective is met
        if self.is_report_generated() and self.objective == AnalysisObjective.COMPREHENSIVE:
            return True
        return False
    
    def log_action(self, agent: str, action: str, details: Optional[Dict[str, Any]] = None):
        """Log an agent action to execution history."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent,
            "action": action,
            "stage": self.current_stage.value,
            "details": details or {}
        }
        self.execution_log.append(log_entry)
        
        # Write to unified info.log
        if self.logger:
            try:
                self.logger.info(f"[{agent}] {action}")
            except Exception:
                # Best-effort logging; don't raise from logging
                pass
    
    def log_error(self, agent: str, error_message: str, details: Optional[Dict[str, Any]] = None):
        """Log an error to error history."""
        error_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent,
            "error": error_message,
            "details": details or {}
        }
        self.errors.append(error_entry)
        self.last_error = error_message
        
        # Write to unified info.log
        if self.logger:
            try:
                self.logger.error(f"[{agent}] {error_message}")
            except Exception:
                pass
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for serialization."""
        return {
            "user_query": self.user_query,
            "ticker": self.ticker,
            "company_name": self.company_name,
            "email": self.email,
            "objective": self.objective.value,
            "timestamp": self.timestamp,
            "analysis_path": self.analysis_path,
            "current_stage": self.current_stage.value,
            "completed_stages": [s.value for s in self.completed_stages],
            "next_agent": self.next_agent.value,
            "financial_data": self.financial_data.__dict__ if self.financial_data else None,
            "news_analysis": self.news_analysis.__dict__ if self.news_analysis else None,
            "financial_model": self.financial_model.__dict__ if self.financial_model else None,
            "report": self.report.__dict__ if self.report else None,
            "execution_log": self.execution_log,
            "total_llm_cost": self.total_llm_cost,
            "total_execution_time": self.total_execution_time,
            "errors": self.errors,
            "last_error": self.last_error
        }
    
    def save_to_file(self, output_path: str):
        """Save state to JSON file for audit trail."""
        with open(output_path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


@dataclass
class PipelineConfig:
    """Configuration for the entire agentic pipeline."""
    
    # LLM configuration
    llm_model: str = "gpt-4o-mini"
    llm_temperature_planner: float = 0.1  # Low temp for routing decisions
    llm_temperature_analysis: float = 0.7  # Higher temp for analysis tasks
    llm_max_retries: int = 3
    
    # Cost management
    cost_limit_usd: Optional[float] = None  # Global budget cap
    timeout_seconds: int = 3600  # 1 hour max execution time
    
    # Article scraping (use centralized config defaults)
    max_articles_to_search: int = MAX_ARTICLES
    min_filter_score: float = MIN_SCORE
    min_confidence_for_insights: float = MIN_CONFIDENCE
    
    # Model generation
    projection_years: int = 5
    use_llm_for_assumptions: bool = True
    
    # Output & logging
    save_intermediate_states: bool = True
    verbose_logging: bool = True
    
    # API keys (from environment, validated on init)
    serpapi_key: Optional[str] = None
    openai_key: Optional[str] = None
    anthropic_key: Optional[str] = None
    
    def __post_init__(self):
        """Validate configuration."""
        import os
        # Load API keys from environment if not provided
        if not self.serpapi_key:
            self.serpapi_key = os.getenv("SERPAPI_API_KEY")
        if not self.openai_key:
            self.openai_key = os.getenv("OPENAI_API_KEY")
        if not self.anthropic_key:
            self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        
        # Validate cost limit
        if self.cost_limit_usd is not None and self.cost_limit_usd <= 0:
            raise ValueError("cost_limit_usd must be positive or None")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "llm_model": self.llm_model,
            "llm_temperature_planner": self.llm_temperature_planner,
            "llm_temperature_analysis": self.llm_temperature_analysis,
            "cost_limit_usd": self.cost_limit_usd,
            "timeout_seconds": self.timeout_seconds,
            "max_articles_to_search": self.max_articles_to_search,
            "min_filter_score": self.min_filter_score,
            "min_confidence_for_insights": self.min_confidence_for_insights
        }
