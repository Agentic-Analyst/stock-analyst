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

from src.confidence_alert import SCENARIO_STEM, no_single_value_stem, support_shape
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


# The common publication reasons, as a reader would put them. The stored
# reason stays complete for audit; the chat answer's "Detail:" used to quote
# its first sentence ("The near-term operating case is not reconciled: FY1
# model revenue is +22% versus ...").
_PLAIN_REASONS = (
    (re.compile(r"^At least one valuation method failed", re.I),
     "One of VYNN's valuation methods gave no positive value, so the other cannot carry a "
     "rating on its own."),
    (re.compile(r"^The valuation methods disagree by more than 2\.5x", re.I),
     "VYNN's valuation methods disagree by more than 2.5 times, so there is no single value to state."),
    (re.compile(r"^The valuation methods span more than 1\.8x", re.I),
     "VYNN's valuation methods are more than 1.8 times apart, too far for one value."),
    (re.compile(r"^No finite positive intrinsic-value output", re.I),
     "The model produced no positive value."),
    (re.compile(r"^The near-term operating case is not reconciled", re.I),
     "VYNN's sales forecast for the next year or two differs from the analysts' by more than "
     "15%, and that has to be explained before a value is stated."),
    (re.compile(r"^The near-term profitability case is not reconciled", re.I),
     "VYNN's profit-margin forecast differs from what the analysts' earnings estimates imply "
     "by more than 8 points, and that has to be explained before a value is stated."),
    (re.compile(r"^The DCF-only estimate is ([+-]?\d+%) from the market", re.I),
     "VYNN's only valuation method puts the shares {0} from the market price, and the analysts "
     "do not back a gap that large."),
)


def plain_publication_reason(value: Any, *, max_chars: int = 500) -> str:
    """The reason no single value is published, in plain words where it is a common one."""
    first = compact_publication_reason(value, max_chars=max_chars)
    for pattern, plain in _PLAIN_REASONS:
        match = pattern.search(first)
        if match:
            return plain.format(*match.groups())
    return first


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
    return {"low": low, "high": high, "shape": support_shape(low, high)}


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
    if required.get("kind") == "mid_cycle_peak_years":
        from src.agents.fm.memory_cycle import peak_years_sentence
        return peak_years_sentence(required)
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


# What a user reads where the engine states no single fair value. These say
# what the answer IS (the evidence, or a range) and why; none of them reads as
# a missing rating. A sound model the Street does not back never reaches these
# sentences: it is published with a confidence alert (src/confidence_alert.py).
EVIDENCE_ANSWER = "VYNN's answer here is the evidence, not a fair value"
NO_MODEL_ANSWER = (
    "No valuation model was produced in this run, so there is no fair value "
    "to state."
)


def plain_refusal_note(kind: Any, reason: Any = None) -> str:
    """Why this run answers with evidence and no fair value, in one plain sentence.

    ``kind`` is the methodology's ``specialized_service``; ``reason`` is its
    auditor-facing text, used only when the kind is unknown. A run with no
    model and no refusal (a build failure) gets a sentence that says so
    rather than "published without a point headline".
    """
    plain = _PLAIN_REFUSALS.get(str(kind or "").strip().lower())
    if plain:
        return f"{EVIDENCE_ANSWER}, because {plain}."
    if kind:
        detail = " ".join(str(reason or "").split())
        return (
            f"{EVIDENCE_ANSWER}, because this instrument is outside the "
            "valuation method's scope"
            + (f": {detail}" if detail else ".")
        )
    return NO_MODEL_ANSWER


# The same sentences for a question asked in Chinese, keyed like _PLAIN_REFUSALS.
_PLAIN_REFUSALS_ZH = {
    "commodity_cycle": "其现金流随大宗商品价格波动，基于当前价格的现金流模型更像是押注商品价格，而不是估值",
    "reit": "它是房地产投资信托（REIT），价值取决于其物业与运营资金（FFO），而非公司自由现金流",
    "insurance": "它是保险公司，价值体现在准备金、浮存金和资本上，而非公司自由现金流",
    "fund": "它是基金，价值取决于持仓与资产净值，而非现金流",
    "crypto": "它是加密资产，没有可以折现的现金流",
    "unsupported_asset": "它不是上市运营公司",
    "bank_valuation_input_gap": "它是银行，而银行估值所需的账面价值与回报率数据未能同时获得",
}


