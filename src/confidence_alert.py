"""The confidence alert on a published answer.

VYNN used to withhold its fair value and rating whenever well-covered analysts
did not back the model's conclusion, and the user read "NOT RATED". A valuation
has no certain answer, only better or worse evidence, so the engine now gives
its own answer and says plainly how far it stands from the Street: the model is
never pulled toward consensus, and consensus is never hidden.

An alert is evidence about confidence. It never enters intrinsic value, and it
exists only when the model itself is sound: a method that failed, methods that
contradict each other, stale statements or a method the company does not fit
still leave no single value to publish (see the publication boundary).

Everything here is pure and deterministic, so the chat answer, the report, the
workbook and the dashboard all state the same alert from the same numbers.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional

KIND_STREET = "street_divergence"

# How the Street stands against the model's conclusion.
OPPOSITE = "opposite"          # a qualified target points the other way
AT_MARKET = "at_market"        # a qualified target sits at the market price
SMALLER = "smaller"            # same direction, under half of the model's move
RATING = "rating"              # targets agree or are absent; ratings point away
UNCONFIRMED = "unconfirmed"    # no current, dated target was available

_RELATIONS = (OPPOSITE, AT_MARKET, SMALLER, RATING, UNCONFIRMED)
_RATING_DIRECTIONS = {
    "strong buy": 1, "buy": 1, "outperform": 1, "overweight": 1,
    "strong sell": -1, "sell": -1, "underperform": -1, "underweight": -1,
    "hold": 0, "neutral": 0, "market perform": 0, "equal weight": 0,
}


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return min(max(int(value or 0), 0), 100_000)
    except (TypeError, ValueError, OverflowError):
        return 0


def _rating_direction(label: Any) -> Optional[int]:
    text = str(label or "").strip().lower().replace("_", " ").replace("-", " ")
    return _RATING_DIRECTIONS.get(text)


def build_street_alert(
    model_gap: Any,
    *,
    targets: Iterable[Dict[str, Any]] = (),
    ratings: Iterable[Dict[str, Any]] = (),
    half_move_floor: float = 0.05,
    detail: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Describe how qualified Street evidence stands against the model.

    ``targets`` rows carry ``gap`` (target / price - 1), ``count`` and
    ``source``; ``ratings`` rows carry ``label`` and ``count``. Both are the
    rows the boundary already qualified (at least five analysts, current).
    Returns ``None`` when the model states no gap to compare.
    """
    gap = _finite(model_gap)
    if gap is None or gap == 0:
        return None
    direction = 1 if gap > 0 else -1
    bar = max(half_move_floor, abs(gap) * 0.50)

    rows: List[Dict[str, Any]] = []
    for row in targets or ():
        row_gap = _finite((row or {}).get("gap"))
        if row_gap is None:
            continue
        rows.append({
            "gap": row_gap,
            "count": _count(row.get("count")),
            "source": str(row.get("source") or "")[:50],
        })

    # The target that argues hardest against the model is the one a reader
    # needs: the one furthest on the other side, else at the price, else the
    # one backing the least of the move.
    chosen = None
    relation = UNCONFIRMED
    against = [row for row in rows if row["gap"] * direction < 0 and abs(row["gap"]) >= 0.005]
    flat = [row for row in rows if abs(row["gap"]) < 0.005]
    short = [row for row in rows if row["gap"] * direction > 0 and abs(row["gap"]) < bar]
    if against:
        chosen = max(against, key=lambda row: abs(row["gap"]))
        relation = OPPOSITE
    elif flat:
        chosen = max(flat, key=lambda row: row["count"])
        relation = AT_MARKET
    elif short:
        chosen = min(short, key=lambda row: abs(row["gap"]))
        relation = SMALLER

    rating_row = None
    for row in ratings or ():
        row_direction = _rating_direction((row or {}).get("label"))
        if row_direction is not None and row_direction != direction:
            rating_row = {
                "label": str(row.get("label") or "").replace("_", " ").strip().upper()[:40],
                "count": _count(row.get("count")),
            }
            break
    if chosen is None and rating_row is not None:
        relation = RATING

    return {
        "kind": KIND_STREET,
        "relation": relation,
        "model_gap": gap,
        "benchmark_gap": chosen["gap"] if chosen else None,
        "analyst_count": (chosen["count"] or None) if chosen else None,
        "analyst_rating": rating_row["label"] if rating_row else None,
        "analyst_rating_count": (rating_row["count"] or None) if rating_row else None,
        "detail": " ".join(str(detail or "").split())[:2000] or None,
    }


