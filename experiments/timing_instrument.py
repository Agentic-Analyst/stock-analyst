"""
Timing instrumentation for VYNN AI experiments.

This module provides utilities for measuring and recording timing metrics
during workflow execution, including:
- Per-agent execution time
- End-to-end workflow latency
- Cache hit tracking
"""

import time
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path


@dataclass
class AgentTiming:
    """Records timing for a single agent execution."""
    agent_name: str
    start_time: float
    end_time: float
    duration: float
    success: bool
    error_message: Optional[str] = None


@dataclass
class WorkflowTimings:
    """Records all timings for a complete workflow execution."""
    ticker: str
    user_prompt: str
    session_id: str
    start_time: float
    end_time: Optional[float] = None
    total_duration: Optional[float] = None
    
    # Agent-specific timings
    financial_data_time: Optional[float] = None
    news_analysis_time: Optional[float] = None
    model_generation_time: Optional[float] = None
    report_generation_time: Optional[float] = None
    
    # Detailed agent executions
    agent_timings: list[AgentTiming] = field(default_factory=list)
    
    # Cache tracking
    cache_hit: bool = False
    reuse_financial_data: bool = False
    reuse_news_data: bool = False
    reuse_model: bool = False
    
    # Workflow metadata
    total_iterations: int = 0
    completion_status: str = "not_started"
    error_message: Optional[str] = None
    
    def finalize(self):
        """Calculate final timing metrics."""
        if self.end_time and self.start_time:
            self.total_duration = self.end_time - self.start_time
        
        # Aggregate agent timings by agent type
        agent_times = {}
        for timing in self.agent_timings:
            agent_type = timing.agent_name
            if agent_type not in agent_times:
                agent_times[agent_type] = 0
            agent_times[agent_type] += timing.duration
        
        # Map to specific fields
        self.financial_data_time = agent_times.get("financial_data_agent")
        self.news_analysis_time = agent_times.get("news_analysis_agent")
        self.model_generation_time = agent_times.get("model_generation_agent")
        self.report_generation_time = agent_times.get("report_generator_agent")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Convert AgentTiming objects to dicts
        result['agent_timings'] = [asdict(t) for t in self.agent_timings]
        return result
    
    def save_to_file(self, filepath: Path):
        """Save timing data to JSON file."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)


class TimingInstrument:
    """Context manager for timing code execution."""
    
    def __init__(self, label: str = "operation"):
        self.label = label
        self.start_time = None
        self.end_time = None
        self.duration = None
    
    def __enter__(self):
        self.start_time = time.monotonic()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end_time = time.monotonic()
        self.duration = self.end_time - self.start_time
        return False  # Don't suppress exceptions
    
    def get_duration(self) -> float:
        """Get duration in seconds."""
        if self.duration is not None:
            return self.duration
        elif self.start_time is not None:
            return time.monotonic() - self.start_time
        return 0.0


def load_timing_results(experiment_dir: Path) -> list[WorkflowTimings]:
    """Load all timing results from an experiment directory."""
    results = []
    for json_file in experiment_dir.glob("timing_*.json"):
        with open(json_file, 'r') as f:
            data = json.load(f)
            # Reconstruct AgentTiming objects
            agent_timings = [AgentTiming(**t) for t in data.get('agent_timings', [])]
            data['agent_timings'] = agent_timings
            results.append(WorkflowTimings(**data))
    return results


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    else:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
