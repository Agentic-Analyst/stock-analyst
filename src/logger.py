#!/usr/bin/env python3
"""
logger.py - Centralized logging utility for stock analysis pipeline.

This module provides a unified logging system that saves all logs to data/{ticker}/info.log
and provides both file logging and console output with proper formatting.
"""

import logging
import pathlib
import os
import re
import sys
from datetime import datetime
from typing import Optional

# This file is imported under two names: `logger` (main.py puts src/ on
# sys.path, and the chat tools set the run logger up through it) and
# `src.logger` (FinancialState reads the run logger back through it). Python
# would load it twice, with two separate run-logger globals, so on the chat
# path FinancialState never saw the run logger and every task agent's lines,
# the report validator's verdicts among them, went to a console-only fallback
# instead of info.log. Register one module object under both names, whichever
# is imported first.
for _name in ("logger", "src.logger"):
    sys.modules.setdefault(_name, sys.modules[__name__])
del _name

class StockAnalystLogger:
    """Centralized logger for the stock analysis pipeline."""
    
    def __init__(self, ticker: str, base_path: pathlib.Path, console_level: str = "INFO", session_name: Optional[str] = None):
        """
        Initialize stock analyst logger with both console and file output.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            base_path: Base directory for logs
            console_level: Console logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR')
            session_name: Optional session identifier for chatbot continuity
        """
        self.ticker = ticker.upper()
        self.data_dir = base_path
        self.log_file = self.data_dir / "info.log"
        self.session_name = session_name  # Store session ID for output
        
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Create logger
        self.logger = logging.getLogger(f"stock-analyst-{self.ticker}")
        self.logger.setLevel(logging.DEBUG)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # File handler - logs everything
        file_handler = logging.FileHandler(self.log_file, mode='w+', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
        
        # Console handler - configurable level
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, console_level.upper()))
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # Log session start
        self.logger.info(f"🚀 Stock Analysis Pipeline Session Started - {self.ticker}")
        self.logger.info(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"📂 Log file: {self.log_file}")
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self.logger.debug(message, **kwargs)
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self.logger.info(message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """Log warning message."""
        self.logger.warning(message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        self.logger.error(message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        """Log critical message."""
        self.logger.critical(message, **kwargs)
    
    # Convenience methods for common logging patterns
    def stage_start(self, stage_name: str, description: str = ""):
        """Log the start of a pipeline stage."""
        self.logger.info("=" * 80)
        self.logger.info(f"🔥 STAGE: {stage_name}")
        if description:
            self.logger.info(f"📋 {description}")
    
    def stage_end(self, stage_name: str, success: bool = True, stats: Optional[dict] = None):
        """Log the end of a pipeline stage."""
        status = "✅ COMPLETED" if success else "❌ FAILED"
        self.logger.info(f"🏁 {stage_name} - {status}")
        
        if stats:
            for key, value in stats.items():
                self.logger.info(f"   📊 {key}: {value}")
        self.logger.info("=" * 80)

    def llm_call(self, operation: str, cost: float, tokens_used: int = None):
        """Log LLM API call information."""
        msg = f"🤖 LLM Call: {operation} | Cost: ${cost:.6f}"
        if tokens_used:
            msg += f" | Tokens: {tokens_used}"
        self.logger.info(msg)
    
    def file_operation(self, operation: str, file_path: pathlib.Path):
        """Log file operations."""
        self.logger.info(f"📁 {operation}: {file_path}")
    
    def scraping_progress(self, url: str, status: str):
        """Log scraping progress."""
        self.logger.info(f"🌐 Scraping {status}: {url}")
    
    def analysis_result(self, category: str, count: int, details: str = ""):
        """Log analysis results."""
        self.logger.info(f"🔍 {category}: {count} items{' - ' + details if details else ''}")
    
    def session_end(self, total_duration: float, stages_completed: list):
        """Log session end with summary."""
        self.logger.info(f"🏁 PIPELINE SESSION COMPLETED - {self.ticker}")
        self.logger.info(f"⏱️  Total Duration: {total_duration:.1f} seconds")
        self.logger.info(f"✅ Stages Completed: {', '.join(stages_completed)}")
        self.logger.info(f"📂 All logs saved to: {self.log_file}")
        self.logger.info("=" * 80)

    def program_end(self):
        """Log program end with summary and session ID."""
        if self.session_name:
            self.logger.info(f"SESSION_ID: {self.session_name}")
        self.logger.info(f"THE ENTIRE PROGRAM IS COMPLETED - {self.ticker}")

    def get_log_file_path(self) -> pathlib.Path:
        """Get the path to the log file."""
        return self.log_file
    
    def get_log_stats(self) -> dict:
        """Get statistics about the log file."""
        if not self.log_file.exists():
            return {"exists": False, "size": 0, "lines": 0}
        
        size = self.log_file.stat().st_size
        lines = len(self.log_file.read_text(encoding='utf-8').splitlines())
        
        return {
            "exists": True,
            "size": size,
            "lines": lines,
            "path": str(self.log_file),
            "human_size": f"{size / 1024:.1f} KB" if size > 1024 else f"{size} bytes"
        }

# Global logger instance - will be set by the main pipeline
_logger: Optional[StockAnalystLogger] = None

def get_logger() -> Optional[StockAnalystLogger]:
    """Get the current logger instance."""
    return _logger

def set_logger(logger: StockAnalystLogger):
    """Set the global logger instance."""
    global _logger
    _logger = logger

def setup_logger(ticker: str, base_path: pathlib.Path = None, console_level: str = "INFO", session_name: Optional[str] = None) -> StockAnalystLogger:
    """Setup and return a new logger instance."""
    logger = StockAnalystLogger(ticker, base_path, console_level, session_name)
    set_logger(logger)
    return logger


# What the task agents log (the agents themselves and the scrapers, filter,
# screener, model builder and report writer they hand their logger to) goes
# to agents.log beside the run's info.log, not into info.log. api-runner
# streams every info.log line to the chat page, which turns lines into the
# job's status label and acts on control phrases anywhere in them, and these
# lines carry text the run does not control: article titles, search queries,
# URLs, exception messages. A requests ConnectionError, for one, carries the
# full SerpAPI URL with its api_key, so the file is scrubbed as well.
_SECRETS = (
    (re.compile(r"mongodb(?:\+srv)?://[^\s'\"]+", re.I), "[REDACTED_DATABASE_URI]"),
    (re.compile(r"\b(?:sk|rk|pk)[-_](?:proj-|live_|test_)?[A-Za-z0-9]{20,}[A-Za-z0-9_-]*"), "[REDACTED_KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED_KEY]"),
    (re.compile(r"\bAIza[A-Za-z0-9_-]{20,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_-]?key|access[_-]?token|token|secret|password|credentials?|crumb)"
                r"(['\"]?\s*(?:[=:]|%3D)\s*['\"]?)[^\s&,;'\")}]+"), r"\1\2[REDACTED]"),
)
_CONTROL = (
    (re.compile(r"\[(ANSWER_BEGIN|ANSWER_END|FINDING|CHART_DIRECTIVE|LLM)\]", re.I), r"(\1)"),
    (re.compile(r"identified ticker\s*:", re.I), "identified ticker -"),
    (re.compile(r"entire\s+program", re.I), "entire-program"),
    (re.compile(r"session_id\s*:", re.I), "session_id -"),
    (re.compile(r"generated successfully\s*:", re.I), "generated successfully -"),
)


def scrub_untrusted(text) -> str:
    """Redact secrets and disarm the chat page's control phrases."""
    text = str(text)
    for pattern, replacement in _SECRETS + _CONTROL:
        text = pattern.sub(replacement, text)
    return text


class _ScrubbingFormatter(logging.Formatter):
    """Scrubs the finished line, tracebacks included, whatever built it."""

    def format(self, record):
        return scrub_untrusted(super().format(record))


def _agents_logger(log_file: pathlib.Path) -> logging.Logger:
    log = logging.getLogger("stock-analyst-agents:" + str(log_file).replace(".", "_"))
    if not log.handlers:
        log.setLevel(logging.DEBUG)
        log.propagate = False
        # delay: no file for a run whose agents never log.
        to_file = logging.FileHandler(log_file, mode="a", encoding="utf-8", delay=True)
        to_file.setLevel(logging.DEBUG)
        to_file.setFormatter(_ScrubbingFormatter(
            '%(asctime)s | %(levelname)-8s | agents | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
        log.addHandler(to_file)
        to_console = logging.StreamHandler()
        to_console.setLevel(logging.INFO)
        to_console.setFormatter(_ScrubbingFormatter('%(message)s'))
        log.addHandler(to_console)
    return log


class TaskAgentLog(StockAnalystLogger):
    """The run logger as the task agents see it: same run folder, agents.log."""

    def __init__(self, run_logger: StockAnalystLogger):
        self.ticker = run_logger.ticker
        self.data_dir = run_logger.data_dir
        self.session_name = run_logger.session_name
        self.log_file = self.data_dir / "agents.log"
        self.logger = _agents_logger(self.log_file)


# Convenience functions for when logger is set
def info(message: str, **kwargs):
    """Log info message using global logger."""
    if _logger:
        _logger.info(message, **kwargs)

def warning(message: str, **kwargs):
    """Log warning message using global logger."""
    if _logger:
        _logger.warning(message, **kwargs)

def error(message: str, **kwargs):
    """Log error message using global logger."""
    if _logger:
        _logger.error(message, **kwargs)

def debug(message: str, **kwargs):
    """Log debug message using global logger."""
    if _logger:
        _logger.debug(message, **kwargs)