def normalize_alert(value: Any) -> Optional[Dict[str, Any]]:
    """A bounded copy of an alert that crossed a file or service boundary."""
    if not isinstance(value, dict) or value.get("kind") != KIND_STREET:
        return None
    gap = _finite(value.get("model_gap"))
    if gap is None or gap == 0:
        return None
    relation = value.get("relation")
    benchmark = _finite(value.get("benchmark_gap"))
    rating = value.get("analyst_rating")
    rating = str(rating).strip().upper()[:40] if isinstance(rating, str) and rating.strip() else None
    detail = value.get("detail")
    if relation not in _RELATIONS:
        relation = UNCONFIRMED
    # A relation names a figure. Without that figure there is no second
    # position to state, so the sentence, the label and every consumer of
    # ``relation`` say "not confirmed" rather than "analysts disagree".
    if (relation in (OPPOSITE, SMALLER) and benchmark is None) or (
            relation == RATING and not rating):
        relation = UNCONFIRMED
    return {
        "kind": KIND_STREET,
        "relation": relation,
        "model_gap": gap,
        "benchmark_gap": benchmark,
        "analyst_count": _count(value.get("analyst_count")) or None,
        "analyst_rating": rating,
        "analyst_rating_count": _count(value.get("analyst_rating_count")) or None,
        "detail": " ".join(str(detail).split())[:2000] if isinstance(detail, str) and detail.strip() else None,
    }


def reason_with_street_context(reason: Any, alert: Any) -> str:
    """A model blocker's reason, followed by what the Street says as context.

    For a run blocked after its alert was drawn up (stale statements, an
    unsuitable method, an unreconciled forecast). Nothing is published, so
    there is no alert; the analysts' position follows the reason as context,
    the same way it does when the publication boundary itself blocks. It is
    never the reason.
    """
    text = " ".join(str(reason or "").split())
    detail = (normalize_alert(alert) or {}).get("detail") or ""
    if detail and detail not in text:
        return f"{text} {detail}".strip()
    return text


def _side(gap: float) -> str:
    return "above" if gap > 0 else "below"


def _percent(gap: float) -> str:
    return f"{abs(gap):.0%}"


def _analysts(count: Optional[int]) -> str:
    return f"the mean target of {count} analysts" if count else "the analysts' mean target"


def _states_street_position(alert: Dict[str, Any]) -> bool:
    """True when a normalized alert has a second position beside VYNN's.

    normalize_alert reduces a relation whose figure is missing to
    UNCONFIRMED, so an alert that names no analyst figure never ends
    "weigh both".
    """
    return alert["relation"] != UNCONFIRMED


def alert_facts(alert: Any) -> str:
    """The two positions, stated side by side, without advice.

    "VYNN's fair value is 49% below the market price, while the mean target
    of 35 analysts is 15% above it."
    """
    alert = normalize_alert(alert)
    if not alert:
        return ""
    gap = alert["model_gap"]
    own = f"VYNN's fair value is {_percent(gap)} {_side(gap)} the market price"
    if not _states_street_position(alert):
        return f"{own}, and no current analyst target was available to check it against."
    relation = alert["relation"]
    benchmark = alert["benchmark_gap"]
    who = _analysts(alert["analyst_count"])
    if relation == OPPOSITE:
        return f"{own}, while {who} is {_percent(benchmark)} {_side(benchmark)} it."
    if relation == AT_MARKET:
        return f"{own}, while {who} sits at the market price."
    if relation == SMALLER:
        return (
            f"{own}, while {who} is {_percent(benchmark)} {_side(benchmark)} it, "
            "which backs less than half of that move."
        )
    ratings = alert["analyst_rating_count"]
    return (
        f"{own}, while analysts rate it {alert['analyst_rating']}"
        + (f" ({ratings} ratings)" if ratings else "")
        + ", which does not point the same way."
    )


