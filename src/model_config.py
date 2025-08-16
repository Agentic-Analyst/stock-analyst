#!/usr/bin/env python3
"""
model_config.py - Configuration constants for financial model generator.

Centralizes all default values and configuration parameters to eliminate
hardcoded constants throughout the codebase.
"""

from __future__ import annotations
from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class ModelDefaults:
    """Default parameter values for financial modeling."""
    
    # Tax rate computation
    DEFAULT_TAX_RATE: float = 0.25
    
    # WACC computation defaults
    DEFAULT_BETA: float = 1.2
    DEFAULT_RISK_FREE_RATE: float = 0.045
    DEFAULT_EQUITY_RISK_PREMIUM: float = 0.05
    
    # Terminal growth defaults
    DEFAULT_TERMINAL_GROWTH_FALLBACK: float = 0.02
    TERMINAL_GROWTH_CAGR_SCALE: float = 0.30
    MAX_TERMINAL_GROWTH_DETERMINISTIC: float = 0.03
    MAX_TERMINAL_GROWTH_LLM: float = 0.05
    
    # Working capital defaults
    DEFAULT_WORKING_CAPITAL_VALUE: float = 0.0
    
    # LLM inference settings
    LLM_CONFIDENCE_THRESHOLD: float = 0.55
    
    # LLM temperature settings
    TEMP_PARAMETER_INFERENCE: float = 0.15
    TEMP_STRATEGY_SELECTION: float = 0.1
    TEMP_TERMINAL_GROWTH: float = 0.1
    TEMP_NARRATIVE_ANALYSIS: float = 0.2
    TEMP_PARAMETER_OVERRIDES: float = 0.1
    
    # Local terminal growth sensitivity deltas
    LOCAL_TG_SENSITIVITY_DELTAS: List[float] = None
    
    # WACC computation bounds and floors
    TAX_RATE_BOUNDS: tuple = (0, 0.6)
    WACC_OVERRIDE_BOUNDS: tuple = (0.0, 0.5)
    WACC_MIN_FLOOR: float = 0.04
    WACC_MAX_CEILING: float = 0.15
    COST_OF_DEBT_FLOOR: float = 0.03
    DEFAULT_CORPORATE_TAX_RATE: float = 0.21
    
    def __post_init__(self):
        if self.LOCAL_TG_SENSITIVITY_DELTAS is None:
            self.LOCAL_TG_SENSITIVITY_DELTAS = [-0.01, -0.005, 0.0, 0.005, 0.01]


@dataclass
class ParameterBounds:
    """Parameter bounds for LLM inference and validation."""
    
    FIRST_YEAR_GROWTH: tuple = (0.0, 0.80)
    MARGIN_TARGET: tuple = (0.05, 0.60)
    MARGIN_RAMP: tuple = (0.0, 0.08)
    CAPEX_RATE: tuple = (0.0, 0.30)
    DA_RATE: tuple = (0.0, 0.25)
    NWC_RATIO: tuple = (-0.10, 0.50)
    TERMINAL_GROWTH: tuple = (0.0, 0.05)
    
    def get_bounds_dict(self) -> Dict[str, tuple]:
        """Return bounds as dictionary for easy lookup."""
        return {
            'first_year_growth': self.FIRST_YEAR_GROWTH,
            'margin_target': self.MARGIN_TARGET,
            'margin_ramp': self.MARGIN_RAMP,
            'capex_rate': self.CAPEX_RATE,
            'da_rate': self.DA_RATE,
            'nwc_ratio': self.NWC_RATIO,
            'terminal_growth': self.TERMINAL_GROWTH,
        }


@dataclass
class ExcelConfig:
    """Excel export configuration."""
    
    MAX_SHEET_NAME_LENGTH: int = 31
    HEADER_FILL_COLOR: str = "CCCCCC"
    WARNING_FILL_COLOR: str = "FFF3CD"
    
    # Sheet name mappings
    SHEET_NAMES: Dict[str, str] = None
    
    def __post_init__(self):
        if self.SHEET_NAMES is None:
            self.SHEET_NAMES = {
                "dcf_model": "DCF Model",
                "comparable_analysis": "Comparable Analysis", 
                "peer_comparables": "Peer Comps",
                "reit_ffo_affo": "FFO_AFFO",
                "sensitivity_wacc_term": "Sens WACC-TG",
                "sensitivity_growth_margin": "Sens Growth-Margin",
                "sensitivity_term_growth_local": "Sens TG Local",
            }


@dataclass
class PromptPaths:
    """File paths for prompt templates."""
    
    PARAMETER_INFERENCE: str = "prompts/parameter_inference.md"
    STRATEGY_SELECTION: str = "prompts/strategy_selection.md"
    FINANCIAL_NARRATIVE: str = "prompts/financial_narrative.md"
    PARAMETER_OVERRIDES: str = "prompts/parameter_overrides.md"


# Singleton instances
DEFAULTS = ModelDefaults()
BOUNDS = ParameterBounds()
EXCEL_CONFIG = ExcelConfig()
PROMPTS = PromptPaths()