def plain_refusal_note_zh(kind: Any) -> str:
    """plain_refusal_note in Chinese: why this run answers with evidence and no fair value."""
    plain = _PLAIN_REFUSALS_ZH.get(str(kind or "").strip().lower())
    if plain:
        return f"VYNN 在此给出的是证据，而不是公允价值，因为{plain}。"
    if kind:
        return "VYNN 在此给出的是证据，而不是公允价值，因为该标的超出估值方法的适用范围。"
    return "本次运行没有生成估值模型，因此没有可给出的公允价值。"


# The model's own reasons for stating a range, in the order a reader should
# hear them: the valuation itself, then the business it is applied to, then
# its inputs. Each entry is (phrases the engine's reason contains, the plain
# cause). tests/test_market_expectations.py builds reasons with the engine's
# own functions, so a wording change there fails a test rather than leaving a
# user with the bare sentence.
_PLAIN_RANGE_CAUSES = (
    (("span more than", "disagree by more than", "do not converge",
      "contradict each other"),
     "the valuation methods disagree too widely to settle on one"),
    (("non-positive value", "failed with"),
     "one valuation method produced no positive value"),
    (("no finite positive",),
     "the model produced no positive value"),
    (("operating cash flow is non-positive", "operating cash flow is unavailable",
      "free cash flow is not yet established"),
     "the company does not yet generate the steady cash flow a cash-flow "
     "valuation needs"),
    (("positive current revenue is unavailable",),
     "the company has no revenue yet to build a forecast on"),
    (("fewer than two aligned annual",),
     "there is too little financial history to build a forecast on"),
    (("near-term operating case is not reconciled",),
     "the model's near-term revenue forecast is far from analysts' estimates "
     "and that gap is not yet explained"),
    (("near-term profitability case is not reconciled",),
     "the model's near-term profit margin is far from what analysts' estimates "
     "imply and that gap is not yet explained"),
    (("model boundary", "safety boundary"),
     "a core input of the bank model hit its safety limit"),
    (("days old", "annual-only limit"),
     "the latest annual financial statements are too old for a current valuation"),
    (("currency conversion is unavailable",),
     "the exchange rate needed to compare the value with the share price was "
     "unavailable"),
    (("market price is unavailable",),
     "the valuation or the market price was unavailable"),
    (("could not be completed", "decision is missing or incomplete"),
     "a safety check on this valuation could not be completed"),
)


def plain_rating_note(reason: Any, method_note: Optional[str] = None, *,
                      shape: str = "range") -> str:
    """Why this run's answer is a range (or one scenario estimate, or nothing)
    and not one fair value, in one sentence a retail reader follows.

    The engine's reasons are written for an auditor ("The valuation methods
    span more than 1.8x. That range is useful scenario evidence ..."). The
    technical reason stays in the report and after this sentence in chat; this
    is the line a user reads first. A reason can carry two conditions at once
    (methods that disagree AND statements 270 days old); the first two in the
    order above are named.

    Only the model's own state is ever the cause. What the Street thinks the
    shares are worth is never one: a sound model the analysts' targets and
    ratings do not back is published with a confidence alert, and when the
    model is blocked their position is context that follows the reason.

    ``shape`` is what the usable methods support (supported_valuation_span):
    a "range", a "single_estimate" when one method survived, or "unavailable"
    when none produced a positive value. The sentence never calls one
    estimate, or nothing, a range.
    """
    stem = no_single_value_stem(shape)
    text = " ".join(str(method_note or reason or "").split()).lower()
    if method_note:
        # The method itself was ruled out, so whatever it produced is a
        # scenario: the model-view line beside this note says the same.
        for marker, plain in _PLAIN_METHOD_NOTES:
            if marker in text:
                return f"{SCENARIO_STEM}, because {plain}."
        return f"{SCENARIO_STEM}, because the cash-flow method does not fit this company."
    found = [
        plain for markers, plain in _PLAIN_RANGE_CAUSES
        if any(marker in text for marker in markers)
    ]
    if not found:
        return f"{stem}."
    return f"{stem}, because " + " and ".join(found[:2]) + "."