def alert_body(alert: Any) -> str:
    """The two positions and what to make of them, without the lead-in."""
    facts = alert_facts(alert)
    if not facts:
        return ""
    alert = normalize_alert(alert) or {}
    closing = (
        "That is a large gap between VYNN and the Street, so treat this as "
        "VYNN's own view and weigh both."
        if _states_street_position(alert) else
        "Nothing outside the model confirms a gap this large, so treat it as "
        "VYNN's own view."
    )
    return f"{facts} {closing}"


def alert_sentence(alert: Any) -> str:
    """The whole alert as a user reads it, in English."""
    body = alert_body(alert)
    return f"Low confidence: {body}" if body else ""


def alert_sentence_zh(alert: Any) -> str:
    """The same alert for a question asked in Chinese."""
    alert = normalize_alert(alert)
    if not alert:
        return ""
    gap = alert["model_gap"]
    own = f"VYNN 的公允价值{'高于' if gap > 0 else '低于'}市场价 {_percent(gap)}"
    if not _states_street_position(alert):
        return (
            f"置信度低：{own}，且没有可供核对的最新分析师目标价。"
            "模型之外尚无证据印证如此大的差距，请将此视为 VYNN 自身的观点。"
        )
    relation = alert["relation"]
    benchmark = alert["benchmark_gap"]
    count = alert["analyst_count"]
    who = f" {count} 位分析师的平均目标价" if count else "分析师的平均目标价"
    if relation == OPPOSITE:
        other = f"而{who}{'高于' if benchmark > 0 else '低于'}市场价 {_percent(benchmark)}"
    elif relation == AT_MARKET:
        other = f"而{who}与市场价持平"
    elif relation == SMALLER:
        other = (
            f"而{who}仅{'高于' if benchmark > 0 else '低于'}市场价 {_percent(benchmark)}，"
            "不到该差距的一半"
        )
    else:
        other = f"而分析师评级为 {alert['analyst_rating']}，方向并不一致"
    return f"置信度低：{own}，{other}。两者差距较大，请将此视为 VYNN 自身的观点，并综合两方判断。"


def alert_label(alert: Any) -> str:
    """A few words for a status cell or a chip."""
    alert = normalize_alert(alert)
    if not alert:
        return ""
    return (
        "low confidence: far from analyst consensus"
        if _states_street_position(alert)
        else "low confidence: not yet confirmed by analysts"
    )


# --------------------------------------------------------------------------
# Words for a result with no single value
# --------------------------------------------------------------------------
# "NOT RATED" is the engine's machine value for "no directional rating
# exists". It stays in the contracts (the calculator's ``rating``, the
# publication metadata, stored theses). A user is never shown that label: when
# the model cannot support one number they are shown what it does support,
# and why, under the words below.
#
# What it supports has one of three shapes, and the words follow the shape so
# that nothing is called a range when it is not one:
#   range            two or more usable methods, apart at the cent
#   single_estimate  one usable method, or methods equal at the cent: the
#                    words say "scenario estimate", which is true of both
#   unavailable      no method produced a positive value

NOT_RATED = "NOT RATED"
RANGE = "range"
SINGLE_ESTIMATE = "single_estimate"
UNAVAILABLE = "unavailable"
RANGE_ONLY = "Range Only"
ESTIMATE_ONLY = "Scenario Estimate Only"
NO_FAIR_VALUE = "No Fair Value"
NO_MARKET_PRICE = "No Market Price"

# The labels of the supported figures, shared by every report section.
SUPPORTED_RANGE_LABEL = "Supported Valuation Range"
SUPPORTED_ESTIMATE_LABEL = "Supported Scenario Estimate"

