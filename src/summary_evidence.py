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


MODEL_VIEW_DIRECTION_THRESHOLD = 0.15



def required_growth_sentence(required: Any) -> Optional[str]:
    """What the price requires, as revenue growth, in one or two sentences.

    ``required`` is ``external_expectations.implied_revenue_growth_for_enterprise_value``
    output. The price's requirement is set against the SAME solve at the
    model's own value, so the two numbers order exactly as the valuations do.
    When new capital earns too little over its cost for the modeled-margin
    number to be stable, the statement falls back to the company's best
    reported margin, compared with the model's revenue path.
    """
    if not isinstance(required, dict) or not required.get("available"):
        return None
    years = int(required.get("years") or 10)
    need = _number(required.get("required_growth"))
    need_bound = required.get("required_growth_beyond_bound")
    model_eq = _number(required.get("model_equivalent_growth"))
    best_need = _number(required.get("required_growth_at_best_margin"))
    best_bound = required.get("required_growth_at_best_margin_beyond_bound")
    best_margin = _number(required.get("best_operating_margin"))
    cagr = _number(required.get("model_revenue_growth"))
    source = str(required.get("revenue_source") or "")
    forecasts = (
        "analyst-based forecasts" if source.startswith("yahoo_analyst_consensus")
        else "revenue forecasts"
    )
    if need is not None or need_bound in ("above", "below"):
        if need_bound == "above":
            head = (
                "At this price, no revenue growth up to 150% a year for "
                f"{years} years reaches the valuation at the modeled margins"
            )
        elif need_bound == "below":
            head = (
                "At this price, the market is pricing revenue shrinking faster "
                f"than 20% a year for {years} years at the modeled margins"
            )
        elif need >= 0:
            head = (
                f"At this price, revenue would have to grow about {need:.0%} a "
                f"year for {years} years at the modeled margins"
            )
        else:
            head = (
                "At this price, the market is pricing revenue shrinking about "
                f"{abs(need):.0%} a year for {years} years at the modeled margins"
            )
        if model_eq is not None:
            head += (
                f"; on the same measure, the model's {forecasts} come to "
                + (f"about {model_eq:.0%} a year" if model_eq >= 0
                   else f"a decline of about {abs(model_eq):.0%} a year")
            )
        text = head + "."
        if (need is not None and model_eq is not None and need > model_eq
                and best_need is not None and best_margin is not None
                and best_need > model_eq + 0.01
                and round(best_need * 100) != round(need * 100)):
            text += (
                f" Even at the company's best reported operating margin of "
                f"{best_margin:.0%}, the price would need about {best_need:.0%} a year."
            )
        return text
    if best_margin is not None and cagr is not None:
        if best_bound == "above":
            return (
                "At this price, even at the company's best reported operating "
                f"margin of {best_margin:.0%}, no revenue growth up to 150% a year "
                f"for {years} years reaches the valuation; the model's {forecasts} "
                f"average about {cagr:.0%} a year."
            )
        if best_need is not None and best_need > cagr + 0.01:
            return (
                "At this price, even at the company's best reported operating "
                f"margin of {best_margin:.0%}, revenue would have to grow about "
                f"{best_need:.0%} a year for {years} years; the model's {forecasts} "
                f"average about {cagr:.0%} a year."
            )
    return None


_PLAIN_METHOD_NOTES = (
    ("captive-finance", "the company runs a lending arm whose loans and debt are "
     "mixed into its accounts, so the operating business and the lender must be "
     "valued separately"),
    ("memory-chip", "memory-chip prices set its margins, so the forecast years are "
     "one point of a price cycle rather than a normal year"),
    ("sum-of-the-parts", "the company needs a sum-of-the-parts valuation of its "
     "separate businesses"),
)

# Why the engine declines to value an instrument at all, keyed by the
# methodology's ``specialized_service``. The engine's own reason is written for
# an auditor ("a normalized commodity price deck, mid-cycle volumes and
# margins, reserve or resource life..."); this is the sentence a user reads.
_PLAIN_REFUSALS = {
    "commodity_cycle": (
        "its cash flows follow commodity prices, so a cash-flow model built on "
        "today's prices would be a bet on the commodity price rather than a "
        "valuation"
    ),
    "reit": (
        "it is a real-estate investment trust, which is valued on its properties "
        "and funds from operations rather than on corporate free cash flow"
    ),
    "insurance": (
        "it is an insurer, whose value sits in reserves, float and capital "
        "rather than in corporate free cash flow"
    ),
    "fund": (
        "it is a fund, which is valued on its holdings and net asset value "
        "rather than on cash flows"
    ),
    "crypto": "it is a crypto asset with no cash flows to discount",
    "unsupported_asset": "it is not a listed operating company",
    "bank_valuation_input_gap": (
        "it is a bank and the book-value and return inputs a bank valuation "
        "needs are not both available"
    ),
}


