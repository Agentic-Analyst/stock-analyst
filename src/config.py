#!/usr/bin/env python3
"""
config.py - Centralized configuration for stock-analyst project

This module provides all default configuration values used throughout the project.
Update values here once to change behavior everywhere.
"""

# Article scraping and filtering defaults
class ArticleConfig:
    """Configuration for article scraping and filtering operations."""
    
    # Maximum number of articles to scrape/search
    MAX_ARTICLES = 15
    
    # Minimum relevance score for article filtering (0-10 scale)
    MIN_SCORE = 5.0
    
    # Minimum confidence for screening insights (0-1 scale)
    MIN_CONFIDENCE = 0.6


# Backward compatibility - expose at module level for easy imports
MAX_ARTICLES = ArticleConfig.MAX_ARTICLES
MIN_SCORE = ArticleConfig.MIN_SCORE
MIN_CONFIDENCE = ArticleConfig.MIN_CONFIDENCE
