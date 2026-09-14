"""Deterministic Street-expectations benchmark for an equity valuation.

Analyst targets and ratings are not intrinsic value.  They are nevertheless a
material external benchmark: a large disagreement should be explained through
revenue, earnings, margins, or valuation multiples instead of being reduced to
one veto flag.  This module normalizes only the point-in-time inputs already in
the saved financial artifact and never calls a provider or an LLM.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


PROFITABILITY_CONFLICT_PCT_POINTS = 0.08


def _timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        if len(raw) == 7 and raw[4] == "-":
            raw += "-01"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _analyst_max_age_days() -> int:
    try:
        value = int(os.getenv("ANALYST_BENCHMARK_MAX_AGE_DAYS", "180") or 180)
    except ValueError:
        value = 180
    return min(max(value, 30), 730)


def _temporal_quality(provider_as_of: Any, captured_at: Any) -> Dict[str, Any]:
    """Classify source time without pretending capture time is provider time."""
    observed = _timestamp(provider_as_of)
    reference = _timestamp(captured_at) or datetime.now(timezone.utc)
    maximum = _analyst_max_age_days()
    if observed is None:
        return {
            "status": "unknown", "age_days": None, "max_age_days": maximum,
            "provider_as_of_available": False,
        }
    age = (reference - observed).total_seconds() / 86400.0
    if age < -2:
        status = "invalid_future"
    elif age > maximum:
        status = "stale"
    else:
        status = "current"
    return {
        "status": status,
        "age_days": round(age, 3),
        "max_age_days": maximum,
        "provider_as_of_available": True,
    }


def _number(value: Any, *, positive: bool = False) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _count(value: Any) -> int:
    number = _number(value)
    return max(0, int(number)) if number is not None else 0


def implied_terminal_fcf_for_enterprise_value(
    enterprise_value: Any,
    *,
    pv_explicit_fcf: Any,
    pv_terminal_value: Any,
    model_terminal_fcf: Any,
) -> Dict[str, Any]:
    """Reverse the DCF at an observed or external target enterprise value.

    This is a benchmark diagnostic, never a valuation input.  It preserves the
    model's explicit cash flows, discounting, and terminal-growth convention,
    then asks what terminal FCF a named enterprise value would require.  That
    makes a human-analyst target economically comparable with the model instead
    of leaving it as a decorative price number.
    """
    target_ev = _number(enterprise_value)
    explicit = _number(pv_explicit_fcf)
    terminal_pv = _number(pv_terminal_value)
    model_terminal = _number(model_terminal_fcf)
    if (
        target_ev is None or explicit is None or terminal_pv is None
        or model_terminal is None or terminal_pv <= 0 or model_terminal <= 0
    ):
        return {
            "available": False,
            "implied_terminal_fcf": None,
            "implied_fcf_vs_model": None,
        }
    implied = (target_ev - explicit) * model_terminal / terminal_pv
    if not math.isfinite(implied) or implied <= 0:
        return {
            "available": False,
            "implied_terminal_fcf": None,
            "implied_fcf_vs_model": None,
        }
    return {
        "available": True,
        "implied_terminal_fcf": implied,
        "implied_fcf_vs_model": implied / model_terminal - 1.0,
        "enterprise_value": target_ev,
        "role": "external_target_reverse_dcf_benchmark_only",
    }


def implied_fcf_path_scale_for_enterprise_value(
    enterprise_value: Any, *, model_enterprise_value: Any,
) -> Dict[str, Any]:
    """Compare an observed EV with the EV of the whole modeled FCF path.

    Because DCF is linear in cash flow when WACC and terminal growth are held
    fixed, ``target EV / model EV`` is the proportional scale required across
    both explicit and terminal cash flows.  This complements the deliberately
    harsher terminal-only reverse DCF and makes an external analyst target a
    concrete economic benchmark without feeding it into intrinsic value.
    """
    target_ev = _number(enterprise_value, positive=True)
    model_ev = _number(model_enterprise_value, positive=True)
    if target_ev is None or model_ev is None:
        return {
            "available": False,
            "scale": None,
            "implied_fcf_path_vs_model": None,
        }
    scale = target_ev / model_ev
    if not math.isfinite(scale) or scale <= 0:
        return {
            "available": False,
            "scale": None,
            "implied_fcf_path_vs_model": None,
        }
    return {
        "available": True,
        "scale": scale,
        "implied_fcf_path_vs_model": scale - 1.0,
        "enterprise_value": target_ev,
        "role": "proportional_fcf_path_reverse_dcf_benchmark_only",
    }


def implied_discount_rate_for_enterprise_value(
    enterprise_value: Any,
    *,
    explicit_fcf: Any,
    terminal_growth: Any,
    model_wacc: Any = None,
    mid_year_adjustment: Any = 0.0,
) -> Dict[str, Any]:
    """Solve the WACC which makes one FCF path equal a named enterprise value."""
    target = _number(enterprise_value, positive=True)
    growth = _number(terminal_growth)
    timing = _number(mid_year_adjustment)
    try:
        path = [float(value) for value in explicit_fcf]
    except (TypeError, ValueError):
        path = []
    if (target is None or growth is None or timing is None
            or not 0.0 <= timing <= 1.0 or not path
            or not all(math.isfinite(value) for value in path)
            or path[-1] <= 0 or growth <= -0.99 or growth >= 0.20):
        return {"available": False, "implied_wacc": None,
                "implied_wacc_vs_model": None}

    terminal_fcf = path[-1] * (1.0 + growth)

    def value_at(rate: float) -> float:
        if rate <= growth:
            return float("inf")
        explicit = sum(value / (1.0 + rate) ** (year - timing)
                       for year, value in enumerate(path, start=1))
        terminal = (
            terminal_fcf / (rate - growth)
            / (1.0 + rate) ** (len(path) - timing)
        )
        return explicit + terminal

    lower = max(growth + 1e-6, 1e-6)
    upper = 0.50
    low_value, high_value = value_at(lower), value_at(upper)
    if not (math.isfinite(high_value) and low_value >= target >= high_value):
        return {"available": False, "implied_wacc": None,
                "implied_wacc_vs_model": None}
    for _ in range(160):
        midpoint = (lower + upper) / 2.0
        if value_at(midpoint) > target:
            lower = midpoint
        else:
            upper = midpoint
    implied = (lower + upper) / 2.0
    model = _number(model_wacc)
    return {
        "available": True,
        "implied_wacc": implied,
        "implied_wacc_vs_model": implied - model if model is not None else None,
        "enterprise_value": target,
        "role": "reverse_dcf_discount_rate_benchmark_only",
    }


def implied_terminal_growth_for_enterprise_value(
    enterprise_value: Any,
    *,
    explicit_fcf: Any,
    wacc: Any,
    model_terminal_growth: Any = None,
    mid_year_adjustment: Any = 0.0,
) -> Dict[str, Any]:
    """Solve terminal growth at fixed WACC for a named enterprise value."""
    target = _number(enterprise_value, positive=True)
    rate = _number(wacc, positive=True)
    timing = _number(mid_year_adjustment)
    try:
        path = [float(value) for value in explicit_fcf]
    except (TypeError, ValueError):
        path = []
    if (target is None or rate is None or timing is None
            or not 0.0 <= timing <= 1.0 or not path or rate >= 0.50
            or not all(math.isfinite(value) for value in path) or path[-1] <= 0):
        return {"available": False, "implied_terminal_growth": None,
                "implied_terminal_growth_vs_model": None}
    explicit_pv = sum(value / (1.0 + rate) ** (year - timing)
                      for year, value in enumerate(path, start=1))
    residual = target - explicit_pv
    if not math.isfinite(residual) or residual <= 0:
        return {"available": False, "implied_terminal_growth": None,
                "implied_terminal_growth_vs_model": None}
    multiple = residual * (1.0 + rate) ** (len(path) - timing) / path[-1]
    implied = (multiple * rate - 1.0) / (multiple + 1.0)
    if (not math.isfinite(implied) or implied <= -0.99
            or implied >= rate - 1e-6):
        return {"available": False, "implied_terminal_growth": None,
                "implied_terminal_growth_vs_model": None}
    model = _number(model_terminal_growth)
    return {
        "available": True,
        "implied_terminal_growth": implied,
        "implied_terminal_growth_vs_model": (
            implied - model if model is not None else None
        ),
        "enterprise_value": target,
        "role": "reverse_dcf_terminal_growth_benchmark_only",
    }


def _direction(label: Any) -> Optional[str]:
    value = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"strong_buy", "buy", "outperform", "overweight"}:
        return "bullish"
    if value in {"hold", "neutral", "market_perform", "equal_weight"}:
        return "neutral"
    if value in {"strong_sell", "sell", "underperform", "underweight"}:
        return "bearish"
    return None


def _estimate(rows: Any, period: str, *, positive_values: bool) -> Dict[str, Any]:
    row = (rows or {}).get(period) if isinstance(rows, dict) else None
    row = row if isinstance(row, dict) else {}
    return {
        "period": period,
        # Revenue must be positive. EPS may legitimately be zero or negative
        # for pre-profit and cyclical companies; discarding it would make a
        # real Street loss estimate look like missing coverage.
        "average": _number(row.get("avg"), positive=positive_values),
        "low": _number(row.get("low"), positive=positive_values),
        "high": _number(row.get("high"), positive=positive_values),
        "growth": _number(row.get("growth")),
        "analyst_count": _count(row.get("numberOfAnalysts")),
    }


def _eps_in_model_currency(
    value: Any, *, source_currency: Any, financial_currency: Any, fx_rate: Any,
) -> Optional[float]:
    """Convert provider EPS to the model's financial currency.

    Yahoo's TSM estimates are USD per ADR while revenue and the DCF are in TWD.
    Multiplying raw USD EPS by ADR-equivalent shares and dividing by TWD revenue
    fabricated a 1.6% Street margin. The listing-to-financial FX used for price
    targets is also the correct per-share conversion here because the model's
    share count is in listing/ADR-equivalent units.
    """
    number = _number(value)
    if number is None:
        return None
    source = str(source_currency or "").strip().upper()
    financial = str(financial_currency or source).strip().upper()
    if not source:
        return None
    if not financial or source == financial:
        return number
    rate = _number(fx_rate, positive=True)
    return number * rate if rate is not None else None


def _infer_eps_source_currency(
    *, analyst: Dict[str, Any], basic: Dict[str, Any], market: Dict[str, Any],
    valuation: Dict[str, Any], forward_eps: Any,
) -> Dict[str, Any]:
    """Resolve Yahoo's undocumented ADR EPS units and fail closed if ambiguous.

    Yahoo uses listing-currency EPS for some ADRs (TSM) and reporting-currency
    EPS for others (BABA), despite returning both through the same endpoint.
    The provider's own forward P/E gives us a dimensional checksum: only one
    candidate should reproduce it from the saved quote. This is an inference,
    so it must be both close to the provider ratio and clearly better than the
    alternative. An explicit normalized currency supplied by a future licensed
    feed takes precedence.
    """
    listing = str(basic.get("listing_currency") or basic.get("currency") or "").upper()
    financial = str(basic.get("currency") or listing).upper()
    explicit = str(analyst.get("earnings_estimates_currency") or "").upper()
    if explicit in {listing, financial}:
        return {
            "currency": explicit,
            "basis": "provider_explicit_currency",
            "confidence": "high",
        }
    if not listing or not financial:
        return {"currency": None, "basis": "missing_security_currency", "confidence": "none"}
    if listing == financial:
        return {
            "currency": financial,
            "basis": "same_listing_and_reporting_currency",
            "confidence": "high",
        }

    eps = _number(forward_eps, positive=True)
    fx_rate = _number(market.get("fx_listing_to_financial"), positive=True)
    provider_pe = _number(valuation.get("pe_ratio_forward"), positive=True)
    listing_price = _number(market.get("current_price_listing"), positive=True)
    financial_price = _number(market.get("current_price"), positive=True)
    if listing_price is None and financial_price is not None and fx_rate is not None:
        listing_price = financial_price / fx_rate
    if financial_price is None and listing_price is not None and fx_rate is not None:
        financial_price = listing_price * fx_rate
    if None in (eps, fx_rate, provider_pe, listing_price, financial_price):
        return {
            "currency": None,
            "basis": "insufficient_forward_pe_unit_evidence",
            "confidence": "none",
        }

    candidates = {
        listing: listing_price / eps,
        financial: financial_price / eps,
    }
    errors = {
        currency: abs(math.log(candidate_pe / provider_pe))
        for currency, candidate_pe in candidates.items()
        if candidate_pe > 0
    }
    ranked = sorted(errors.items(), key=lambda item: item[1])
    if len(ranked) != 2:
        return {"currency": None, "basis": "invalid_forward_pe_unit_evidence",
                "confidence": "none"}
    (winner, best_error), (_, other_error) = ranked
    # Within 20% of the provider ratio, and at least 50% closer in multiplicative
    # distance than the competing unit. This avoids a silent guess when FX is
    # near one or the provider's P/E and estimate horizons do not line up.
    if best_error <= math.log(1.20) and other_error - best_error >= math.log(1.50):
        return {
            "currency": winner,
            "basis": "provider_forward_pe_dimensional_match",
            "confidence": "high",
            "provider_forward_pe": provider_pe,
            "listing_currency_candidate_pe": candidates[listing],
            "reporting_currency_candidate_pe": candidates[financial],
        }
    return {
        "currency": None,
        "basis": "ambiguous_forward_pe_unit_evidence",
        "confidence": "none",
        "provider_forward_pe": provider_pe,
        "listing_currency_candidate_pe": candidates[listing],
        "reporting_currency_candidate_pe": candidates[financial],
    }


def build_external_expectations(financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build an auditable Street case from the artifact's normalized inputs."""
    data = financial_data if isinstance(financial_data, dict) else {}
    company = data.get("company_data") if isinstance(data.get("company_data"), dict) else {}
    market = company.get("market_data") if isinstance(company.get("market_data"), dict) else {}
    capital = (
        company.get("capital_structure")
        if isinstance(company.get("capital_structure"), dict) else {}
    )
    basic = company.get("basic_info") if isinstance(company.get("basic_info"), dict) else {}
    valuation = (
        company.get("valuation_metrics")
        if isinstance(company.get("valuation_metrics"), dict) else {}
    )
    analyst = data.get("analyst_data") if isinstance(data.get("analyst_data"), dict) else {}
    consensus = (
        company.get("analyst_consensus") or analyst.get("consensus") or {}
    )
    consensus = consensus if isinstance(consensus, dict) else {}

    price = _number(market.get("current_price"), positive=True)
    shares = next((value for raw in (
        # Use the same all-class/listing-unit count as the valuation bridge.
        # Yahoo's basic count can represent only one Alphabet class; multiplying
        # Street EPS by it understated implied net income by roughly half.
        market.get("shares_outstanding_implied"),
        market.get("shares_outstanding_diluted"),
        market.get("shares_outstanding_basic"),
        market.get("shares_outstanding"),
    ) if (value := _number(raw, positive=True)) is not None), None)
    target = consensus.get("price_target") if isinstance(consensus.get("price_target"), dict) else {}
    recommendation = (
        consensus.get("recommendation")
        if isinstance(consensus.get("recommendation"), dict) else {}
    )
    target_mean = _number(target.get("mean"), positive=True)
    target_count = _count(target.get("analyst_count"))

    target_sources: Dict[str, Dict[str, Any]] = {}
    snapshots = consensus.get("source_snapshots") or {}
    # The security's listing/reporting currency is the comparison authority.
    # Never let a provider target's own currency declare itself comparable: a
    # malformed EUR target for a USD listing would otherwise pass this check.
    expected_currency = str(basic.get("currency") or target.get("currency") or "").upper()
    if isinstance(snapshots, dict):
        for source, snapshot in snapshots.items():
            row = snapshot.get("price_target") if isinstance(snapshot, dict) else {}
            row = row if isinstance(row, dict) else {}
            mean = _number(row.get("mean"), positive=True)
            count = _count(row.get("analyst_count"))
            currency = str(row.get("currency") or "").upper()
            if mean is None:
                continue
            currency_comparable = bool(
                expected_currency and currency and currency == expected_currency
            )
            temporal = _temporal_quality(
                row.get("as_of"),
                (snapshot or {}).get("captured_at") or consensus.get("captured_at"),
            )
            covered = count >= 5 and currency_comparable
            target_sources[str(source)] = {
                "mean": mean,
                "analyst_count": count,
                "coverage_unit": row.get("coverage_unit"),
                "currency": currency or None,
                "provider_as_of": row.get("as_of"),
                "oldest_observation_as_of": row.get("oldest_observation_as_of"),
                "source_endpoint": row.get("source_endpoint"),
                "return_vs_market": mean / price - 1 if price is not None else None,
                # Unknown provider dates may still challenge a directional
                # claim, but cannot positively validate an exceptional point
                # target. Stale/future-dated evidence does neither.
                "qualified": covered and temporal["status"] in {"current", "unknown"},
                "qualified_for_contradiction": (
                    covered and temporal["status"] in {"current", "unknown"}
                ),
                "qualified_for_corroboration": (
                    covered and temporal["status"] == "current"
                ),
                "currency_comparable": currency_comparable,
                "temporal_quality": temporal,
            }
    if not target_sources and target_mean is not None:
        source = str(target.get("source") or "unknown")
        currency = str(target.get("currency") or "").upper()
        currency_comparable = bool(
            expected_currency and currency and currency == expected_currency
        )
        temporal = _temporal_quality(target.get("as_of"), consensus.get("captured_at"))
        covered = target_count >= 5 and currency_comparable
        target_sources[source] = {
            "mean": target_mean,
            "analyst_count": target_count,
            "coverage_unit": target.get("coverage_unit"),
            "currency": currency or None,
            "provider_as_of": target.get("as_of"),
            "return_vs_market": target_mean / price - 1 if price is not None else None,
            "qualified": covered and temporal["status"] in {"current", "unknown"},
            "qualified_for_contradiction": (
                covered and temporal["status"] in {"current", "unknown"}
            ),
            "qualified_for_corroboration": (
                covered and temporal["status"] == "current"
            ),
            "currency_comparable": currency_comparable,
            "temporal_quality": temporal,
        }

    revenue_rows = analyst.get("revenue_estimates") or {}
    eps_rows = analyst.get("earnings_estimates") or {}
    revenue = [
        _estimate(revenue_rows, period, positive_values=True)
        for period in ("0y", "+1y")
    ]
    raw_eps = [
        _estimate(eps_rows, period, positive_values=False)
        for period in ("0y", "+1y")
    ]
    listing_currency = basic.get("listing_currency") or basic.get("currency")
    financial_currency = basic.get("currency") or listing_currency
    fx_rate = market.get("fx_listing_to_financial")
    eps_unit = _infer_eps_source_currency(
        analyst=analyst,
        basic=basic,
        market=market,
        valuation=valuation,
        forward_eps=raw_eps[1].get("average"),
    )
    eps_source_currency = eps_unit.get("currency")
    eps = []
    for row in raw_eps:
        normalized = dict(row)
        for field in ("average", "low", "high"):
            normalized[field] = _eps_in_model_currency(
                row.get(field), source_currency=eps_source_currency,
                financial_currency=financial_currency, fx_rate=fx_rate,
            )
        normalized["source_currency"] = eps_source_currency
        normalized["currency"] = (
            financial_currency if normalized.get("average") is not None else None
        )
        normalized["currency_conversion_rate"] = (
            fx_rate if str(eps_source_currency or "").upper()
            != str(financial_currency or "").upper() else 1.0
        )
        eps.append(normalized)
    years = []
    for index, period in enumerate(("0y", "+1y")):
        revenue_row, eps_row = revenue[index], eps[index]
        implied_net_income = (
            eps_row["average"] * shares
            if eps_row["average"] is not None and shares is not None else None
        )
        implied_net_margin = (
            implied_net_income / revenue_row["average"]
            if implied_net_income is not None and revenue_row["average"] else None
        )
        years.append({
            "period": period,
            "revenue": revenue_row["average"],
            "revenue_growth": revenue_row["growth"],
            "revenue_analyst_count": revenue_row["analyst_count"],
            "eps": eps_row["average"],
            "eps_source_value": raw_eps[index]["average"],
            "eps_source_currency": eps_row.get("source_currency"),
            "eps_currency": eps_row.get("currency"),
            "eps_currency_conversion_rate": eps_row.get(
                "currency_conversion_rate"
            ),
            "eps_unit_basis": eps_unit.get("basis"),
            "eps_unit_confidence": eps_unit.get("confidence"),
            "eps_growth": eps_row["growth"],
            "eps_analyst_count": eps_row["analyst_count"],
            "implied_net_income": implied_net_income,
            "implied_net_margin": implied_net_margin,
        })

    rating_sources = {}
    if isinstance(snapshots, dict):
        for source, snapshot in snapshots.items():
            row = snapshot.get("recommendation") if isinstance(snapshot, dict) else {}
            row = row if isinstance(row, dict) else {}
            if row.get("label"):
                # Yahoo's numberOfAnalystOpinions describes price-target
                # coverage, not the opaque recommendationKey population. Some
                # legacy artifacts copied that count into ``total``. Never let
                # those cached rows regain a fabricated rating vote.
                source_count = 0 if str(source) == "yahoo_finance" else max(
                    _count(row.get("total")),
                    _count(row.get("unique_analyst_count")),
                    _count(row.get("analyst_count")),
                )
                temporal = _temporal_quality(
                    row.get("period"),
                    (snapshot or {}).get("captured_at") or consensus.get("captured_at"),
                )
                rating_sources[str(source)] = {
                    "label": row.get("label"),
                    "direction": _direction(row.get("label")),
                    "analyst_count": source_count,
                    "coverage_unit": row.get("coverage_unit"),
                    "qualified": source_count >= 5 and temporal["status"] in {
                        "current", "unknown"
                    },
                    "period": row.get("period"),
                    "oldest_observation_as_of": row.get(
                        "oldest_observation_as_of"
                    ),
                    "source_endpoint": row.get("source_endpoint"),
                    "temporal_quality": temporal,
                }
    if not rating_sources and recommendation.get("label"):
        source = str(recommendation.get("source") or "unknown")
        # Legacy Yahoo artifacts did not carry source_snapshots and copied
        # numberOfAnalystOpinions (the population behind the price-target
        # fields) onto recommendation.  That does *not* tell us how many
        # analysts contributed to Yahoo's opaque recommendationKey.  Apply the
        # same fail-closed rule used by the snapshot path so old cached runs
        # cannot regain a fabricated "39 ratings" vote merely because they
        # predate the normalized provider envelope.
        source_count = 0 if source == "yahoo_finance" else max(
            _count(recommendation.get("total")),
            _count(recommendation.get("unique_analyst_count")),
            _count(recommendation.get("analyst_count")),
        )
        temporal = _temporal_quality(
            recommendation.get("period"), consensus.get("captured_at")
        )
        rating_sources[source] = {
            "label": recommendation.get("label"),
            "direction": _direction(recommendation.get("label")),
            "analyst_count": source_count,
            "coverage_unit": recommendation.get("coverage_unit"),
            "qualified": source_count >= 5 and temporal["status"] in {
                "current", "unknown"
            },
            "period": recommendation.get("period"),
            "temporal_quality": temporal,
        }

    qualified_ratings = [row for row in rating_sources.values() if row["qualified"]]
    directions = {row["direction"] for row in qualified_ratings if row["direction"]}
    # Coverage describes evidence that can actually participate in policy.
    # A stale/future-dated 50-rating snapshot must not turn coverage "high".
    rating_coverage = max(
        (row["analyst_count"] for row in qualified_ratings), default=0
    )
    revenue_coverage = max((row["revenue_analyst_count"] for row in years), default=0)
    eps_coverage = max((row["eps_analyst_count"] for row in years), default=0)
    raw_observations = consensus.get("analyst_observations") or {}
    raw_observations = (
        raw_observations if isinstance(raw_observations, dict) else {}
    )
    analyst_observations = []
    excluded_observation_count = 0
    for raw in (raw_observations.get("observations") or [])[:25]:
        if not isinstance(raw, dict):
            continue
        source = str(
            raw.get("source") or raw_observations.get("source") or ""
        ).strip()
        temporal = _temporal_quality(raw.get("date"), consensus.get("captured_at"))
        rating = str(raw.get("rating") or "").strip()[:60] or None
        target_value = _number(raw.get("price_target"), positive=True)
        if (source != "benzinga" or temporal.get("status") != "current"
                or (rating is None and target_value is None)):
            excluded_observation_count += 1
            continue
        analyst_observations.append({
            "date": raw.get("date"),
            "firm": str(raw.get("firm") or "").strip()[:120] or None,
            "action": str(raw.get("action") or "").strip()[:60] or None,
            "rating": rating,
            "price_target": target_value,
            "source": "benzinga",
            "source_endpoint": "analyst_insights",
            "temporal_quality": temporal,
            "content_role": "structured_external_analyst_observation",
        })
    analyst_observations.sort(
        key=lambda row: str(row.get("date") or ""), reverse=True
    )
    warnings = []
    if target_mean is not None and not target.get("as_of"):
        warnings.append("Price-target source date unavailable; capture time is not a provider as-of date.")
    if target_mean is not None and target_count < 5:
        warnings.append("Price-target coverage is below five analysts.")
    stale_targets = [source for source, row in target_sources.items()
                     if (row.get("temporal_quality") or {}).get("status")
                     in {"stale", "invalid_future"}]
    if stale_targets:
        warnings.append(
            "Stale or invalid-dated price-target evidence excluded: "
            + ", ".join(sorted(stale_targets)) + "."
        )
    if target_sources and not any(
        row.get("qualified_for_corroboration") for row in target_sources.values()
    ):
        warnings.append(
            "No provider-dated current price target is available to corroborate "
            "an exceptional intrinsic-value claim."
        )
    if len(directions) > 1:
        warnings.append("Recommendation providers disagree on direction.")
    excluded_ratings = [
        source for source, row in rating_sources.items()
        if (row.get("temporal_quality") or {}).get("status")
        in {"stale", "invalid_future"}
    ]
    if excluded_ratings:
        warnings.append(
            "Stale or invalid-dated recommendation evidence excluded: "
            + ", ".join(sorted(excluded_ratings)) + "."
        )
    if rating_sources and not qualified_ratings:
        raw_rating_coverage = max(
            (row["analyst_count"] for row in rating_sources.values()), default=0
        )
        warnings.append(
            "Recommendation coverage is below five analysts."
            if raw_rating_coverage < 5 else
            "No current recommendation evidence with adequate coverage is available."
        )
    if not any(row["revenue"] is not None for row in years):
        warnings.append("Forward revenue estimates are unavailable.")
    if not any(row["eps"] is not None for row in years):
        warnings.append("Forward EPS estimates are unavailable.")
    if (
        str(listing_currency or "").upper() != str(financial_currency or "").upper()
        and eps_source_currency is None
        and any(row["average"] is not None for row in raw_eps)
    ):
        warnings.append(
            "Forward EPS estimates were excluded because the provider's ADR EPS "
            "currency/unit could not be resolved safely."
        )
    if raw_observations and not analyst_observations:
        warnings.append(
            "Structured analyst observations were present but none had current, "
            "source-labelled rating or target metadata suitable for benchmarking."
        )

    evidence_components = sum((
        any(row.get("qualified_for_contradiction") for row in target_sources.values()),
        rating_coverage >= 5,
        revenue_coverage >= 5,
        eps_coverage >= 5,
    ))
    coverage = "high" if evidence_components == 4 else (
        "moderate" if evidence_components >= 2 else "limited"
    )
    forward_eps = years[1]["eps"]
    forward_revenue = years[1]["revenue"]
    target_market_cap = (
        target_mean * shares
        if target_mean is not None and shares is not None else None
    )
    current_enterprise_value = next((value for raw in (
        market.get("enterprise_value_financial"),
        market.get("enterprise_value"),
    ) if (value := _number(raw, positive=True)) is not None), None)
    target_enterprise_value = (
        current_enterprise_value + (target_mean - price) * shares
        if current_enterprise_value is not None and target_mean is not None
        and price is not None and shares is not None else None
    )
    if target_enterprise_value is None and target_market_cap is not None:
        debt = _number(capital.get("total_debt")) or 0.0
        cash = _number(capital.get("total_cash")) or 0.0
        target_enterprise_value = target_market_cap + debt - cash
    active_target_evidence = target_sources.get(str(target.get("source") or ""), {})
    active_rating_evidence = rating_sources.get(
        str(recommendation.get("source") or ""), {}
    )
    return {
        "captured_at": consensus.get("captured_at") or analyst.get("captured_at"),
        "currency": basic.get("currency") or target.get("currency"),
        "market_price_at_run": price,
        "price_target": {
            "mean": target_mean,
            "median": _number(target.get("median"), positive=True),
            "low": _number(target.get("low"), positive=True),
            "high": _number(target.get("high"), positive=True),
            "analyst_count": target_count,
            "coverage_unit": target.get("coverage_unit"),
            "source": target.get("source"),
            "provider_as_of": target.get("as_of"),
            "oldest_observation_as_of": target.get("oldest_observation_as_of"),
            "source_endpoint": target.get("source_endpoint"),
            "return_vs_market": target_mean / price - 1
            if target_mean is not None and price is not None else None,
            "source_evidence": target_sources,
            "qualified_for_corroboration": bool(
                active_target_evidence.get("qualified_for_corroboration")
            ),
            "qualified_for_contradiction": bool(
                active_target_evidence.get("qualified_for_contradiction")
            ),
            "temporal_quality": active_target_evidence.get("temporal_quality"),
        },
        "recommendations": {
            "active_label": recommendation.get("label"),
            "active_source": recommendation.get("source"),
            "direction": _direction(recommendation.get("label")),
            "source_evidence": rating_sources,
            "directional_agreement": len(directions) == 1
            if len(qualified_ratings) >= 2 else None,
            "active_qualified": bool(active_rating_evidence.get("qualified")),
        },
        "analyst_observations": {
            "source": "benzinga" if analyst_observations else None,
            "source_endpoint": "analyst_insights" if analyst_observations else None,
            "observation_count": len(analyst_observations),
            "excluded_observation_count": excluded_observation_count,
            "as_of": analyst_observations[0].get("date")
            if analyst_observations else None,
            "oldest_observation_as_of": analyst_observations[-1].get("date")
            if analyst_observations else None,
            "observations": analyst_observations,
            "included_in_intrinsic_value": False,
            "content_policy": "structured_metadata_only_no_licensed_prose",
        },
        "forward_estimates": years,
        "valuation_cross_check": {
            # P/E has no useful interpretation at zero or negative earnings.
            "forward_pe_at_market": price / forward_eps
            if price is not None and forward_eps is not None and forward_eps > 0 else None,
            "forward_pe_at_mean_target": target_mean / forward_eps
            if target_mean is not None and forward_eps is not None and forward_eps > 0 else None,
            # These make the Street number economically interpretable instead
            # of leaving it as a decorative price target. They describe the
            # valuation the external target implies; they do not feed the DCF.
            "target_implied_market_cap": target_market_cap,
            "target_implied_enterprise_value": target_enterprise_value,
            "target_implied_ev_to_forward_revenue": (
                target_enterprise_value / forward_revenue
                if target_enterprise_value is not None
                and forward_revenue is not None and forward_revenue > 0 else None
            ),
            "forward_revenue_period": years[1]["period"],
        },
        "coverage": coverage,
        "warnings": warnings,
        "role": "external_benchmark_only",
        "included_in_intrinsic_value": False,
    }