def plain_refusal_note(kind: Any, reason: Any = None) -> str:
    """Why no rating or fair value exists for this run, in one plain sentence.

    ``kind`` is the methodology's ``specialized_service``; ``reason`` is its
    auditor-facing text, used only when the kind is unknown. A run with no
    model and no refusal (a build failure) gets a sentence that says so
    rather than "published without a point headline".
    """
    plain = _PLAIN_REFUSALS.get(str(kind or "").strip().lower())
    if plain:
        return f"No rating or fair value is published: {plain}."
    if kind:
        detail = " ".join(str(reason or "").split())
        return (
            "No rating or fair value is published, because this instrument is "
            "outside the valuation method's scope"
            + (f": {detail}" if detail else ".")
        )
    return (
        "No rating or fair value is published, because no valuation model was "
        "produced in this run."
    )


# The engine's own figures, as analysis_tools.valuation_publication_boundary
# prints them for a corporate valuation: "The model is +94% from the market",
# "37-analyst target benchmark is +46%", "finnhub rates it HOLD (20 ratings)".
# Only the qualified evidence is printed, and only qualified evidence blocks.
# tests/test_market_expectations.py builds reasons with that function across
# both branches (DCF-only and model-plus-comps), so a wording change there
# fails a test rather than reaching a user.
_MODEL_GAP = re.compile(r"(?:model|estimate) is ([+-]\d+)% from the market")
_TARGET_GAP = re.compile(r"target benchmark is ([+-]\d+)%")
_RATING = re.compile(r"rates it ([a-z][a-z ]*?) \(\d+ ratings\)")
_RATING_DIRECTION = {
    "strong buy": 1, "buy": 1, "outperform": 1, "overweight": 1,
    "strong sell": -1, "sell": -1, "underperform": -1, "underweight": -1,
    "hold": 0, "neutral": 0, "market perform": 0, "equal weight": 0,
}
_NO_CURRENT_TARGET = "no provider-dated current analyst target qualified"
_UNCONFIRMED = "independent analyst evidence does not confirm the model's call"


def _street_disagreement(text: str) -> str:
    """Name what kept the Street from backing the model, only when it is sure.

    The engine withholds a rating when a qualified Street target points the
    other way, backs less than half of the model's move, or when a qualified
    analyst rating points another way; a DCF-only call also needs a current,
    dated target to back it. "The model and the Street's price targets point
    to different conclusions" misread the common case (Meta: +26% against
    the Street's +5%, both undervalued) and blamed targets when a rating or a
    missing target was the reason. Every specific sentence here is one the
    printed evidence proves; anything else gets the neutral sentence. Bank
    reasons ("The bank valuation is ...") follow different thresholds, so they
    always get the neutral sentence. The model's own figure is left to the
    model-view line beside this note, which states it at the range midpoint.
    """
    model = _MODEL_GAP.search(text)
    gap = int(model.group(1)) if model else 0
    if not gap:
        return _UNCONFIRMED
    side = "upside" if gap > 0 else "downside"
    targets = [int(value) for value in _TARGET_GAP.findall(text)]
    # A target at the price or on the other side never backs the model.
    for target in sorted(targets, key=lambda value: value * gap):
        if target * gap <= 0:
            where = (
                "sit at the market price" if target == 0
                else f"point the other way ({target:+d}%)"
            )
            return f"the Street's price targets {where}, against the model's {side}"
    # Below half the model's move blocks. The printed figures are rounded to
    # a whole percent, so only a target at least a point under the bar is
    # certain to be one the engine rejected; the tightest one is named.
    bar = max(5, abs(gap) / 2)
    short = [target for target in targets if abs(target) < bar - 1]
    if short:
        target = min(short, key=abs)
        return (
            f"the Street's price targets ({target:+d}%) back less than half "
            f"of the model's {side}"
        )
    direction = 1 if gap > 0 else -1
    for label in _RATING.findall(text):
        if _RATING_DIRECTION.get(label.strip()) not in (None, direction):
            return (
                f"the Street's analyst ratings ({label.strip().upper()}) do not "
                "point the same way as the model"
            )
    if _NO_CURRENT_TARGET in text:
        return "no current, dated analyst target backs the model's call"
    return _UNCONFIRMED


def plain_rating_note(reason: Any, method_note: Optional[str] = None) -> str:
    """Why no rating was published, in one sentence a retail reader follows.

    The engine's reasons are written for an auditor ("well-covered
    analyst-target evidence does not corroborate both the direction and
    material magnitude"). The technical reason stays in the report and after
    this sentence in chat; this is the line a user reads first. A reason can
    carry two conditions at once (Amazon: the model and the Street disagree
    AND the latest annual statements are 270 days old); the two most
    substantive are named, disagreement before data freshness.
    """
    text = " ".join(str(method_note or reason or "").split()).lower()
    if method_note:
        for marker, plain in _PLAIN_METHOD_NOTES:
            if marker in text:
                return f"No rating is published because {plain}."
        return "No rating is published because the cash-flow method does not fit this company."
    found = []
    if "corroborate" in text or "conflict" in text:
        found.append(_street_disagreement(text))
    if "span more than" in text or "disagree by more than" in text:
        found.append("the valuation methods disagree too widely for a single fair value")
    if "non-positive value" in text or "failed with" in text:
        found.append("one valuation method produced no positive value")
    if "days old" in text or "annual-only limit" in text:
        found.append("the latest annual financial statements are too old for a current valuation")
    if not found:
        return "No rating is published for this run."
    return "No rating is published because " + " and ".join(found[:2]) + "."


