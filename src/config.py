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


def _bounded_env_float(
    name: str, default: float, *, minimum: float, maximum: float,
) -> float:
    """Read a finite bounded timeout/ratio knob with a safe fallback."""
    try:
        value = float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    if value != value or value in (float("inf"), float("-inf")):
        value = default
    return min(maximum, max(minimum, value))

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
    # A provider call should not hold an interactive research run for the
    # client's historical 60+ second default.  Fifteen seconds still covered
    # the successful first query in the launch dry run; operators may tune it
    # only within a deliberately narrow reliability/latency band.
    SERPAPI_SEARCH_TIMEOUT_SECONDS = _bounded_env_float(
        "SERPAPI_SEARCH_TIMEOUT_SECONDS", 15.0, minimum=5.0, maximum=30.0,
    )


# Backward compatibility - expose at module level for easy imports
MAX_ARTICLES = ArticleConfig.MAX_ARTICLES
MIN_SCORE = ArticleConfig.MIN_SCORE
MIN_CONFIDENCE = ArticleConfig.MIN_CONFIDENCE
NEWS_MAX_AGE_DAYS = ArticleConfig.NEWS_MAX_AGE_DAYS
NEWS_MIN_FRESH_ARTICLES = ArticleConfig.NEWS_MIN_FRESH_ARTICLES
NEWS_CANDIDATE_LIMIT = ArticleConfig.NEWS_CANDIDATE_LIMIT
SERPAPI_SEARCH_TIMEOUT_SECONDS = ArticleConfig.SERPAPI_SEARCH_TIMEOUT_SECONDS