_VIEW_NAMES = {RANGE: RANGE_ONLY, SINGLE_ESTIMATE: ESTIMATE_ONLY, UNAVAILABLE: NO_FAIR_VALUE}
_SINGLE_VALUE_LINES = {
    RANGE: "**Single Fair Value**: Range only",
    SINGLE_ESTIMATE: "**Single Fair Value**: Scenario estimate only",
    UNAVAILABLE: "**Single Fair Value**: None",
}
_STATEMENTS = {
    RANGE: "VYNN shows a range here rather than a single fair value, rating or price target.",
    SINGLE_ESTIMATE: (
        "VYNN shows one scenario estimate here, not a fair value, rating or "
        "price target."
    ),
    UNAVAILABLE: "VYNN states no fair value, rating or price target here.",
}
_STEMS = {
    RANGE: "VYNN's answer here is a range, not a single fair value",
    SINGLE_ESTIMATE: "VYNN's answer here is a scenario estimate, not a fair value",
    UNAVAILABLE: "VYNN has no fair value to state here",
}


def support_shape(low: Any, high: Any) -> str:
    """Whether the usable methods form a range, one visible estimate, or nothing."""
    a, b = _finite(low), _finite(high)
    if a is None or b is None or a <= 0 or b <= 0:
        return UNAVAILABLE
    # Product surfaces display cents: two methods that round to the same
    # number support one visible estimate, not a zero-width range.
    return SINGLE_ESTIMATE if round(a, 2) == round(b, 2) else RANGE


def _shape(value: Any) -> str:
    return value if value in _VIEW_NAMES else UNAVAILABLE


def view_name(shape: Any) -> str:
    """ "Range Only", "Scenario Estimate Only" or "No Fair Value". """
    return _VIEW_NAMES[_shape(shape)]


def single_fair_value_line(shape: Any) -> str:
    """The status line the services read where a report states no single value."""
    return _SINGLE_VALUE_LINES[_shape(shape)]


def no_single_value_statement(shape: Any) -> str:
    """One sentence saying what the report shows in place of a single value."""
    return _STATEMENTS[_shape(shape)]


def no_single_value_stem(shape: Any) -> str:
    """How a chat answer opens the same statement, before "because ..."."""
    return _STEMS[_shape(shape)]


# Where the methodology rules the cash-flow method out for the company (a
# captive lender, a memory cycle, an unfinished sum of the parts), its output
# is a scenario whatever its shape: it states no direction versus the market.
SCENARIO_STEM = "VYNN's answer here is a scenario, not a fair value"

# The same statements for a question asked in Chinese.
_STEMS_ZH = {
    RANGE: "VYNN 在此给出的是估值区间，而不是单一公允价值",
    SINGLE_ESTIMATE: "VYNN 在此给出的是一个情景估算值，而不是公允价值",
    UNAVAILABLE: "VYNN 在此没有可给出的公允价值",
}
SCENARIO_STEM_ZH = "VYNN 在此给出的是情景分析，而不是公允价值"


def no_single_value_stem_zh(shape: Any) -> str:
    """no_single_value_stem in Chinese."""
    return _STEMS_ZH[_shape(shape)]


def workbook_status(withheld: bool, alert: Any = None, *, one_estimate: bool = False) -> str:
    """The "Publication status" cell of the downloadable workbook."""
    if withheld:
        return "SCENARIO ESTIMATE ONLY" if one_estimate else "SCENARIO RANGE ONLY"
    label = alert_label(alert)
    return f"PUBLISHABLE ({label})" if label else "PUBLISHABLE"


_REPORT_HEADING = re.compile(
    r"^#{2,3}\s*Investment (Rating|View):\s*(.+?)\s*$", re.M
)


def report_rating_heading(rating: Any, *, priced: bool = True, shape: Any = RANGE) -> str:
    """The first line of a report's recommendation section.

    A rating keeps ``### Investment Rating: BUY`` (the line the services
    read). With no rating the report says what it shows instead of printing a
    missing rating: the range, one scenario estimate, or that no fair value
    (or no market price) exists.
    """
    text = str(rating or "").strip()
    if text and text.upper() != NOT_RATED:
        return f"### Investment Rating: {text}"
    return f"### Investment View: {view_name(shape) if priced else NO_MARKET_PRICE}"


def rating_in_report(text: Any) -> str:
    """The machine rating a saved report states.

    ``NOT RATED`` for a report that states a view without a rating, and for
    one written before this wording existed.
    """
    match = _REPORT_HEADING.search(str(text or ""))
    if not match or match.group(1) == "View":
        return NOT_RATED
    return match.group(2).strip()
