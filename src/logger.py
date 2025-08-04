#!/usr/bin/env python3
"""
logger.py - Centralized logging utility for stock analysis pipeline.

This module provides a unified logging system that saves all logs to data/{ticker}/info.log
and provides both file logging and console output with proper formatting.
"""

import logging
import pathlib
from datetime import datetime
from typing import Optional

class StockAnalystLogger:
    """Centralized logger for the stock analysis pipeline."""
    
    def __init__(self, ticker: str, console_level: str = "INFO"):
        """
        Initialize logger for a specific ticker.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            console_level: Console logging level ('DEBUG', 'INFO', 'WARNING', 'ERROR')
        """
        self.ticker = ticker.upper()
        self.data_dir = pathlib.Path("data") / self.ticker
        self.log_file = self.data_dir / "info.log"
        
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Create logger
        self.logger = logging.getLogger(f"stock-analyst-{self.ticker}")
        self.logger.setLevel(logging.DEBUG)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # File handler - logs everything
        file_handler = logging.FileHandler(self.log_file, mode='a', encoding='utf-8')
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
        self.logger.info("=" * 80)
        self.logger.info(f"🚀 Stock Analysis Pipeline Session Started - {self.ticker}")
        self.logger.info(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"📂 Log file: {self.log_file}")
        self.logger.info("=" * 80)
    
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
        separator = "=" * 50
        self.logger.info(f"\n{separator}")
        self.logger.info(f"🔥 STAGE: {stage_name}")
        if description:
            self.logger.info(f"📋 {description}")
        self.logger.info(separator)
    
    def stage_end(self, stage_name: str, success: bool = True, stats: Optional[dict] = None):
        """Log the end of a pipeline stage."""
        status = "✅ COMPLETED" if success else "❌ FAILED"
        self.logger.info(f"🏁 {stage_name} - {status}")
        
        if stats:
            for key, value in stats.items():
                self.logger.info(f"   📊 {key}: {value}")
        
        self.logger.info("-" * 50)
    
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
        self.logger.info("=" * 80)
        self.logger.info(f"🏁 PIPELINE SESSION COMPLETED - {self.ticker}")
        self.logger.info(f"⏱️  Total Duration: {total_duration:.1f} seconds")
        self.logger.info(f"✅ Stages Completed: {', '.join(stages_completed)}")
        self.logger.info(f"📂 All logs saved to: {self.log_file}")
        self.logger.info("=" * 80)
    
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

def setup_logger(ticker: str, console_level: str = "INFO") -> StockAnalystLogger:
    """Setup and return a new logger instance."""
    logger = StockAnalystLogger(ticker, console_level)
    set_logger(logger)
    return logger

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