def mid_cycle_method_note(suitability: Any) -> Optional[str]:
    """How a memory maker's published value was reached, or None."""
    if not isinstance(suitability, dict) or suitability.get("primary_method") != "dcf_mid_cycle":
        return None
    detail = suitability.get("mid_cycle") or {}
    margin = _number(detail.get("operating_margin"))
    if margin is None:
        return None
    industry = "DRAM" if detail.get("kind") == "dram" else "NAND"
    percent = round(margin * 100)
    # "an 18%", "an 8%", "an 80%", "an 11%": the number as it is spoken.
    article = "an" if str(percent).startswith("8") or percent in (11, 18) else "a"
    return (
        "VYNN values a memory maker on mid-cycle economics: the Street's two covered "
        f"years, then revenue back to its long-run trend and {article} {percent}% "
        f"operating margin, the {industry} industry's through-cycle level, so the "
        "value does not capitalize one point of the price cycle."
    )


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
    """The conclusion a range-only valuation still supports, in plain words.

    Direction and size of the supported method span against the market, the
    Street's mean target beside it, and the multiple of the modeled free-cash-
    flow path that the market price assumes. It never manufactures a rating or
    a point estimate: the publication boundary states none for this run.
    Before this, such a run rendered as "valuation conclusion: INCONCLUSIVE",
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
    # One surviving estimate has no midpoint and is not a range.
    one_estimate = support_shape(low, high) == "single_estimate"
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
            f"({gap:+.0%}" + ("" if one_estimate else " at the midpoint") + ")."
        )
        parts.append(f"Against a price of {money(price)}")
    else:
        out["headline"] = (
            "the modeled cash flows support "
            + ("one scenario estimate" if one_estimate else "a valuation range")
            + ", but no market price was available to compare it with."
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
        "model_fair_value": model_value,
        # The price comparisons below are against the cash-flow method alone.
        "model_cash_flow_value": _number(metrics.get("perpetual_price"), positive=True),
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
        # A memory maker valued mid-cycle: a market several times its cash-flow
        # path is the price paying for the peak to last, which the answer
        # states, not cash flow the model leaves out.
        "mid_cycle_value": bool(mid_cycle_method_note(metrics.get("method_suitability"))),
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
    if market_path is not None and market_path + 1 >= 3.0 and value.get("mid_cycle_value"):
        parts.append(
            f"mid-cycle scope: current market EV requires {market_path + 1:.2f}x "
            "the modeled FCF path; the model holds the Street's peak-cycle cash flow "
            "for the covered years, then mid-cycle revenue and margins, so the gap is "
            "the price paying for the peak to last longer, not cash flow left out of "
            "the model (the gap does not validate the market price)"
        )
    elif market_path is not None and market_path + 1 >= 3.0:
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


_SOURCE_NAMES = {
    "yahoo_finance": "Yahoo Finance", "yahoo": "Yahoo Finance", "finnhub": "Finnhub",
    "benzinga": "Benzinga", "fmp": "Financial Modeling Prep",
}
_HORIZON_NAMES = {
    "FY1": "this fiscal year", "FY2": "next fiscal year", "FY3": "the year after",
    "NTM1": "the next 12 months", "NTM2": "the 12 months after that",
}


def _money(amount: float, currency: str) -> str:
    """A per-share amount the way a reader writes it: $412.48, A$5.40, 1,234.00p."""
    if currency == "GBp":
        return f"{amount:,.2f}p"
    try:
        from src.currency import currency_symbol
        symbol = currency_symbol(currency) if currency else ""
    except Exception:
        symbol = f"{currency} " if currency else ""
    return f"{symbol}{amount:,.2f}"


def _source_name(source: Any) -> str:
    text = str(source or "").strip()
    return _SOURCE_NAMES.get(text.lower(), text.replace("_", " ").title()) if text else ""


def _plain_count(count: Any, unit: Any) -> str:
    number = int(_number(count) or 0)
    noun = "analyst firm" if "firm" in str(unit or "") else "analyst"
    return f"{number} {noun}{'' if number == 1 else 's'}"


def _times(ratio: float) -> str:
    return f"{ratio:.1f}" if abs(ratio) >= 10 else f"{ratio:.2f}"


def _method_basis_note(value: Dict[str, Any], currency: str) -> str:
    """Say the price comparison is against the cash-flow method alone, when that differs.

    Hansen's fair value of A$4.16 sat 17% above the price while the line said the
    price needs slightly more cash flow than the model expects: the comparison
    uses the cash-flow method alone, the fair value blends in a second method.
    """
    cash_flow = value.get("model_cash_flow_value")
    fair = value.get("model_fair_value")
    if not cash_flow or not fair or abs(cash_flow / fair - 1.0) < 0.05:
        return ""
    return (f" That is against VYNN's cash-flow method alone, which values the shares at "
            f"{_money(cash_flow, currency)}; its fair value of {_money(fair, currency)} also uses "
            "a second method.")


def render_external_benchmark_compact(value: Dict[str, Any], *, model_comparison: bool = True) -> str:
    """The analysts' view and what the price assumes, in plain words.

    Shown under the guard's fixed statement, to the user. It used to read
    like the model's own diagnostics ("whole-path reverse DCF: market
    29.27×; ... (diagnostic only)", "External analyst view: BUY from
    yahoo_finance (0 rating observations; provider date unavailable;
    provenance only)"), which a reviewer of real answers called jargon a
    retail investor cannot act on. ``render_external_benchmark`` keeps the
    exhaustive form for the answer-writing model.

    ``model_comparison=False`` keeps only what the analysts say: for a
    cash-flow model ruled out for this company, the lines that set the
    analysts or the price against it would give it a direction it lacks.
    """
    value = value if isinstance(value, dict) else {}
    currency = str(value.get("currency") or "")
    lines = []
    target = value.get("target_mean")
    if target is not None:
        move = value.get("target_return_vs_market")
        move_text = (
            f", {abs(move):.1%} {'above' if move >= 0 else 'below'} today's price"
            if move is not None else ""
        )
        latest = value.get("target_provider_as_of")
        oldest = value.get("target_oldest_observation_as_of")
        when = (f", set between {oldest} and {latest}" if oldest and latest
                else f", as of {latest}" if latest else "")
        source = _source_name(value.get("target_source"))
        lines.append(
            f"- Average price target: {_money(target, currency)} from "
            f"{_plain_count(value.get('target_analyst_count'), value.get('target_coverage_unit'))}"
            f"{move_text}{when}" + (f" ({source})." if source else ".")
        )
        low, median, high = (value.get(key) for key in ("target_low", "target_median", "target_high"))
        if low is not None and high is not None:
            lines.append(
                f"- Their targets range from {_money(low, currency)} to {_money(high, currency)}"
                + (f" (middle: {_money(median, currency)})." if median is not None else ".")
            )

    # Yahoo reports "none" when it has no consensus rating.
    if str(value.get("rating") or "").strip().lower() not in ("", "none", "n/a", "null"):
        rating = str(value["rating"]).replace("_", " ").title()
        count = int(_number(value.get("rating_analyst_count")) or 0)
        source = _source_name(value.get("rating_source"))
        detail = ", ".join(part for part in (
            f"{count} rating{'' if count == 1 else 's'}" if count else "", source) if part)
        lines.append(f"- Their consensus rating: {rating}" + (f" ({detail})." if detail else "."))

    relationship = value.get("benchmark_relationship") if model_comparison else None
    if relationship == "material_conflict":
        range_note = {
            "analyst_range_entirely_above_model_range": (
                " Even the lowest analyst target is above every value VYNN's model supports."
            ),
            "analyst_range_entirely_below_model_range": (
                " Even the highest analyst target is below every value VYNN's model supports."
            ),
            "ranges_overlap": " Their ranges overlap.",
        }.get(value.get("target_range_relationship"), "")
        lines.append("- VYNN's model and the analysts disagree sharply." + range_note)
    elif relationship == "corroborates":
        lines.append("- The analysts' targets back the direction of VYNN's model and much of its size.")

    sources = value.get("target_source_means") or {}
    if len(sources) >= 2:
        rows = [
            f"{_source_name(source)} {_money(row['mean'], currency)} "
            f"({_plain_count(row['analyst_count'], row.get('coverage_unit'))})"
            for source, row in sorted(sources.items())
        ]
        lines.append("- Average target by source: " + "; ".join(rows) + ".")

    if value.get("analyst_observation_count"):
        firms = value.get("analyst_observation_firms") or []
        firm_text = f" ({', '.join(firms)})" if firms else ""
        latest = value.get("analyst_observation_as_of")
        lines.append(
            f"- Recent analyst actions on record: {value['analyst_observation_count']}{firm_text}"
            + (f", the latest on {latest}." if latest else ".")
        )

    anchored = [
        row for row in value.get("forward") or []
        if row.get("street_revenue") is not None and row.get("model_uses_street_anchor")
    ] if model_comparison else []
    if anchored:
        horizons = [_HORIZON_NAMES.get(str(row.get("horizon")), str(row.get("horizon"))) for row in anchored]
        years = horizons[0] if len(horizons) == 1 else ", ".join(horizons[:-1]) + " and " + horizons[-1]
        lines.append(
            f"- VYNN's model already uses the analysts' sales forecasts for {years}. Where the two "
            "differ, it is over how much of those sales becomes cash, how much the company must "
            "reinvest, the return investors require, and how long growth lasts."
        )

    market_path = value.get("market_implied_fcf_path_delta") if model_comparison else None
    target_path = value.get("analyst_target_implied_fcf_path_delta")
    if market_path is not None:
        ratio = market_path + 1
        if ratio >= 1.05:
            need = f"about {_times(ratio)} times the cash flow VYNN's model expects"
        elif ratio > 0.95:
            need = f"about the cash flow VYNN's model expects ({_times(ratio)} times)"
        else:
            need = f"only {_times(ratio)} times the cash flow VYNN's model expects"
        analyst = (f"; the average analyst target needs {_times(target_path + 1)} times"
                   if target_path is not None else "")
        lines.append(f"- To justify today's price, the company needs {need}{analyst}."
                     + _method_basis_note(value, currency))
    if market_path is not None and market_path + 1 >= 3.0 and value.get("mid_cycle_value"):
        lines.append(
            "- That gap is the price betting that today's peak profits last longer than the "
            "model assumes, not cash flow the model left out. It does not make today's price right."
        )
    elif market_path is not None and market_path + 1 >= 3.0:
        lines.append(
            "- A gap that large means VYNN's model counts only the cash flow it can forecast, "
            "not everything investors are paying for. It does not make today's price right."
        )
    elif model_comparison and market_path is None and value.get("market_implied_fcf_delta") is not None:
        gap = value["market_implied_fcf_delta"]
        lines.append(
            f"- Today's price assumes long-run cash flow {abs(gap):.1%} "
            f"{'above' if gap >= 0 else 'below'} VYNN's model."
        )

    clauses = []
    if model_comparison and value.get("market_implied_wacc") is not None:
        model_wacc = value.get("model_wacc")
        clauses.append(
            f"investors accept a yearly return of {value['market_implied_wacc']:.1%}"
            + (f" (VYNN's model uses {model_wacc:.1%})" if model_wacc is not None else "")
        )
    if model_comparison and value.get("market_implied_terminal_growth") is not None:
        model_growth = value.get("model_terminal_growth")
        clauses.append(
            f"cash flow grows {value['market_implied_terminal_growth']:.1%} a year forever"
            + (f" (VYNN's model uses {model_growth:.1%})" if model_growth is not None else "")
        )
    if clauses:
        lines.append("- Put another way, today's price works if " + ", or if ".join(clauses) + ".")

    reinvestment = (value.get("reinvestment_sensitivity") or {}) if model_comparison else {}
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
            level = "high" if abs(reported_ratio) > abs(normalized_ratio) else "low"
            lines.append(
                f"- Investment spending is unusually {level}: {abs(reported_ratio):.1%} of sales, "
                f"against {abs(normalized_ratio):.1%} over the last three years. At the usual level, "
                f"the model's cash-flow value would be {_money(normalized_value, currency)} instead of "
                f"{_money(reported_value, currency)} (a what-if, not VYNN's estimate)."
            )

    pe = value.get("target_implied_forward_pe")
    ev_sales = value.get("target_implied_ev_to_forward_revenue")
    economics = []
    if pe is not None:
        economics.append(f"the shares would trade at {pe:.1f} times next year's expected earnings")
    if ev_sales is not None:
        economics.append(f"the whole company would be valued at {ev_sales:.1f} times next year's expected sales")
    if economics:
        lines.append("- At the average target, " + ", and ".join(economics) + ".")

    if not lines:
        return "Human-analyst benchmark unavailable or below usable coverage."
    return "\n".join(lines)
