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
    
    # A directional call needs a margin of safety around a noisy point
    # valuation.  These are valuation-gap bands, not a claim that a share price
    # follows a normal distribution or converges smoothly each quarter.
    RATING_BANDS = {
        "STRONG BUY": (30.0, float('inf')),
        "BUY": (15.0, 30.0),
        "HOLD": (-15.0, 15.0),
        "SELL": (-30.0, -15.0),
        "STRONG SELL": (float('-inf'), -30.0)
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
        analyst_captured_at: Optional[str] = None,
        analyst_rating: Optional[str] = None,
        analyst_rating_count: Optional[int] = None,
        valuation_reliability: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Calculate all fixed numbers deterministically.
        
        Returns a complete FixedNumbers payload that LLM cannot modify.
        """
        def _finite(value: Any, default: float = 0.0) -> float:
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ):
                return float(value)
            return default

        def _nonnegative_count(value: Any) -> int:
            if isinstance(value, bool):
                return 0
            try:
                count_value = int(value or 0)
            except (TypeError, ValueError, OverflowError):
                return 0
            return min(max(count_value, 0), 100_000)

        
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
        current_price = _finite(current_price)
        price_available = current_price > 0
        dcf_perpetual = _finite(dcf_perpetual)
        dcf_exit = _finite(dcf_exit)
        catalyst_score_pct = _finite(catalyst_score_pct)
        risk_score_pct = _finite(risk_score_pct)
        momentum_score_pct = _finite(momentum_score_pct)
        hist_vol_annual_pct = _finite(hist_vol_annual_pct, 18.0)
        if hist_vol_annual_pct < 0:
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
        _legs = [v for v in (dcf_perpetual, dcf_exit) if v > 0]
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
        
        # 3. No unmeasured sector haircut.
        adj_val_gap_pct = raw_val_gap_pct

        # News classifications and 52-week-range position are useful context,
        # but they are not calibrated percentage-return forecasts.  The former
        # implementation multiplied them by arbitrary 40%/20% weights and
        # called the sum a 12-month price target.  That produced a precise
        # number which no financial model had actually estimated.  A published
        # target now has one auditable basis: convergence to the point intrinsic
        # value already approved by the valuation publication boundary.
        net_catalyst_risk_pct = catalyst_score_pct - risk_score_pct
        expected_return_pct = raw_val_gap_pct
        target_12m = valuation_value if valuation_available else None
        
        reliability = valuation_reliability or {}
        point_estimate_withheld = bool(
            reliability.get("point_estimate_withheld")
            or reliability.get("band") in {"wide", "unreliable"}
        )

        # 4. Determine rating
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
        # view is evidence that our model may be missing an assumption.  It is
        # a publication gate, not a decorative footnote and not an ingredient
        # averaged into fair value.
        consensus_alignment = "unavailable"
        rating_confidence = "moderate" if rating_available else None
        count = _nonnegative_count(analyst_count)
        rating_count = _nonnegative_count(analyst_rating_count)
        label = str(analyst_rating or "").strip().lower().replace("-", "_").replace(" ", "_")
        rating_direction = (
            1 if label in {"strong_buy", "buy", "outperform", "overweight"}
            else -1 if label in {"strong_sell", "sell", "underperform", "underweight"}
            else 0 if label in {"hold", "neutral", "market_perform", "equal_weight"}
            else None
        )
        external_directions = []
        if analyst_gap_pct is not None and count >= 5:
            external_directions.append(
                1 if analyst_gap_pct >= 8 else -1 if analyst_gap_pct <= -8 else 0
            )
        if rating_direction is not None and rating_count >= 5:
            external_directions.append(rating_direction)
        if external_directions:
            model_direction = 1 if raw_val_gap_pct >= 15 else (-1 if raw_val_gap_pct <= -15 else 0)
            non_neutral = [direction for direction in external_directions if direction]
            conflicts = bool(
                model_direction and any(direction != model_direction for direction in external_directions)
            )
            if conflicts:
                consensus_alignment = "conflicting"
                rating_available = False
                rating = "NOT RATED"
                rating_confidence = None
            elif model_direction and non_neutral and all(
                direction == model_direction for direction in non_neutral
            ):
                consensus_alignment = "supportive"
            else:
                consensus_alignment = "mixed"

        # A single-method valuation can retain a view at low confidence when it
        # is not exceptional. A wide or unreliable football field has no
        # defensible midpoint, so all point targets and expected returns are null.
        reliability_band = reliability.get("band")
        if rating_available and reliability_band == "single-method":
            rating_confidence = "low"

        if point_estimate_withheld:
            rating_withheld_reason = reliability.get("withheld_reason")
            if not rating_withheld_reason and reliability.get("band") == "unreliable":
                rating_withheld_reason = (
                    "Valuation methods do not converge, so no defensible point "
                    "estimate exists for a directional rating or price target."
                )
            if not rating_withheld_reason:
                rating_withheld_reason = (
                    "Valuation evidence is not sufficient for a defensible point "
                    "estimate, directional rating, or price target."
                )
        elif consensus_alignment == "conflicting" and abs(raw_val_gap_pct) >= 15:
            rating_withheld_reason = (
                "The publishable intrinsic-value model and a sufficiently covered "
                "external analyst benchmark point in materially different "
                "directions. The intrinsic methods remain visible for audit, but "
                "the rating and convergence target are withheld until the "
                "assumption disagreement is reconciled."
            )
        elif not valuation_available:
            rating_withheld_reason = (
                "No usable intrinsic-value method produced a positive result."
            )
        elif not price_available:
            rating_withheld_reason = "No market price was available for this listing."
        else:
            rating_withheld_reason = None

        range_candidates = [value for value in _legs if value > 0]
        supplied_low = _finite(reliability.get("range_low"))
        supplied_high = _finite(reliability.get("range_high"))
        range_low = supplied_low if supplied_low > 0 else (
            min(range_candidates) if range_candidates else None
        )
        range_high = supplied_high if supplied_high > 0 else (
            max(range_candidates) if range_candidates else None
        )

        if not rating_available:
            expected_return_output = None
            targets_output = {
                period: {"price": None, "range_low": None, "range_high": None}
                for period in ("m3", "m6", "m12")
            }
        else:
            expected_return_output = round(expected_return_pct, 2)
            # No invented three/six-month path and no pseudo-confidence band
            # made from historical volatility.  The only range shown is the
            # range of approved valuation methods.
            targets_output = {
                "m3": {"price": None, "range_low": None, "range_high": None},
                "m6": {"price": None, "range_low": None, "range_high": None},
                "m12": {
                    "price": round(target_12m, 2),
                    "range_low": round(range_low, 2) if range_low is not None else None,
                    "range_high": round(range_high, 2) if range_high is not None else None,
                },
            }

        # 10. Build complete fixed numbers payload
        return {
            "as_of": str(date.today()),
            "ticker": ticker,
            "current_price": current_price,
            "expected_return_pct_12m": expected_return_output,
            "target_basis": "published_intrinsic_value_convergence",
            "target_assumption": (
                "The 12-month case assumes convergence to the currently published "
                "intrinsic value; it is not a statistically forecast market price."
            ),
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
                "analyst_captured_at": analyst_captured_at,
                "analyst_rating": analyst_rating,
                "analyst_rating_count": rating_count,
                "consensus_alignment": consensus_alignment,
                "valuation_reliability": reliability or None,
                "catalyst_score_pct": round(catalyst_score_pct, 2),
                "risk_score_pct": round(risk_score_pct, 2),
                "net_catalyst_risk_pct": round(net_catalyst_risk_pct, 2),
                "momentum_score_pct": round(momentum_score_pct, 2),
                "hist_vol_annual_pct": round(hist_vol_annual_pct, 2),
                "qualitative_signals_used_in_target": False,
                "uncapped_expected_return_pct": round(expected_return_pct, 2),
                "cap_applied": False,
                "cap_pct": None,
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
        if expected_return_pct >= 30.0:
            return "STRONG BUY"
        if expected_return_pct >= 15.0:
            return "BUY"
        if expected_return_pct > -15.0:
            return "HOLD"
        if expected_return_pct > -30.0:
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