def align_forward_estimates_to_forecast_basis(
    expectations: Dict[str, Any], forecast_basis: Optional[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Put Street fiscal-year estimates on the model's forecast clock.

    Yahoo's 0y/+1y estimates are fiscal-year totals. A model built at an
    intra-year quarter end forecasts a rolling next-twelve-month period, so a
    direct NTM1-versus-0y comparison is not like-for-like. Blend the two covered
    fiscal years by the same elapsed-fiscal-year fraction used by the model.
    Only NTM1 is returned when progress is non-zero because a second rolling
    comparison would require the unavailable +2y Street estimate.
    """
    rows = [dict(row) for row in (expectations or {}).get(
        "forward_estimates", []) if isinstance(row, dict)]
    basis = forecast_basis if isinstance(forecast_basis, dict) else {}
    if basis.get("basis") != "rolling_twelve_months" or len(rows) < 2:
        return rows
    progress = _number(basis.get("fiscal_year_progress"))
    if progress is None or not 0.0 <= progress <= 1.0 or progress <= 1e-12:
        return rows

    current, following = rows[0], rows[1]

    def blend(field: str) -> Optional[float]:
        first = _number(current.get(field))
        second = _number(following.get(field))
        if first is None or second is None:
            return None
        return first * (1.0 - progress) + second * progress

    revenue = blend("revenue")
    net_income = blend("implied_net_income")
    base_revenue = _number(basis.get("base_revenue"), positive=True)
    period_end = _timestamp(basis.get("period_end"))
    if period_end is not None:
        try:
            ntm_end = period_end.replace(year=period_end.year + 1)
        except ValueError:  # February 29
            ntm_end = period_end.replace(year=period_end.year + 1, day=28)
        period_label = f"NTM ending {ntm_end.date().isoformat()}"
    else:
        period_label = "NTM1"

    def covered_count(field: str) -> int:
        first = _count(current.get(field))
        second = _count(following.get(field))
        return min(first, second) if first and second else 0

    return [{
        **current,
        "horizon": "NTM1",
        "period": period_label,
        "revenue": revenue,
        "revenue_growth": (
            revenue / base_revenue - 1.0
            if revenue is not None and base_revenue is not None else None
        ),
        "revenue_analyst_count": covered_count("revenue_analyst_count"),
        "eps": blend("eps"),
        "eps_growth": None,
        "eps_analyst_count": covered_count("eps_analyst_count"),
        "implied_net_income": net_income,
        "implied_net_margin": (
            net_income / revenue
            if net_income is not None and revenue is not None and revenue > 0
            else None
        ),
        "forecast_alignment": {
            "basis": "rolling_twelve_months",
            "fiscal_year_progress": progress,
            "source_periods": [current.get("period"), following.get("period")],
            "method": "fiscal-progress blend of covered fiscal-year estimates",
        },
    }]


def reconcile_model_profitability(
    expectations: Dict[str, Any], projections: Dict[str, Any],
    forecast_basis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cross-check model NOPAT against the Street EPS/revenue operating case.

    EPS is levered net income while a DCF forecasts unlevered after-tax operating
    profit, so the two are deliberately *not* treated as accounting equivalents.
    They are still a useful launch rail: an eight-point margin disagreement with
    a well-covered Street case is too large to bury in an appendix. It means the
    earnings bridge, financing effects, share count, or operating assumptions
    need reconciliation before a point valuation is publishable.
    """
    expectations = expectations if isinstance(expectations, dict) else {}
    projections = projections if isinstance(projections, dict) else {}
    revenues = projections.get("revenue") or []
    nopat = projections.get("nopat") or []
    rows = []
    aligned_estimates = align_forward_estimates_to_forecast_basis(
        expectations, forecast_basis
    )
    for index, street in enumerate(aligned_estimates[:2]):
        if not isinstance(street, dict):
            continue
        model_revenue = revenues[index] if index < len(revenues) else None
        model_nopat = nopat[index] if index < len(nopat) else None
        model_margin = (
            float(model_nopat) / float(model_revenue)
            if _number(model_nopat) is not None
            and _number(model_revenue, positive=True) is not None else None
        )
        street_margin = _number(street.get("implied_net_margin"))
        margin_gap = (
            model_margin - street_margin
            if model_margin is not None and street_margin is not None else None
        )
        revenue_count = _count(street.get("revenue_analyst_count"))
        eps_count = _count(street.get("eps_analyst_count"))
        qualified = revenue_count >= 5 and eps_count >= 5
        diagnostic_conflict = bool(
            qualified and margin_gap is not None
            and abs(margin_gap) > PROFITABILITY_CONFLICT_PCT_POINTS
        )
        row = {
            "horizon": street.get("horizon") or f"FY{index + 1}",
            "period": street.get("period"),
            "model_after_tax_operating_margin": model_margin,
            "street_implied_net_margin": street_margin,
            "margin_gap": margin_gap,
            "revenue_analyst_count": revenue_count,
            "eps_analyst_count": eps_count,
            "qualified": qualified,
            # EPS can be GAAP or adjusted and can contain a one-time item that
            # is absent from unlevered NOPAT.  Preserve the raw diagnostic, but
            # do not call a single anomalous horizon a durable model conflict.
            "diagnostic_conflict": diagnostic_conflict,
            "material_conflict": False,
        }
        rows.append(row)
    diagnostic_conflicts = [row for row in rows if row["diagnostic_conflict"]]
    # Require persistence across both well-covered near-term horizons before
    # this accounting-basis comparison can independently block publication.
    # GOOGL's live FY0 consensus, for example, implied a 51% net margin and
    # then fell to 30% in FY+1; treating the isolated FY0 value as recurring
    # economics mislabeled a likely one-time/definition effect as a DCF flaw.
    qualified_horizons = [row for row in rows if row["qualified"]]
    conflicts = diagnostic_conflicts if (
        len(qualified_horizons) >= 2 and len(diagnostic_conflicts) >= 2
    ) else []
    conflict_ids = {id(row) for row in conflicts}
    for row in rows:
        row["material_conflict"] = id(row) in conflict_ids
    return {
        "rows": rows,
        "conflicts": conflicts,
        "diagnostic_conflicts": diagnostic_conflicts,
        "isolated_horizon_anomalies": [
            row for row in diagnostic_conflicts if id(row) not in conflict_ids
        ],
        "material_threshold_percentage_points": PROFITABILITY_CONFLICT_PCT_POINTS,
        "comparison_basis": (
            "Model NOPAT margin versus EPS-implied Street net margin. This is a "
            "directional profitability bridge, not an accounting equivalence. "
            + (
                "The first Street row is aligned to the model's rolling NTM clock. "
                if (forecast_basis or {}).get("basis") == "rolling_twelve_months"
                else ""
            )
            + "A hard publication conflict requires a material gap in both "
            "well-covered near-term horizons; an isolated gap remains a visible "
            "one-time/definition anomaly."
        ),
    }
