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
    
    # Volatility caps for price movements
    MAX_3M_MOVEMENT = 0.12   # ±12%
    MAX_6M_MOVEMENT = 0.20   # ±20%
    MAX_12M_MOVEMENT = 0.30  # ±30%
    
    # Symmetric rating bands. The old table called -5% a SELL but required
    # +10% for BUY, mechanically creating more sell calls from equal noise.
    RATING_BANDS = {
        "STRONG BUY": (20.0, float('inf')),
        "BUY": (8.0, 20.0),
        "HOLD": (-8.0, 8.0),
        "SELL": (-20.0, -8.0),
        "STRONG SELL": (float('-inf'), -20.0)
    }
    
    def __init__(self, sector: str = "default"):
        self.sector = sector
        # Kept in the payload as zero for compatibility with old reports. A
        # sector label is not measured evidence that half of a technology
        # valuation gap should disappear, which is what the old table did.
        self.sector_adjustment = 0.0
    
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
        survival_risk: bool = False,
        fair_value: Optional[float] = None,
        analyst_target: Optional[float] = None,
        analyst_count: Optional[int] = None,
        analyst_source: Optional[str] = None,
        analyst_as_of: Optional[str] = None,
        valuation_reliability: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate all fixed numbers deterministically.
        
        Returns a complete FixedNumbers payload that LLM cannot modify.
        """
        
        # A MISSING PRICE INVALIDATES THE RATING. It does not become a penny.
        #
        # This used to read `current_price = 0.01  # Avoid division by zero`,
        # which turned "we have no price" into "the stock costs one cent". Every
        # downstream figure then followed from that: a real LVMH run on the
        # Stuttgart line, where yfinance returns no price, computed the
        # valuation gap as 290.73/0.01 and shipped a confident BUY with a price
        # target — while the chat answer, which had the live price, said HOLD.
        #
        # Upside, a rating and a price target are all measured AGAINST the
        # market price. Without one there is nothing to measure against, so the
        # honest output is to say so rather than to invent the denominator.
        price_available = current_price is not None and current_price > 0
        if not price_available:
            current_price = 0.0
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
        # Average only the legs that came out POSITIVE. The truthiness test that
        # was here dropped a zero but kept a negative, so PC Jeweller's gap was
        # built on (-2.03 + 6.82) / 2 = 2.40 per share — an 81% "discount" and
        # a STRONG SELL — while the summary the reader sees averages the
        # positive legs to 12.14 (a 6% discount). A negative per-share value is
        # a method that does not fit the company, not a low estimate; the
        # Summary tab and the dispersion rail already exclude it, and the
        # rating must be built on the same number the report shows.
        _legs = [v for v in (dcf_perpetual, dcf_exit) if isinstance(v, (int, float)) and v > 0]
        dcf_avg = sum(_legs) / len(_legs) if _legs else 0
        legs_used = len(_legs)
        
        # 2. Raw valuation gap. Rate on the same headline fair value the user
        # sees. Previously the dashboard blended DCF and comps, while this
        # engine silently discarded comps and recomputed a DCF-only view.
        fair_value_available = (
            isinstance(fair_value, (int, float)) and not isinstance(fair_value, bool)
            and math.isfinite(float(fair_value)) and float(fair_value) > 0
        )
        valuation_value = float(fair_value) if fair_value_available else dcf_avg
        valuation_basis = "blended_fair_value" if fair_value_available else "dcf_average"

        # No usable leg is "no valuation signal", not a 100% discount — that
        # would rate a company STRONG SELL because both methods broke on it.
        valuation_available = fair_value_available or bool(legs_used)
        raw_val_gap_pct = (
            (valuation_value / current_price - 1) * 100
            if current_price > 0 and valuation_available else 0
        )
        
        # 3. No unmeasured sector haircut. The 40% weight below already models
        # partial 12-month convergence toward a longer-duration fair value.
        adj_val_gap_pct = raw_val_gap_pct
        
        # 4. Expected return (weighted formula)
        # 40% valuation + 40% catalysts/risks + 20% momentum
        net_catalyst_risk_pct = catalyst_score_pct - risk_score_pct
        
        expected_return_pct = (
            0.40 * adj_val_gap_pct +
            0.40 * net_catalyst_risk_pct +
            0.20 * momentum_score_pct
        )
        
        # 5. Apply volatility caps (unless survival risk)
        # The uncapped figure is kept so the report can show its own arithmetic
        # honestly: the three weighted lines sum to THIS, not to the capped
        # total, and printing the sum under a different total made the
        # methodology section visibly not add up (a shipped VOO report showed
        # -32.0 +2.6 -2.0 under a Total of -30.0).
        uncapped_expected_return_pct = expected_return_pct
        if not survival_risk:
            expected_return_pct = max(
                min(expected_return_pct, self.MAX_12M_MOVEMENT * 100),
                -self.MAX_12M_MOVEMENT * 100
            )
        
        # 6. Calculate price targets
        # Progressive targets: 3M gets 33% of ER, 6M gets 67%, 12M gets 100%
        # With no market price these are meaningless (every one would be 0), so
        # they are left at zero and flagged rather than presented as targets.
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
        
        reliability = valuation_reliability or {}
        point_estimate_withheld = bool(reliability.get("point_estimate_withheld"))

        # 9. Determine rating
        #
        # A rating is a statement about price versus value. With no market
        # price there is no such statement to make, so this returns NOT RATED
        # instead of letting the band table hand back a default that reads as
        # a considered call.
        rating_available = bool(
            price_available and valuation_available and not point_estimate_withheld
        )
        rating = self._determine_rating(expected_return_pct) if rating_available else "NOT RATED"

        analyst_target_value = (
            float(analyst_target)
            if isinstance(analyst_target, (int, float))
            and not isinstance(analyst_target, bool)
            and math.isfinite(float(analyst_target)) and float(analyst_target) > 0
            else None
        )
        analyst_gap_pct = (
            (analyst_target_value / current_price - 1) * 100
            if analyst_target_value is not None and current_price > 0 else None
        )
        
        # Human consensus is not intrinsic value, but a well-covered opposite
        # view is evidence that our model may be missing an assumption. Keep
        # the arithmetic untouched and reduce only the conviction of an
        # extreme call. The rule is symmetric for bullish and bearish models.
        consensus_alignment = "unavailable"
        rating_confidence = "moderate" if rating_available else None
        count = int(analyst_count or 0)
        if analyst_gap_pct is not None and count >= 5 and rating_available:
            model_direction = 1 if raw_val_gap_pct >= 8 else (-1 if raw_val_gap_pct <= -8 else 0)
            analyst_direction = 1 if analyst_gap_pct >= 8 else (-1 if analyst_gap_pct <= -8 else 0)
            if model_direction and analyst_direction and model_direction != analyst_direction:
                consensus_alignment = "conflicting"
                rating_confidence = "low"
                if rating == "STRONG BUY":
                    rating = "BUY"
                elif rating == "STRONG SELL":
                    rating = "SELL"
            elif model_direction and model_direction == analyst_direction:
                consensus_alignment = "supportive"
            else:
                consensus_alignment = "mixed"

        # A wide or single-method valuation can still support a directional
        # view, but the model evidence is weaker than a converged football
        # field. Make that visible without changing the arithmetic. An
        # unreliable field is different: there is no defensible midpoint to
        # rate, so all point targets and expected-return outputs are null.
        reliability_band = reliability.get("band")
        if rating_available and reliability_band in {"wide", "single-method"}:
            rating_confidence = "low"

        if point_estimate_withheld:
            rating_withheld_reason = (
                "Valuation methods do not converge, so no defensible point "
                "estimate exists for a directional rating or price target."
            )
        elif not valuation_available:
            rating_withheld_reason = (
                "No usable intrinsic-value method produced a positive result."
            )
        elif not price_available:
            rating_withheld_reason = "No market price was available for this listing."
        else:
            rating_withheld_reason = None

        if not rating_available and price_available:
            expected_return_output = None
            targets_output = {
                period: {"price": None, "range_low": None, "range_high": None}
                for period in ("m3", "m6", "m12")
            }
        else:
            expected_return_output = round(expected_return_pct, 2)
            targets_output = targets_with_ranges

        # 10. Build complete fixed numbers payload
        return {
            "as_of": str(date.today()),
            "ticker": ticker,
            "current_price": current_price,
            "expected_return_pct_12m": expected_return_output,
            "targets": targets_output,
            "rating": rating,
            "rating_confidence": rating_confidence,
            # Downstream must be able to distinguish "no view" from "neutral
            # view": the report narrative, the price-target table and the
            # answer all read this.
            "price_available": price_available,
            "rating_available": rating_available,
            "rating_withheld_reason": rating_withheld_reason,
            "inputs": {
                "raw_val_gap_pct": round(raw_val_gap_pct, 2),
                "dcf_legs_used": legs_used,
                "valuation_basis": valuation_basis,
                "valuation_value": round(valuation_value, 2) if valuation_available else None,
                "sector_premium_adjustment": self.sector_adjustment,
                "adj_val_gap_pct": round(adj_val_gap_pct, 2),
                "analyst_target": round(analyst_target_value, 2) if analyst_target_value else None,
                "analyst_target_gap_pct": round(analyst_gap_pct, 2) if analyst_gap_pct is not None else None,
                "analyst_count": count,
                "analyst_source": analyst_source,
                "analyst_as_of": analyst_as_of,
                "consensus_alignment": consensus_alignment,
                "valuation_reliability": reliability or None,
                "catalyst_score_pct": round(catalyst_score_pct, 2),
                "risk_score_pct": round(risk_score_pct, 2),
                "net_catalyst_risk_pct": round(net_catalyst_risk_pct, 2),
                "momentum_score_pct": round(momentum_score_pct, 2),
                "hist_vol_annual_pct": round(hist_vol_annual_pct, 2),
                "uncapped_expected_return_pct": round(uncapped_expected_return_pct, 2),
                "cap_applied": bool(
                    abs(uncapped_expected_return_pct - expected_return_pct) > 0.05
                ),
                "cap_pct": self.MAX_12M_MOVEMENT * 100,
            }
        }
    
    def _apply_cap(self, base: float, target: float, cap: float) -> float:
        """Apply movement cap to target price."""
        max_price = base * (1 + cap)
        min_price = base * (1 - cap)
        return max(min(target, max_price), min_price)
    
    def _determine_rating(self, expected_return_pct: float) -> str:
        """Determine rating based on expected return."""
        # Spell out the boundaries so exactly -8% maps to SELL just as exactly
        # +8% maps to BUY. A tuple loop cannot make both inner boundaries
        # inclusive without overlapping intervals.
        if expected_return_pct >= 20.0:
            return "STRONG BUY"
        if expected_return_pct >= 8.0:
            return "BUY"
        if expected_return_pct > -8.0:
            return "HOLD"
        if expected_return_pct > -20.0:
            return "SELL"
        return "STRONG SELL"
    
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
