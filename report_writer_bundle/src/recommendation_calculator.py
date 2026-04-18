#!/usr/bin/env python3
"""
recommendation_calculator.py - Deterministic Financial Calculator

This module computes ALL numbers (expected return, price targets, ranges, rating)
using deterministic formulas. The LLM never touches these numbers.

Design Philosophy:
- Calculator = Code (deterministic, auditable, reproducible)
- Explanations = LLM (narrative, judgment, evidence linkage)
- Validation = Code + Critic LLM (integrity checks)
"""

import math
from typing import Dict, Any, Optional
from datetime import date


class RecommendationCalculator:
    """
    Deterministic calculator for investment recommendations.
    All numbers are computed using transparent, auditable formulas.
    """
    
    # Sector-specific premium adjustments
    # Quality companies in these sectors often trade above DCF
    SECTOR_PREMIUM_ADJUSTMENTS = {
        "Technology": 0.50,  # Ecosystem value, network effects
        "Healthcare": 0.30,  # R&D pipeline value, regulatory moats
        "Consumer Discretionary": 0.20,  # Brand value
        "Consumer Staples": 0.15,
        "Financial Services": 0.10,
        "Industrials": 0.15,
        "default": 0.20
    }
    
    # Volatility caps for price movements
    MAX_3M_MOVEMENT = 0.12   # ±12%
    MAX_6M_MOVEMENT = 0.20   # ±20%
    MAX_12M_MOVEMENT = 0.30  # ±30%
    
    # Rating bands (based on expected return)
    RATING_BANDS = {
        "STRONG BUY": (20.0, float('inf')),
        "BUY": (10.0, 20.0),
        "HOLD": (-5.0, 10.0),
        "SELL": (-20.0, -5.0),
        "STRONG SELL": (float('-inf'), -20.0)
    }
    
    def __init__(self, sector: str = "default"):
        self.sector = sector
        self.sector_adjustment = self.SECTOR_PREMIUM_ADJUSTMENTS.get(
            sector, 
            self.SECTOR_PREMIUM_ADJUSTMENTS["default"]
        )
    
    def calculate_fixed_numbers(
        self,
        ticker: str,
        current_price: float,
        dcf_perpetual: float,
        dcf_exit: float,
        catalyst_score_pct: float,
        risk_score_pct: float,
        momentum_score_pct: float,
        hist_vol_annual_pct: float,
        survival_risk: bool = False
    ) -> Dict[str, Any]:
        """
        Calculate all fixed numbers deterministically.
        
        Returns a complete FixedNumbers payload that LLM cannot modify.
        """
        
        # Handle None values for ETFs or missing data
        if current_price is None or current_price == 0:
            current_price = 0.01  # Avoid division by zero
        if dcf_perpetual is None:
            dcf_perpetual = 0
        if dcf_exit is None:
            dcf_exit = 0
        if catalyst_score_pct is None:
            catalyst_score_pct = 0
        if risk_score_pct is None:
            risk_score_pct = 0
        if momentum_score_pct is None:
            momentum_score_pct = 0
        if hist_vol_annual_pct is None:
            hist_vol_annual_pct = 18.0
        
        # 1. DCF average
        dcf_avg = (dcf_perpetual + dcf_exit) / 2 if dcf_perpetual and dcf_exit else 0
        
        # 2. Raw valuation gap
        raw_val_gap_pct = ((dcf_avg / current_price - 1) * 100) if current_price > 0 else 0
        
        # 3. Adjusted valuation gap (sector premium)
        adj_val_gap_pct = raw_val_gap_pct * (1 - self.sector_adjustment)
        
        # 4. Expected return (weighted formula)
        # 40% valuation + 40% catalysts/risks + 20% momentum
        net_catalyst_risk_pct = catalyst_score_pct - risk_score_pct
        
        expected_return_pct = (
            0.40 * adj_val_gap_pct +
            0.40 * net_catalyst_risk_pct +
            0.20 * momentum_score_pct
        )
        
        # 5. Apply volatility caps (unless survival risk)
        if not survival_risk:
            expected_return_pct = max(
                min(expected_return_pct, self.MAX_12M_MOVEMENT * 100),
                -self.MAX_12M_MOVEMENT * 100
            )
        
        # 6. Calculate price targets
        # Progressive targets: 3M gets 33% of ER, 6M gets 67%, 12M gets 100%
        target_3m = current_price * (1 + 0.33 * expected_return_pct / 100)
        target_6m = current_price * (1 + 0.67 * expected_return_pct / 100)
        target_12m = current_price * (1 + expected_return_pct / 100)
        
        # Apply individual caps if not survival risk
        if not survival_risk:
            target_3m = self._apply_cap(current_price, target_3m, self.MAX_3M_MOVEMENT)
            target_6m = self._apply_cap(current_price, target_6m, self.MAX_6M_MOVEMENT)
            target_12m = self._apply_cap(current_price, target_12m, self.MAX_12M_MOVEMENT)
        
        # 7. Calculate confidence ranges using volatility
        # Range = ± (σ_annual * sqrt(horizon/12))
        vol_decimal = hist_vol_annual_pct / 100
        
        range_3m_pct = vol_decimal * math.sqrt(3/12) * 100  # 3-month
        range_6m_pct = vol_decimal * math.sqrt(6/12) * 100  # 6-month
        range_12m_pct = vol_decimal * 100                    # 12-month
        
        # Apply caps to ranges
        if not survival_risk:
            range_3m_pct = min(range_3m_pct, self.MAX_3M_MOVEMENT * 100)
            range_6m_pct = min(range_6m_pct, self.MAX_6M_MOVEMENT * 100)
            range_12m_pct = min(range_12m_pct, self.MAX_12M_MOVEMENT * 100)
        
        # 8. Calculate range bounds
        targets_with_ranges = {
            "m3": {
                "price": round(target_3m, 2),
                "range_low": round(target_3m * (1 - range_3m_pct / 100), 2),
                "range_high": round(target_3m * (1 + range_3m_pct / 100), 2)
            },
            "m6": {
                "price": round(target_6m, 2),
                "range_low": round(target_6m * (1 - range_6m_pct / 100), 2),
                "range_high": round(target_6m * (1 + range_6m_pct / 100), 2)
            },
            "m12": {
                "price": round(target_12m, 2),
                "range_low": round(target_12m * (1 - range_12m_pct / 100), 2),
                "range_high": round(target_12m * (1 + range_12m_pct / 100), 2)
            }
        }
        
        # 9. Determine rating
        rating = self._determine_rating(expected_return_pct)
        
        # 10. Build complete fixed numbers payload
        return {
            "as_of": str(date.today()),
            "ticker": ticker,
            "current_price": current_price,
            "expected_return_pct_12m": round(expected_return_pct, 2),
            "targets": targets_with_ranges,
            "rating": rating,
            "inputs": {
                "raw_val_gap_pct": round(raw_val_gap_pct, 2),
                "sector_premium_adjustment": self.sector_adjustment,
                "adj_val_gap_pct": round(adj_val_gap_pct, 2),
                "catalyst_score_pct": round(catalyst_score_pct, 2),
                "risk_score_pct": round(risk_score_pct, 2),
                "net_catalyst_risk_pct": round(net_catalyst_risk_pct, 2),
                "momentum_score_pct": round(momentum_score_pct, 2),
                "hist_vol_annual_pct": round(hist_vol_annual_pct, 2)
            }
        }
    
    def _apply_cap(self, base: float, target: float, cap: float) -> float:
        """Apply movement cap to target price."""
        max_price = base * (1 + cap)
        min_price = base * (1 - cap)
        return max(min(target, max_price), min_price)
    
    def _determine_rating(self, expected_return_pct: float) -> str:
        """Determine rating based on expected return."""
        for rating, (lower, upper) in self.RATING_BANDS.items():
            if lower <= expected_return_pct < upper:
                return rating
        return "HOLD"  # Default
    
    def estimate_catalyst_impact(self, catalysts: list) -> float:
        """
        Estimate total catalyst impact from screening data.
        
        Formula: Sum of (confidence × estimated_impact)
        Cap at 25% total.
        """
        if not catalysts:
            return 0.0
        
        total_impact = 0.0
        for cat in catalysts:
            confidence = cat.get('confidence', 0.5)
            
            # Estimate impact based on timeline and type
            timeline = cat.get('timeline', 'medium-term')
            cat_type = cat.get('type', 'other')
            
            # Base impact multipliers
            timeline_mult = {
                'immediate': 1.0,
                'short-term': 0.9,
                'medium-term': 0.7,
                'long-term': 0.5
            }.get(timeline, 0.7)
            
            type_mult = {
                'financial': 1.0,
                'product': 0.8,
                'market': 0.7,
                'regulatory': 0.6
            }.get(cat_type, 0.6)
            
            # Each catalyst contributes up to 8%
            impact = confidence * timeline_mult * type_mult * 8.0
            total_impact += impact
        
        # Cap at 25%
        return min(total_impact, 25.0)
    
    def estimate_risk_impact(self, risks: list) -> float:
        """
        Estimate total risk impact from screening data.
        
        Formula: Sum of (severity × likelihood × weight)
        Cap at 25% total.
        """
        if not risks:
            return 0.0
        
        severity_map = {
            'low': 0.25,
            'medium': 0.50,
            'high': 0.75,
            'very_high': 0.90
        }
        
        likelihood_map = {
            'unlikely': 0.20,
            'possible': 0.40,
            'likely': 0.60,
            'very_likely': 0.80,
            'certain': 0.95,
            'high': 0.70,  # Fallback mapping
            'medium': 0.50
        }
        
        total_impact = 0.0
        for risk in risks:
            severity = risk.get('severity', 'medium')
            likelihood = risk.get('likelihood', 'possible')
            confidence = risk.get('confidence', 0.5)
            
            # Convert to numeric values
            if isinstance(severity, str):
                severity_val = severity_map.get(severity.lower(), 0.5)
            else:
                severity_val = severity
            
            if isinstance(likelihood, str):
                likelihood_val = likelihood_map.get(likelihood.lower(), 0.5)
            else:
                likelihood_val = likelihood
            
            # Each risk contributes up to 10%
            impact = severity_val * likelihood_val * confidence * 10.0
            total_impact += impact
        
        # Cap at 25%
        return min(total_impact, 25.0)
    
    def calculate_momentum(
        self,
        current_price: float,
        week_52_low: float,
        week_52_high: float,
        sentiment: str
    ) -> float:
        """
        Calculate momentum score.
        
        Combines:
        - Price position in 52-week range
        - Sentiment score
        
        Capped at ±10%
        """
        # Handle None values for ETFs or missing data
        if current_price is None:
            current_price = 0
        if week_52_low is None:
            week_52_low = current_price
        if week_52_high is None:
            week_52_high = current_price
            
        # Price position momentum (0-10%)
        if week_52_high > week_52_low:
            price_range = week_52_high - week_52_low
            position = (current_price - week_52_low) / price_range
            price_momentum = (position - 0.5) * 20  # Maps 0-1 to -10% to +10%
        else:
            price_momentum = 0.0
        
        # Sentiment momentum (-5% to +5%)
        sentiment_map = {
            'very_positive': 5.0,
            'positive': 3.0,
            'bullish': 3.0,
            'neutral': 0.0,
            'negative': -3.0,
            'bearish': -3.0,
            'very_negative': -5.0
        }
        
        sentiment_lower = sentiment.lower() if isinstance(sentiment, str) else 'neutral'
        sentiment_momentum = sentiment_map.get(sentiment_lower, 0.0)
        
        # Total momentum (capped at ±10%)
        total_momentum = price_momentum + sentiment_momentum
        return max(min(total_momentum, 10.0), -10.0)
