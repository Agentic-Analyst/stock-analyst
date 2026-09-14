"""Small deterministic evidence pack for the supervisor's final user answer.

The report already contains a detailed model-versus-Street table. The chat
answer previously received only a DCF midpoint and news sentiment, so an LLM
could reduce human-analyst evidence to a caveat or omit it entirely. These
helpers pass the same point-in-time benchmark into the answer prompt without
turning a consensus target into intrinsic value.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional

from src.external_expectations import (
    align_forward_estimates_to_forecast_basis,
    build_external_expectations,
)


def compact_publication_reason(value: Any, *, max_chars: int = 500) -> str:
    """Return the decision headline without repeating its evidence appendix.

    Publication metadata intentionally carries a complete, auditable reason
    including provider benchmarks and reverse-DCF diagnostics. Chat and
    several report sections already render those details in structured form;
    repeating the full metadata paragraph ahead of them makes the product read
    like a debug dump. Keep the first deterministic sentence as the headline
    while leaving the stored reason untouched for the canonical status block.
    """
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    if len(first) <= max_chars:
        return first
    shortened = first[: max(1, max_chars - 1)].rsplit(" ", 1)[0].rstrip(" ,;:")
    return shortened + "…"


def _number(value: Any, *, positive: bool = False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _analyst_observation_metadata(value: Any) -> List[Dict[str, Any]]:
    """Fail-closed, prompt-safe metadata for licensed analyst records.

    The collection layer never reads or stores licensed rationale prose. The
    answer layer receives only dated firm/action/rating/target observations and
    must not infer research themes from those fields.
    """
    envelope = value if isinstance(value, dict) else {}
    if str(envelope.get("source") or "").strip().lower() != "benzinga":
        return []
    rows: List[Dict[str, Any]] = []
    for raw in (envelope.get("observations") or [])[:12]:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("source") or "").strip().lower() != "benzinga":
            continue
        if raw.get("content_role") != "structured_external_analyst_observation":
            continue
        temporal = raw.get("temporal_quality") or {}
        if temporal and temporal.get("status") != "current":
            continue
        rating = str(raw.get("rating") or "").strip()[:60] or None
        target = _number(raw.get("price_target"), positive=True)
        if rating is None and target is None:
            continue
        rows.append({
            "date": str(raw.get("date") or "").strip()[:32] or None,
            "firm": str(raw.get("firm") or "").strip()[:120] or None,
            "action": str(raw.get("action") or "").strip()[:60] or None,
            "rating": rating,
            "price_target": target,
            "source": "benzinga",
            "licensed_prose_collected": False,
        })
    return rows


def _coverage_text(count: Any, unit: Any, *, kind: str = "target") -> str:
    """Describe heterogeneous provider coverage without overstating identity.

    Yahoo reports analyst opinions, Finnhub reports analysts, while our dated
    Benzinga reconstruction counts latest analyst-firm observations.  Calling
    every one of these simply "analysts" implied precision the providers do
    not all expose.
    """
    number = int(_number(count) or 0)
    labels = {
        "latest_analyst_firm_target_observations": (
            "latest analyst-firm target observations"
        ),
        "latest_analyst_firm_rating_observations": (
            "latest analyst-firm rating observations"
        ),
        "provider_unique_analysts": "provider-reported unique analysts",
        "provider_reported_analyst_opinions": "provider-reported analyst opinions",
        "provider_reported_analysts": "provider-reported analysts",
        "provider_rating_observations": "provider rating observations",
    }
    fallback = "target observations" if kind == "target" else "rating observations"
    return f"{number} {labels.get(str(unit or ''), fallback)}"


def supported_valuation_values(metrics: Dict[str, Any]) -> List[float]:
    """Only method values that are eligible for the displayed support range."""
    metrics = metrics if isinstance(metrics, dict) else {}
    if metrics.get("valuation_method") == "justified_pb_roe":
        def first_positive(*values: Any):
            return next((number for value in values
                         if (number := _number(value, positive=True)) is not None), None)
        raw = (
            first_positive(
                metrics.get("bank_intrinsic_fair_value"),
                metrics.get("intrinsic_fair_value"),
            ),
            first_positive(
                metrics.get("bank_peer_fair_value"),
                metrics.get("peer_fair_value"),
            ),
        )
    else:
        raw = [metrics.get("perpetual_price"), metrics.get("exit_multiple_price")]
        if metrics.get("comps_included_in_blended_value") is True:
            raw.append(metrics.get("comps_price"))
    return [number for value in raw
            if (number := _number(value, positive=True)) is not None]


def supported_valuation_span(values: Iterable[Any]) -> Dict[str, Any]:
    """Describe method support without calling one displayed number a range."""
    supported = [number for value in values
                 if (number := _number(value, positive=True)) is not None]
    if not supported:
        return {"low": None, "high": None, "shape": "unavailable"}
    low, high = min(supported), max(supported)
    # Product surfaces display cents. Two methods that round to the same
    # number support one visible scenario estimate, not a zero-width range.
    shape = "single_estimate" if round(low, 2) == round(high, 2) else "range"
    return {"low": low, "high": high, "shape": shape}


def external_benchmark(financial_data: Dict[str, Any],
                       model_revenue: Iterable[Any] = (),
                       *, revenue_growth_source: Any = None,
                       valuation_metrics: Optional[Dict[str, Any]] = None,
                       ) -> Dict[str, Any]:
    """Compact, point-in-time human-analyst benchmark for answer synthesis."""
    data = financial_data if isinstance(financial_data, dict) else {}
    expectations = data.get("external_expectations") or build_external_expectations(data)
    expectations = expectations if isinstance(expectations, dict) else {}
    target = expectations.get("price_target") or {}
    target_cross_check = expectations.get("valuation_cross_check") or {}
    recommendations = expectations.get("recommendations") or {}
    observations = expectations.get("analyst_observations") or {}
    analyst_observation_metadata = _analyst_observation_metadata(observations)
    evidence = recommendations.get("source_evidence") or {}
    active_source = recommendations.get("active_source")
    active_rating = recommendations.get("active_label")
    active_row = evidence.get(active_source) if isinstance(evidence, dict) else None
    active_row = active_row if isinstance(active_row, dict) else {}
    model_values = list(model_revenue or ())
    revenue_source = str(revenue_growth_source or "").strip()
    consensus_anchored = revenue_source.startswith("yahoo_analyst_consensus")
    metrics = valuation_metrics if isinstance(valuation_metrics, dict) else {}
    forecast_basis = metrics.get("forecast_basis") or {}
    reinvestment = metrics.get("reinvestment_sensitivity") or {}
    reinvestment = reinvestment if isinstance(reinvestment, dict) else {}
    target_mean = _number(target.get("mean"), positive=True)
    target_low = _number(target.get("low"), positive=True)
    target_high = _number(target.get("high"), positive=True)
    target_median = _number(target.get("median"), positive=True)
    current_price = _number(metrics.get("current_price"), positive=True)
    model_value = _number(metrics.get("fair_value"), positive=True)
    model_gap = _number(metrics.get("upside_vs_market"))
    if model_gap is None and current_price is not None and model_value is not None:
        model_gap = model_value / current_price - 1.0
    target_gap = _number(target.get("return_vs_market"))
    if target_gap is None and current_price is not None and target_mean is not None:
        target_gap = target_mean / current_price - 1.0

    # Give the final answer a deterministic interpretation of the benchmark.
    # A provider target is not intrinsic value, but a well-covered target which
    # points away from a large model call is not a decorative caveat either: it
    # is an unresolved model-versus-market conflict and must be said plainly.
    target_can_challenge = bool(target.get("qualified_for_contradiction"))
    target_can_corrob = bool(target.get("qualified_for_corroboration"))
    benchmark_relationship = None
    if (model_gap is not None and abs(model_gap) >= 0.15
            and target_gap is not None and target_can_challenge):
        aligned = model_gap * target_gap > 0
        material = abs(target_gap) >= max(0.05, abs(model_gap) * 0.50)
        benchmark_relationship = (
            "corroborates" if target_can_corrob and aligned and material
            else "material_conflict"
        )

    method_values = supported_valuation_values(metrics)
    target_range_relationship = None
    if method_values and target_low is not None and target_high is not None:
        model_low, model_high = min(method_values), max(method_values)
        if target_low > model_high:
            target_range_relationship = "analyst_range_entirely_above_model_range"
        elif target_high < model_low:
            target_range_relationship = "analyst_range_entirely_below_model_range"
        else:
            target_range_relationship = "ranges_overlap"

    source_means = {}
    for source, row in (target.get("source_evidence") or {}).items():
        if not isinstance(row, dict):
            continue
        mean = _number(row.get("mean"), positive=True)
        count = int(_number(row.get("analyst_count")) or 0)
        if mean is not None and count >= 5 and row.get("currency_comparable") is not False:
            source_means[str(source)] = {
                "mean": mean,
                "analyst_count": count,
                "coverage_unit": row.get("coverage_unit"),
                "provider_as_of": row.get("provider_as_of"),
                "temporal_status": (row.get("temporal_quality") or {}).get("status"),
            }

    forward = []
    aligned_forward = align_forward_estimates_to_forecast_basis(
        expectations, forecast_basis
    )
    for index, row in enumerate(aligned_forward[:2]):
        if not isinstance(row, dict):
            continue
        street_revenue = _number(row.get("revenue"), positive=True)
        model_value = _number(model_values[index], positive=True) if index < len(model_values) else None
        forward.append({
            "horizon": row.get("horizon") or f"FY{index + 1}",
            "period": row.get("period"),
            "street_revenue": street_revenue,
            "model_revenue": model_value,
            "model_vs_street": (
                model_value / street_revenue - 1.0
                if model_value is not None and street_revenue is not None else None
            ),
            "model_uses_street_anchor": consensus_anchored,
            # EPS can legitimately be negative.
            "street_eps": _number(row.get("eps")),
            "revenue_analyst_count": int(_number(
                row.get("revenue_analyst_count")) or 0),
            "eps_analyst_count": int(_number(row.get("eps_analyst_count")) or 0),
        })

    return {
        "currency": expectations.get("currency"),
        "coverage": expectations.get("coverage"),
        "target_mean": target_mean,
        "target_median": target_median,
        "target_low": target_low,
        "target_high": target_high,
        "target_return_vs_market": target_gap,
        "target_analyst_count": int(_number(target.get("analyst_count")) or 0),
        "target_coverage_unit": target.get("coverage_unit"),
        "target_source": target.get("source"),
        "target_provider_as_of": target.get("provider_as_of"),
        "target_oldest_observation_as_of": target.get(
            "oldest_observation_as_of"
        ),
        "target_temporal_status": (
            (target.get("temporal_quality") or {}).get("status")
        ),
        "target_qualified_for_corroboration": bool(
            target.get("qualified_for_corroboration")
        ),
        "target_qualified_for_contradiction": bool(
            target.get("qualified_for_contradiction")
        ),
        "target_source_means": source_means,
        "model_return_vs_market": model_gap,
        "benchmark_relationship": benchmark_relationship,
        "target_range_relationship": target_range_relationship,
        "target_implied_forward_pe": _number(
            target_cross_check.get("forward_pe_at_mean_target"), positive=True),
        "target_implied_ev_to_forward_revenue": _number(
            target_cross_check.get("target_implied_ev_to_forward_revenue"),
            positive=True,
        ),
        "rating": active_rating,
        "rating_source": active_source,
        "rating_analyst_count": int(_number(active_row.get("analyst_count")) or 0),
        "rating_coverage_unit": active_row.get("coverage_unit"),
        "rating_provider_as_of": active_row.get("period"),
        "rating_oldest_observation_as_of": active_row.get(
            "oldest_observation_as_of"
        ),
        "rating_temporal_status": (
            (active_row.get("temporal_quality") or {}).get("status")
        ),
        "rating_qualified": bool(active_row.get("qualified")),
        "analyst_observation_count": len(analyst_observation_metadata),
        "analyst_observation_source": (
            "benzinga" if analyst_observation_metadata else None
        ),
        "analyst_observation_as_of": (
            observations.get("as_of") if analyst_observation_metadata else None
        ),
        "analyst_observation_oldest_as_of": observations.get(
            "oldest_observation_as_of"
        ) if analyst_observation_metadata else None,
        "analyst_observation_firms": sorted({
            str(row.get("firm"))
            for row in analyst_observation_metadata
            if isinstance(row, dict) and row.get("firm")
        })[:8],
        "analyst_observation_metadata": analyst_observation_metadata,
        "forward": forward,
        "forecast_basis": forecast_basis or None,
        "revenue_growth_source": revenue_source or None,
        # A reverse DCF is the missing bridge between a low intrinsic value and
        # a much higher market/analyst benchmark.  The stored value is a delta,
        # not a ratio: 0.573 means the market requires 57.3% more terminal FCF
        # than the model while holding its explicit FCF, WACC and g fixed.
        "market_implied_terminal_fcf": _number(
            metrics.get("market_implied_terminal_fcf"), positive=True),
        "market_implied_fcf_delta": _number(
            metrics.get("market_implied_fcf_vs_model")),
        "analyst_target_implied_terminal_fcf": _number(
            metrics.get("analyst_target_implied_terminal_fcf"), positive=True),
        "analyst_target_implied_fcf_delta": _number(
            metrics.get("analyst_target_implied_fcf_vs_model")),
        "market_implied_fcf_path_delta": _number(
            metrics.get("market_implied_fcf_path_vs_model")),
        "analyst_target_implied_fcf_path_delta": _number(
            metrics.get("analyst_target_implied_fcf_path_vs_model")),
        "market_implied_wacc": _number(metrics.get("market_implied_wacc")),
        "analyst_target_implied_wacc": _number(
            metrics.get("analyst_target_implied_wacc")
        ),
        "market_implied_terminal_growth": _number(
            metrics.get("market_implied_terminal_growth")
        ),
        "analyst_target_implied_terminal_growth": _number(
            metrics.get("analyst_target_implied_terminal_growth")
        ),
        "model_wacc": _number(metrics.get("wacc")),
        "model_terminal_growth": _number(metrics.get("terminal_growth")),
        "reinvestment_sensitivity": {
            "status": reinvestment.get("status"),
            "cycle": reinvestment.get("cycle"),
            "reported_capex_to_revenue": _number(
                reinvestment.get("reported_capex_to_revenue")
            ),
            "historical_normalized_capex_to_revenue": _number(
                reinvestment.get("historical_normalized_capex_to_revenue")
            ),
            "reported_run_rate_perpetual_dcf": _number(
                reinvestment.get("reported_run_rate_perpetual_dcf"), positive=True
            ),
            "historical_normalized_perpetual_dcf": _number(
                reinvestment.get("historical_normalized_perpetual_dcf"), positive=True
            ),
            "normalized_value_change": _number(
                reinvestment.get("normalized_value_change")
            ),
            "included_in_intrinsic_value": bool(
                reinvestment.get("included_in_intrinsic_value")
            ),
        } if reinvestment else {},
        "role": (
            "target and rating are external cross-checks; covered near-term revenue "
            "may be an explicit model input; none is blended into intrinsic value"
        ),
    }


def render_external_benchmark(value: Dict[str, Any]) -> str:
    """One compact prompt line; no claims beyond the structured evidence."""
    value = value if isinstance(value, dict) else {}
    currency = str(value.get("currency") or "listing currency")
    parts = []
    target = value.get("target_mean")
    if target is not None:
        move = value.get("target_return_vs_market")
        move_text = f", {move:+.1%} vs market" if move is not None else ""
        temporal_status = value.get("target_temporal_status")
        if value.get("target_qualified_for_corroboration"):
            evidence_role = "current; may challenge or corroborate"
        elif value.get("target_qualified_for_contradiction"):
            evidence_role = "provider date unavailable; caution-only"
        else:
            evidence_role = f"{temporal_status or 'unqualified'}; provenance only"
        parts.append(
            f"human-analyst mean target {currency} {target:,.2f}{move_text} "
            f"({_coverage_text(value.get('target_analyst_count'), value.get('target_coverage_unit'))}; "
            f"{value.get('target_source') or 'source unavailable'}; provider as of "
            f"{value.get('target_provider_as_of') or 'date unavailable'}"
            + (
                f"; oldest included observation "
                f"{value['target_oldest_observation_as_of']}"
                if value.get("target_oldest_observation_as_of") else ""
            )
            + f"; {evidence_role})"
        )
        low = value.get("target_low")
        median = value.get("target_median")
        high = value.get("target_high")
        distribution = []
        if low is not None:
            distribution.append(f"low {currency} {low:,.2f}")
        if median is not None:
            distribution.append(f"median {currency} {median:,.2f}")
        if high is not None:
            distribution.append(f"high {currency} {high:,.2f}")
        if distribution:
            parts.append(
                "analyst-target distribution: " + ", ".join(distribution)
                + " (dispersion, not a confidence interval)"
            )
        relationship = value.get("benchmark_relationship")
        range_relationship = value.get("target_range_relationship")
        model_gap = value.get("model_return_vs_market")
        if relationship == "material_conflict":
            gap_text = (
                f" ({model_gap:+.1%} model midpoint versus market)"
                if model_gap is not None else ""
            )
            range_text = {
                "analyst_range_entirely_above_model_range": (
                    "; even the analyst low is above the supported model-method range"
                ),
                "analyst_range_entirely_below_model_range": (
                    "; even the analyst high is below the supported model-method range"
                ),
                "ranges_overlap": "; the analyst and model ranges overlap",
            }.get(range_relationship, "")
            parts.append(
                "benchmark conclusion: the covered external target materially "
                f"conflicts with the model's directional magnitude{gap_text}{range_text}; "
                "this is an unresolved calibration conflict, not a minor caveat"
            )
        elif relationship == "corroborates":
            parts.append(
                "benchmark conclusion: current, covered external target evidence "
                "corroborates the model direction and a material portion of its magnitude"
            )

        source_means = value.get("target_source_means") or {}
        if len(source_means) >= 2:
            rendered_sources = []
            for source, row in sorted(source_means.items()):
                date = row.get("provider_as_of") or "provider date unavailable"
                rendered_sources.append(
                    f"{source} {currency} {row['mean']:,.2f} "
                    f"({_coverage_text(row['analyst_count'], row.get('coverage_unit'))}; {date})"
                )
            parts.append(
                "provider cross-checks kept separate: " + ", ".join(rendered_sources)
            )
        implied = []
        if value.get("target_implied_forward_pe") is not None:
            implied.append(
                f"{value['target_implied_forward_pe']:.1f}x forward P/E")
        if value.get("target_implied_ev_to_forward_revenue") is not None:
            implied.append(
                f"{value['target_implied_ev_to_forward_revenue']:.1f}x "
                "EV/forward Street revenue")
        if implied:
            parts.append(
                "economics implied by that external target: " + ", ".join(implied)
                + " (benchmark only)"
            )
    if value.get("rating"):
        rating_date = value.get("rating_provider_as_of") or "provider date unavailable"
        rating_oldest = value.get("rating_oldest_observation_as_of")
        rating_window = (
            f"observations {rating_oldest} through {rating_date}"
            if rating_oldest else str(rating_date)
        )
        parts.append(
            f"human-analyst rating {str(value['rating']).replace('_', ' ')} "
            f"({_coverage_text(value.get('rating_analyst_count'), value.get('rating_coverage_unit'), kind='rating')}; "
            f"{value.get('rating_source') or 'source unavailable'}; {rating_window}; "
            f"{'qualified external benchmark' if value.get('rating_qualified') else 'provenance only'})"
        )
    if value.get("analyst_observation_count"):
        firms = value.get("analyst_observation_firms") or []
        firm_text = f" across {', '.join(firms)}" if firms else ""
        date_text = (
            f"{value.get('analyst_observation_oldest_as_of')} through "
            f"{value.get('analyst_observation_as_of')}"
            if value.get("analyst_observation_oldest_as_of")
            and value.get("analyst_observation_as_of") else
            value.get("analyst_observation_as_of") or "date unavailable"
        )
        parts.append(
            f"dated analyst-record benchmark: {value['analyst_observation_count']} "
            f"current structured observation(s){firm_text} "
            f"({value.get('analyst_observation_source') or 'source unavailable'}; "
            f"{date_text}). Licensed rationale prose was not read or collected; "
            "do not infer or claim rationale themes from metadata"
        )
        rows = value.get("analyst_observation_metadata") or []
        if rows:
            record_text = []
            for row in rows:
                fields = [
                    str(row.get("firm") or "unattributed firm"),
                    str(row.get("date") or "date unavailable"),
                ]
                if row.get("action"):
                    fields.append(f"action {row['action']}")
                if row.get("rating"):
                    fields.append(f"rating {row['rating']}")
                if row.get("price_target") is not None:
                    fields.append(
                        f"target {currency} {row['price_target']:,.2f}"
                    )
                record_text.append(" / ".join(fields))
            parts.append(
                "dated analyst record metadata (external benchmark only): "
                + "; ".join(record_text)
            )
    for row in value.get("forward") or []:
        street = row.get("street_revenue")
        if street is None:
            continue
        comparison = row.get("model_vs_street")
        if row.get("model_uses_street_anchor"):
            comparison_text = (
                f", used as a model revenue anchor (resulting model gap {comparison:+.1%})"
                if comparison is not None else ", used as a model revenue anchor"
            )
        else:
            comparison_text = (
                f", model {comparison:+.1%} vs Street" if comparison is not None else ""
            )
        eps = row.get("street_eps")
        eps_text = f", Street EPS {eps:,.2f}" if eps is not None else ""
        parts.append(
            f"{row.get('horizon')} Street revenue {currency} {street / 1e9:,.1f}B "
            f"({row.get('revenue_analyst_count') or 0} analysts{comparison_text}{eps_text})"
        )
    if (value.get("benchmark_relationship") == "material_conflict"
            and any(row.get("model_uses_street_anchor") for row in value.get("forward") or [])):
        parts.append(
            "reconciliation: near-term revenue is already anchored to covered Street "
            "estimates, so the remaining valuation conflict sits downstream in cash "
            "conversion, reinvestment, discount rate, and terminal duration/multiple; "
            "it cannot be dismissed as a simple top-line forecast disagreement"
        )
    implied_delta = value.get("market_implied_fcf_delta")
    if implied_delta is not None:
        if abs(implied_delta) < 0.0005:
            gap_text = "approximately in line with the model"
        elif implied_delta > 0:
            gap_text = f"{implied_delta:.1%} above the model"
        else:
            gap_text = f"{abs(implied_delta):.1%} below the model"
        implied_fcf = value.get("market_implied_terminal_fcf")
        amount_text = (
            f" ({currency} {implied_fcf / 1e9:,.1f}B)"
            if implied_fcf is not None else ""
        )
        parts.append(
            "reverse DCF: holding model explicit cash flows, WACC and terminal "
            f"growth fixed, current market EV requires terminal FCF {gap_text}"
            f"{amount_text} (diagnostic only; not a valuation vote)"
        )
    target_implied_delta = value.get("analyst_target_implied_fcf_delta")
    if target_implied_delta is not None:
        if abs(target_implied_delta) < 0.0005:
            gap_text = "approximately in line with the model"
        elif target_implied_delta > 0:
            gap_text = f"{target_implied_delta:.1%} above the model"
        else:
            gap_text = f"{abs(target_implied_delta):.1%} below the model"
        implied_fcf = value.get("analyst_target_implied_terminal_fcf")
        amount_text = (
            f" ({currency} {implied_fcf / 1e9:,.1f}B)"
            if implied_fcf is not None else ""
        )
        parts.append(
            "analyst-target reverse DCF: holding the same model mechanics fixed, "
            f"the external mean target requires terminal FCF {gap_text}{amount_text} "
            "(external expectation benchmark only; excluded from intrinsic value)"
        )
    path_parts = []
    for label, delta in (
        ("current market EV", value.get("market_implied_fcf_path_delta")),
        ("analyst mean-target EV", value.get("analyst_target_implied_fcf_path_delta")),
    ):
        if delta is None:
            continue
        relation = (
            "approximately in line with"
            if abs(delta) < 0.0005 else
            f"{abs(delta):.1%} above"
            if delta > 0 else
            f"{abs(delta):.1%} below"
        )
        path_parts.append(f"{label} is {relation} the model")
    if path_parts:
        parts.append(
            "whole-path reverse DCF: " + "; ".join(path_parts)
            + " when explicit and terminal FCF are scaled proportionally with "
              "WACC and terminal growth fixed (diagnostic only)"
        )
    market_path = value.get("market_implied_fcf_path_delta")
    if market_path is not None and market_path + 1 >= 3.0:
        parts.append(
            f"model-scope warning: current market EV requires {market_path + 1:.2f}x "
            "the modeled FCF path; the method outputs value only that modeled "
            "operating cash-flow path and are not a comprehensive company value "
            "until the missing expectations are explicitly reconciled (the gap "
            "does not validate the market price)"
        )
    assumption_parts = []
    for label, key in (
        ("market-implied WACC", "market_implied_wacc"),
        ("analyst-target-implied WACC", "analyst_target_implied_wacc"),
        ("market-implied terminal growth", "market_implied_terminal_growth"),
        ("analyst-target-implied terminal growth",
         "analyst_target_implied_terminal_growth"),
    ):
        if value.get(key) is not None:
            assumption_parts.append(f"{label} {value[key]:.2%}")
    if assumption_parts:
        baselines = []
        if value.get("model_wacc") is not None:
            baselines.append(f"model WACC {value['model_wacc']:.2%}")
        if value.get("model_terminal_growth") is not None:
            baselines.append(
                f"model terminal growth {value['model_terminal_growth']:.2%}"
            )
        parts.append(
            "assumption reverse DCF: " + "; ".join(assumption_parts)
            + (f" versus {', '.join(baselines)}" if baselines else "")
            + " (each solves one assumption while holding the modeled FCF path "
              "and the other terminal assumption fixed; diagnostic only)"
        )
    reinvestment = value.get("reinvestment_sensitivity") or {}
    if reinvestment.get("status") == "material":
        reported_ratio = reinvestment.get("reported_capex_to_revenue")
        normalized_ratio = reinvestment.get(
            "historical_normalized_capex_to_revenue"
        )
        reported_value = reinvestment.get("reported_run_rate_perpetual_dcf")
        normalized_value = reinvestment.get(
            "historical_normalized_perpetual_dcf"
        )
        change = reinvestment.get("normalized_value_change")
        if all(item is not None for item in (
            reported_ratio, normalized_ratio, reported_value, normalized_value, change,
        )):
            parts.append(
                "reinvestment-cycle sensitivity: reported capex is "
                f"{abs(reported_ratio):.1%} of revenue versus a three-year "
                f"historical median of {abs(normalized_ratio):.1%}; replacing only "
                "the FY1 capex starting intensity and fading to the same FY5 steady "
                f"state moves perpetual DCF from {currency} {reported_value:,.2f} "
                f"to {currency} {normalized_value:,.2f} ({change:+.1%}). This is "
                "sensitivity, not forward guidance or an independent valuation vote"
            )
    if not parts:
        return "Human-analyst benchmark unavailable or below usable coverage."
    return (
        "; ".join(parts)
        + ". Targets and ratings are external cross-checks; any identified revenue "
          "anchor is a model input. None is intrinsic value."
    )


def render_external_benchmark_compact(value: Dict[str, Any]) -> str:
    """Readable launch-surface summary for the deterministic answer guard.

    ``render_external_benchmark`` is intentionally exhaustive because it feeds
    the answer-writing model.  If that model fails the publication guard, the
    user should receive the same evidence in a short structured form rather
    than one duplicated wall of prose.
    """
    value = value if isinstance(value, dict) else {}
    currency = str(value.get("currency") or "listing currency")
    lines = []
    target = value.get("target_mean")
    if target is not None:
        move = value.get("target_return_vs_market")
        move_text = f", {move:+.1%} vs market" if move is not None else ""
        latest = value.get("target_provider_as_of") or "provider date unavailable"
        oldest = value.get("target_oldest_observation_as_of")
        date = f"observations {oldest}–{latest}" if oldest else latest
        lines.append(
            f"- Human benchmark: human-analyst mean target {currency} {target:,.2f}"
            f"{move_text} from {value.get('target_source') or 'source unavailable'} "
            f"({_coverage_text(value.get('target_analyst_count'), value.get('target_coverage_unit'))}; {date})."
        )
        distribution = []
        for label, key in (("low", "target_low"), ("median", "target_median"),
                           ("high", "target_high")):
            number = value.get(key)
            if number is not None:
                distribution.append(f"{label} {currency} {number:,.2f}")
        if distribution:
            lines.append(
                "- Target distribution: " + ", ".join(distribution)
                + " (dispersion, not a confidence interval)."
            )

    relationship = value.get("benchmark_relationship")
    if relationship == "material_conflict":
        range_note = {
            "analyst_range_entirely_above_model_range": (
                " Even the analyst low is above the supported model-method range."
            ),
            "analyst_range_entirely_below_model_range": (
                " Even the analyst high is below the supported model-method range."
            ),
            "ranges_overlap": " The analyst and model ranges overlap.",
        }.get(value.get("target_range_relationship"), "")
        lines.append(
            "- Calibration result: the covered external target materially conflicts "
            "with the model's directional magnitude; this is not a minor caveat."
            + range_note
        )
    elif relationship == "corroborates":
        lines.append(
            "- Calibration result: current, covered target evidence corroborates "
            "the model direction and a material part of its magnitude."
        )

    sources = value.get("target_source_means") or {}
    if len(sources) >= 2:
        rows = []
        for source, row in sorted(sources.items()):
            rows.append(
                f"{source} {currency} {row['mean']:,.2f} "
                f"({_coverage_text(row['analyst_count'], row.get('coverage_unit'))}; "
                f"{row.get('provider_as_of') or 'date unavailable'})"
            )
        lines.append("- Provider cross-checks (kept separate): " + "; ".join(rows) + ".")

    if value.get("rating"):
        latest = value.get("rating_provider_as_of") or "provider date unavailable"
        oldest = value.get("rating_oldest_observation_as_of")
        date = f"observations {oldest}–{latest}" if oldest else str(latest)
        status = (
            "qualified external directional benchmark"
            if value.get("rating_qualified") else "provenance only"
        )
        lines.append(
            "- External analyst view: "
            f"{str(value['rating']).replace('_', ' ').upper()} from "
            f"{value.get('rating_source') or 'source unavailable'} "
            f"({_coverage_text(value.get('rating_analyst_count'), value.get('rating_coverage_unit'), kind='rating')}; "
            f"{date}; {status}). This is the Street benchmark, not Vynn's rating."
        )

    if value.get("analyst_observation_count"):
        firms = value.get("analyst_observation_firms") or []
        firm_text = f" across {', '.join(firms)}" if firms else ""
        lines.append(
            f"- Dated analyst records: {value['analyst_observation_count']} "
            f"current structured observation(s){firm_text} from "
            f"{value.get('analyst_observation_source') or 'source unavailable'} "
            f"through {value.get('analyst_observation_as_of') or 'date unavailable'}. "
            "Only firm/date/action/rating/target metadata was collected; licensed "
            "rationale prose was not read or retained, so no rationale themes are claimed."
        )

    anchored = [
        row for row in value.get("forward") or []
        if row.get("street_revenue") is not None and row.get("model_uses_street_anchor")
    ]
    if anchored:
        years = ", ".join(
            f"{row.get('horizon')} ({row.get('revenue_analyst_count') or 0} analysts)"
            for row in anchored
        )
        lines.append(
            f"- Forecast reconciliation: model revenue is already Street-anchored for "
            f"{years}. The remaining conflict is in cash conversion, reinvestment, "
            "discount rate, and terminal duration/multiple—not a simple revenue miss."
        )

    market_path = value.get("market_implied_fcf_path_delta")
    target_path = value.get("analyst_target_implied_fcf_path_delta")
    implied = []
    if market_path is not None:
        implied.append(f"market {market_path + 1:.2f}×")
    if target_path is not None:
        implied.append(f"analyst mean target {target_path + 1:.2f}×")
    if implied:
        lines.append(
            "- whole-path reverse DCF: " + "; ".join(implied)
            + " the model FCF path at unchanged WACC and terminal growth "
              "(diagnostic only)."
        )
    if market_path is not None and market_path + 1 >= 3.0:
        lines.append(
            f"- Model-scope warning: current market EV requires {market_path + 1:.2f}× "
            "the modeled FCF path. The method outputs therefore value only the "
            "modeled operating cash-flow path—not a comprehensive company value—"
            "until the missing expectations are explicitly reconciled. This gap "
            "does not validate the market price."
        )
    elif value.get("market_implied_fcf_delta") is not None:
        gap = value["market_implied_fcf_delta"]
        relation = (
            f"{abs(gap):.1%} above" if gap >= 0 else f"{abs(gap):.1%} below"
        )
        lines.append(
            "- reverse DCF: the market-implied terminal FCF is "
            f"{relation} the model "
            "at unchanged explicit cash flows, WACC, and terminal growth."
        )

    assumptions = []
    for label, key in (
        ("market WACC", "market_implied_wacc"),
        ("analyst-target WACC", "analyst_target_implied_wacc"),
        ("market terminal growth", "market_implied_terminal_growth"),
        ("analyst-target terminal growth", "analyst_target_implied_terminal_growth"),
    ):
        if value.get(key) is not None:
            assumptions.append(f"{label} {value[key]:.2%}")
    if assumptions:
        baselines = []
        if value.get("model_wacc") is not None:
            baselines.append(f"model WACC {value['model_wacc']:.2%}")
        if value.get("model_terminal_growth") is not None:
            baselines.append(
                f"model terminal growth {value['model_terminal_growth']:.2%}"
            )
        lines.append(
            "- One-assumption reverse DCF: " + "; ".join(assumptions)
            + (f" versus {', '.join(baselines)}" if baselines else "")
            + " (solve one input at a time; diagnostic only)."
        )

    reinvestment = value.get("reinvestment_sensitivity") or {}
    if reinvestment.get("status") == "material":
        reported_ratio = reinvestment.get("reported_capex_to_revenue")
        normalized_ratio = reinvestment.get(
            "historical_normalized_capex_to_revenue"
        )
        reported_value = reinvestment.get("reported_run_rate_perpetual_dcf")
        normalized_value = reinvestment.get(
            "historical_normalized_perpetual_dcf"
        )
        change = reinvestment.get("normalized_value_change")
        if all(item is not None for item in (
            reported_ratio, normalized_ratio, reported_value, normalized_value, change,
        )):
            lines.append(
                "- Reinvestment sensitivity: reported capex is "
                f"{abs(reported_ratio):.1%} of revenue versus a three-year median "
                f"of {abs(normalized_ratio):.1%}. Normalizing only that starting "
                f"intensity moves perpetual DCF from {currency} {reported_value:,.2f} "
                f"to {currency} {normalized_value:,.2f} ({change:+.1%}); this is "
                "not guidance and receives no valuation vote."
            )

    economics = []
    if value.get("target_implied_forward_pe") is not None:
        economics.append(f"{value['target_implied_forward_pe']:.1f}× forward P/E")
    if value.get("target_implied_ev_to_forward_revenue") is not None:
        economics.append(
            f"{value['target_implied_ev_to_forward_revenue']:.1f}× EV/forward revenue"
        )
    if economics:
        lines.append("- Economics at the external mean target: " + ", ".join(economics) + ".")

    if not lines:
        return "Human-analyst benchmark unavailable or below usable coverage."
    return "\n".join(lines) + "\nExternal targets are benchmarks, not intrinsic value."
