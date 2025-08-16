"""qualitative_config.py

Central configuration for qualitative & parameter mapping adjustments.
Allows future externalization / calibration (sector-specific scaling,
timeline weights overrides, source credibility, recency decay tau).
"""
from __future__ import annotations
from typing import Dict

# Sector calibration: can tune scaling/cap per sector (fallback to defaults)
SECTOR_CALIBRATION: Dict[str, Dict[str, float]] = {
    # Example entries (values conservative; adjust via backtest harness later)
    "technology": {"scaling": 0.27, "cap": 0.18},
    "financial services": {"scaling": 0.22, "cap": 0.15},
}

# Source credibility weights (simple demonstration)
SOURCE_WEIGHTS = {
    "press_release": 1.0,
    "company_filing": 1.0,
    "major_news": 0.9,
    "trade_journal": 0.8,
    "blog": 0.5,
}

# Recency decay half-life (days); effective_weight *= 0.5 ** (age_days / half_life)
RECENCY_HALF_LIFE_DAYS = 180

def sector_adjustments(sector: str | None) -> Dict[str, float]:
    if not sector: return {}
    return SECTOR_CALIBRATION.get(sector.lower(), {})

__all__ = [
    'SECTOR_CALIBRATION','SOURCE_WEIGHTS','RECENCY_HALF_LIFE_DAYS','sector_adjustments'
]
