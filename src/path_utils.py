#!/usr/bin/env python3
"""
path_utils.py - Utilities for managing data paths in the stock analysis pipeline.

This module provides consistent path generation and management for user data organization.
"""

import os
import pathlib
from datetime import datetime
from typing import Any

# Use environment variable for data path, default to local development
DATA_ROOT = pathlib.Path(os.getenv('DATA_PATH', 'data'))


def safe_path_component(value: Any, label: str, *, max_length: int = 160) -> str:
    """Return one non-traversing filesystem path component.

    This module is called by HTTP jobs, scheduled jobs, local scripts, and
    values extracted by an LLM.  Enforce path safety here instead of relying on
    every upstream caller to validate identically.
    """
    component = str(value or "").strip()
    if (
        not component
        or len(component) > max_length
        or component in {".", ".."}
        or "/" in component
        or "\\" in component
        or "\x00" in component
        or any(ord(char) < 32 or ord(char) == 127 for char in component)
        or pathlib.PurePath(component).parts != (component,)
    ):
        raise ValueError(f"Invalid {label} path component")
    return component

def get_analysis_path(email: str, ticker: str, timestamp: str = None) -> pathlib.Path:
    """
    Generate the analysis path structure: data/email/ticker/timestamp.
    
    Args:
        email: User's email address
        ticker: Stock ticker symbol
        timestamp: Optional timestamp. If None, current time will be used.
        
    Returns:
        Pathlib.Path object pointing to the analysis directory
    """
    if timestamp is None:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_email = safe_path_component(email, "email").lower()
    safe_ticker = safe_path_component(ticker, "ticker", max_length=80).upper()
    safe_timestamp = safe_path_component(timestamp, "timestamp", max_length=80)
    return DATA_ROOT / safe_email / safe_ticker / safe_timestamp

def get_latest_analysis_path(email: str, ticker: str) -> pathlib.Path:
    """
    Get the latest analysis path for a user and ticker.
    
    Args:
        email: User's email address
        ticker: Stock ticker symbol
        
    Returns:
        Pathlib.Path object pointing to latest analysis directory
    """
    safe_email = safe_path_component(email, "email").lower()
    safe_ticker = safe_path_component(ticker, "ticker", max_length=80).upper()
    base_path = DATA_ROOT / safe_email / safe_ticker
    if not base_path.exists():
        return None
        
    # List all timestamp directories and find the latest
    try:
        latest = max(p for p in base_path.iterdir() if p.is_dir())
        return latest
    except ValueError:  # No subdirectories
        return None

def ensure_analysis_paths(analysis_path: pathlib.Path) -> None:
    """
    Ensure all necessary subdirectories exist in the analysis path.
    
    Args:
        analysis_path: Base analysis path from get_analysis_path()
    """
    # Create standard subdirectories
    (analysis_path / "financials").mkdir(parents=True, exist_ok=True)
    # Note: "filtered" folder removed - articles now stored in MongoDB database
    (analysis_path / "searched").mkdir(parents=True, exist_ok=True)
    (analysis_path / "screened").mkdir(parents=True, exist_ok=True)
    (analysis_path / "reports").mkdir(parents=True, exist_ok=True)
