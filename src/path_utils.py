#!/usr/bin/env python3
"""
path_utils.py - Utilities for managing data paths in the stock analysis pipeline.

This module provides consistent path generation and management for user data organization.
"""

import os
import pathlib
from datetime import datetime

# Use environment variable for data path, default to local development
DATA_ROOT = pathlib.Path(os.getenv('DATA_PATH', 'data'))

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
    return DATA_ROOT / email.lower() / ticker.upper() / timestamp

def get_latest_analysis_path(email: str, ticker: str) -> pathlib.Path:
    """
    Get the latest analysis path for a user and ticker.
    
    Args:
        email: User's email address
        ticker: Stock ticker symbol
        
    Returns:
        Pathlib.Path object pointing to latest analysis directory
    """
    base_path = DATA_ROOT / email.lower() / ticker.upper()
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
