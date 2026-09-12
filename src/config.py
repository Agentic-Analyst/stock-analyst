#!/usr/bin/env python3
"""
config.py - Centralized configuration for stock-analyst project

This module provides all default configuration values used throughout the project.
Update values here once to change behavior everywhere.
"""

import os


def _positive_env_int(name: str, default: int, minimum: int = 1) -> int:
    """Read an integer knob without making a malformed server env fatal."""
    try:
        return max(minimum, int(os.getenv(name, str(default)) or default))
    except (TypeError, ValueError):
        return max(minimum, default)

# Article scraping and filtering defaults
class ArticleConfig:
    """Configuration for article scraping and filtering operations."""
    
    # Maximum number of articles to scrape/search
    MAX_ARTICLES = 30
    
    # Minimum relevance score for article filtering (0-10 scale)
    MIN_SCORE = 5.0
    
    # Minimum confidence for screening insights (0-1 scale)
    MIN_CONFIDENCE = 0.6

    # Investment catalysts must be current.  The old pipeline called every
    # stored document "recent," allowing years-old news to drive today's
    # sentiment and to suppress scraping indefinitely.
    NEWS_MAX_AGE_DAYS = _positive_env_int("NEWS_MAX_AGE_DAYS", 90)
    NEWS_MIN_FRESH_ARTICLES = _positive_env_int("NEWS_MIN_FRESH_ARTICLES", 8)
    NEWS_CANDIDATE_LIMIT = max(
        MAX_ARTICLES, _positive_env_int("NEWS_CANDIDATE_LIMIT", 250)
    )


# Backward compatibility - expose at module level for easy imports
MAX_ARTICLES = ArticleConfig.MAX_ARTICLES
MIN_SCORE = ArticleConfig.MIN_SCORE
MIN_CONFIDENCE = ArticleConfig.MIN_CONFIDENCE
NEWS_MAX_AGE_DAYS = ArticleConfig.NEWS_MAX_AGE_DAYS
NEWS_MIN_FRESH_ARTICLES = ArticleConfig.NEWS_MIN_FRESH_ARTICLES
NEWS_CANDIDATE_LIMIT = ArticleConfig.NEWS_CANDIDATE_LIMIT