def unsuitable_method_note(suitability: Any) -> Optional[str]:
    """The methodology's own reason when it forbids publication, else None."""
    if not isinstance(suitability, dict) or suitability.get("publication_allowed") is not False:
        return None
    primary = str(suitability.get("primary_method") or "")
    if not primary.startswith("scenario_only_pending"):
        return None
    reason = str(suitability.get("reason") or "")
    marker = "because "
    if marker in reason:
        reason = reason.split(marker, 1)[1]
    return reason.strip() or None


def model_view_summary(
    *,
    span: Dict[str, Any],
    current_price: Any,
    street_target: Any = None,
    street_count: Any = None,
    market_implied_path: Any = None,
    currency: str = "",
    symbol: Optional[str] = None,
    required_growth: Optional[Dict[str, Any]] = None,
    method_note: Optional[str] = None,
) -> Dict[str, Any]:
    """The conclusion a withheld valuation still supports, in plain words.

    Direction and size of the supported method span against the market, the
    Street's mean target beside it, and the multiple of the modeled free-cash-
    flow path that the market price assumes. It never manufactures a rating or
    a point estimate: those stay withheld by the publication boundary. Before
    this, a withheld rating rendered as "valuation conclusion: INCONCLUSIVE",
    which read as "not available" to the user who asked.
    """
    price = _number(current_price, positive=True)
    low = _number((span or {}).get("low"), positive=True)
    high = _number((span or {}).get("high"), positive=True)
    code = str(currency or "").upper()
    if symbol is None:
        try:
            from src.currency import currency_symbol
            symbol = currency_symbol(code) if code else ""
        except Exception:
            symbol = ""

    def money(value: float) -> str:
        return f"{symbol}{value:,.2f}" + (f" {code}" if code else "")

    out: Dict[str, Any] = {
        "direction": None, "midpoint_gap": None, "street_gap": None,
        "price_implied_multiple": None, "headline": "", "evidence": "",
        "price_assumes": None,
    }
    if method_note:
        # The method itself was ruled out (captive lender, memory cycle,
        # unfinished sum of the parts): its arithmetic has no direction worth
        # stating, only the reason it cannot carry one.
        out["headline"] = (
            "the cash-flow model is shown only as a scenario for this company, "
            "so it states no direction versus the market."
        )
        out["evidence"] = f"The method was ruled out because {str(method_note).rstrip('.')}."
        return out
    if low is None or high is None:
        out["headline"] = "no supported positive valuation-method estimate is available."
        out["evidence"] = "The valuation methods did not produce a positive value."
        return out

    midpoint = (low + high) / 2.0
    parts: List[str] = []
    if price is not None:
        gap = midpoint / price - 1.0
        out["midpoint_gap"] = gap
        direction = (
            "below" if gap <= -MODEL_VIEW_DIRECTION_THRESHOLD
            else "above" if gap >= MODEL_VIEW_DIRECTION_THRESHOLD
            else "near"
        )
        out["direction"] = direction
        out["headline"] = (
            f"the modeled cash flows support a value {direction} the market "
            f"({gap:+.0%} at the midpoint)."
        )
        parts.append(f"Against a price of {money(price)}")
    else:
        out["headline"] = (
            "the modeled cash flows support a valuation range, but no market "
            "price was available to compare it with."
        )

    target = _number(street_target, positive=True)
    count = int(_number(street_count) or 0)
    if target is not None and price is not None:
        street_gap = target / price - 1.0
        out["street_gap"] = street_gap
        parts.append(
            f"the Street's mean target is {money(target)} ({street_gap:+.0%}"
            + (f", {count} analysts" if count else "")
            + ")"
        )
    out["evidence"] = (", ".join(parts) + ".") if parts else ""

    growth_text = required_growth_sentence(required_growth)
    if growth_text:
        out["price_assumes"] = growth_text
    path = _number(market_implied_path)
    if path is not None and path > -1.0:
        multiple = path + 1.0
        out["price_implied_multiple"] = multiple
        if growth_text:
            pass
        elif multiple >= 1.5:
            out["price_assumes"] = (
                f"The market price assumes about {multiple:.1f}× the modeled "
                "free-cash-flow path."
            )
        elif multiple <= 0.67:
            out["price_assumes"] = (
                f"The market price assumes only about {multiple:.2f}× the modeled "
                "free-cash-flow path."
            )
    return out


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
