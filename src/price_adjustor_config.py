#!/usr/bin/env python3
"""
price_adjustor_config.py - Configuration constants for price adjustor.

Centralizes all default values and configuration parameters for the price
adjustment engine to eliminate hardcoded constants.
"""

from __future__ import annotations
from typing import Dict
from dataclasses import dataclass


@dataclass
class PriceAdjustorDefaults:
    """Default parameter values for price adjustment calculations."""
    
    # Timeline weight multipliers
    TIMELINE_WEIGHTS: Dict[str, float] = None
    
    # Adjustment computation defaults
    DEFAULT_SCALING: float = 0.25
    DEFAULT_CAP: float = 0.20
    DEFAULT_MITIGATION_MAX_RELIEF: float = 0.35
    DEFAULT_TIMELINE_WEIGHT: float = 0.5
    DEFAULT_CONFIDENCE: float = 0.5
    
    # Sector adjustments
    DEFAULT_SECTOR_SCALING: float = 1.0
    DEFAULT_SECTOR_CAP: float = 1.0
    
    # Time calculation (seconds per day)
    SECONDS_PER_DAY: float = 86400.0
    
    # Percentage conversion
    PERCENTAGE_DIVISOR: float = 100.0
    
    # Default adjustment values
    DEFAULT_ADJUSTMENT_PCT: float = 0.0
    DEFAULT_ZERO_CONFIDENCE: float = 0.0
    
    # LLM settings
    DEFAULT_LLM_TEMPERATURE: float = 0.15
    DEFAULT_LLM_GUARDRAIL_THRESHOLD: float = 0.07
    
    # Additional CLI defaults
    DEFAULT_RESIDUAL_OVERLAY_CAP: float = 0.05
    DEFAULT_MATERIALITY_THRESHOLD: float = 0.005

    # Scenario multiplier guardrails (applied to mapped effective deltas)
    SCENARIO_GROWTH_MULT_RANGE = (0.5, 1.5)   # bear to aggressive bull
    SCENARIO_MARGIN_MULT_RANGE = (0.6, 1.3)
    SCENARIO_CAPEX_MULT_RANGE = (0.8, 1.2)
    SCENARIO_WACC_MULT_RANGE = (0.8, 1.2)
    # Probability guardrails (individual) and epsilon for normalization
    SCENARIO_PROB_MIN = 0.05
    SCENARIO_PROB_MAX = 0.80
    SCENARIO_PROB_EPS = 1e-6
    
    def __post_init__(self):
        if self.TIMELINE_WEIGHTS is None:
            self.TIMELINE_WEIGHTS = {
                "immediate": 1.0,
                "short-term": 0.80,
                "short term": 0.80,
                "mid-term": 0.50,
                "mid term": 0.50,
                "medium-term": 0.50,
                "long-term": 0.30,
                "long term": 0.30,
            }


@dataclass
class PromptPaths:
    """File paths for price adjustor prompt templates."""
    
    PARAMETER_DELTAS: str = "prompts/parameter_deltas.md"


# Singleton instances
ADJUSTOR_DEFAULTS = PriceAdjustorDefaults()
ADJUSTOR_PROMPTS = PromptPaths()
