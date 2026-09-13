"""
Our four existing pipeline agents, wrapped as agent-callable tools.

CRITICAL: the wrapped agents' INTERNALS are unchanged — all the Phase 1–4 work
(parallel news screening, concurrent model+news, parallel report sections, the
crash-fix) lives inside them and rides along untouched. These wrappers only:

  1. hand the agent the shared FinancialState (so the dependency chain still works
     — e.g. build_model sees the financial_data that get_financials set, exactly as
     in the old pipeline), and
  2. summarize what the agent produced as a JSON string for the ReAct loop.

The shared state lives on an ``AgentContext`` that every tool in one run shares.
When the agent commits to a ticker, the tools set it on the context and (once)
print the ``Identified ticker:`` line api-runner scrapes.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

from .base import Tool, tool_ok, tool_error


class AgentContext:
    """
    Per-run shared state for the wrapped analysis tools.

    Holds the single FinancialState the tools mutate (preserving the data →
    model → news → report dependency chain), the logger, and run identity
    (email/timestamp/analysis_path). The generalizable agent owns one of these
    for the duration of a chat turn.
    """

    def __init__(self, email: str, timestamp: str, user_prompt: str, logger=None,
                 session_id: Optional[str] = None):
        self.email = email
        self.timestamp = timestamp
        self.user_prompt = user_prompt
        self.logger = logger
        self.state = None            # FinancialState, created when a ticker is set
        self.ticker: Optional[str] = None
        self.company_name: Optional[str] = None
        # When continuing an existing chat, pin the session identity to the
        # incoming session_id so the run logger (and the SESSION_ID it emits on
        # completion) stays STABLE across every turn. Otherwise each turn would
        # derive a fresh per-turn name (chat_<ts> / <ticker>_<ts>), the emitted
        # SESSION_ID would drift, and the next follow-up would read the wrong
        # session file. A fresh chat leaves this None and derives a name lazily.
        self.session_name: Optional[str] = session_id or None
        self.base_path = None        # run folder (ticker folder, or a CHAT folder)
        self.chat_base_path = None   # original CHAT folder, kept when base_path repoints
        self._ticker_announced = False
        # Requested ticker -> the listing we actually analyze, so a repeated
        # request for a bad line doesn't re-run the search over the network.
        self._listing_cache = {}

    def ensure_base_logger(self):
        """
        Guarantee a logger + run folder exist even when NO ticker is committed
        (pure chit-chat / general Q&A). Uses a 'CHAT' folder, mirroring the old
        conversational path so answer.md + completion logging still work.
        """
        if self.logger is not None:
            return self.logger
        from path_utils import get_analysis_path, ensure_analysis_paths
        from logger import setup_logger
        base = get_analysis_path(self.email, "CHAT", self.timestamp)
        ensure_analysis_paths(base)
        self.base_path = base
        # Remember the CHAT folder even if a ticker later repoints base_path:
        # the answer gets mirrored there so api-runner's CHAT fallback path
        # never finds an empty run dir.
        self.chat_base_path = base
        # Keep a pinned session_name (a continuing chat's session_id); only
        # derive a fresh one for a brand-new chat.
        if not self.session_name:
            self.session_name = f"chat_{self.timestamp}"
        self.logger = setup_logger("CHAT", base_path=base, session_name=self.session_name)
        return self.logger

    def ensure_state_for_ticker(self, ticker: str, company_name: Optional[str] = None):
        """
        Ensure a FinancialState exists for ``ticker``. Creates the analysis folder
        and logger on first use, resolves the company name from yfinance, and
        prints the ``Identified ticker:`` line exactly once (api-runner contract).
        Reuses the state if the same ticker is requested again.
        """
        from src.agents.supervisor.state import FinancialState
        from src.listing_resolver import better_listing, is_analyzable
        from path_utils import get_analysis_path, ensure_analysis_paths
        from logger import setup_logger

        ticker = (ticker or "").strip().upper()
        if not ticker:
            raise ValueError("ticker is required")
        # Guard: never let the conversational pseudo-tickers become a real
        # analysis target. Otherwise a vague "analyze this" with no company in
        # context would build a garbage model/report for the literal ticker
        # "CHAT" (yfinance returns nothing → fair value 0.0). The tools surface a
        # clean error the agent must handle by resolving a real company first.
        if ticker in ("CHAT", "PENDING", "UNKNOWN", "NONE", "N/A"):
            raise ValueError(
                f"'{ticker}' is not a real ticker. Resolve the actual company "
                f"(resolve_symbol) or ask the user which company they mean before analyzing."
            )

        # Map through any substitution decided on an earlier call BEFORE the reuse
        # check, so a second request for the original symbol lands on the state we
        # already built for its home listing instead of rebuilding it.
        ticker = self._listing_cache.get(ticker, ticker)

        # If we already have state for this ticker, reuse it (chain continuity).
        if self.state is not None and self.ticker == ticker:
            return self.state

        # A ticker the agent picked may be a regional or OTC line rather than the
        # company's home listing. Those quote a price but report no market cap and
        # no share count, so every downstream valuation divides into a hole and the
        # report ships NOT RATED. Verify the listing here, at the single point where
        # a ticker becomes the analysis target, instead of asking the prompt to get
        # it right. See src/listing_resolver.py for why the search needs two queries
        # and why ranking is not "biggest market cap".
        info = {}
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
        except Exception:
            info = {}

        # A depositary receipt trades in one currency and reports in another.
        # Toyota's ADR (TM) quotes in dollars over yen financials, and the model
        # divided yen equity by 1.3B ADRs against a $197 price — value per share
        # ¥77,233, "+21,000%", STRONG BUY. When the home line reports and trades
        # in the same currency, analyze that instead; when nothing does (Alibaba
        # reports CNY and trades HKD or USD), keep the listing and let the
        # scraper convert the price (see _price_in_financial_currency).
        mismatch = (info.get("currency") and info.get("financialCurrency")
                    and info.get("currency") != info.get("financialCurrency")
                    and "." not in ticker)
        if info and mismatch and is_analyzable(info):
            try:
                upgrade = better_listing(ticker, info)
                if upgrade:
                    import yfinance as yf
                    cand = yf.Ticker(upgrade[0]).info or {}
                    if cand.get("currency") != cand.get("financialCurrency"):
                        upgrade = None      # would not resolve the mismatch
            except Exception:
                upgrade = None
            if upgrade:
                better_symbol, better_name = upgrade
                print(
                    f"[SUPERVISOR] ↪ {ticker} trades in {info.get('currency')} but reports in "
                    f"{info.get('financialCurrency')}; analyzing the home listing {better_symbol} instead."
                )
                self._listing_cache[ticker] = better_symbol
                ticker = better_symbol
                company_name = company_name or better_name
                try:
                    info = yf.Ticker(ticker).info or {}
                except Exception:
                    pass

        if info and not is_analyzable(info):
            try:
                upgrade = better_listing(ticker, info)
            except Exception:
                upgrade = None
            if upgrade:
                better_symbol, better_name = upgrade
                print(
                    f"[SUPERVISOR] ↪ {ticker} has no market cap or share count "
                    f"(secondary listing); analyzing {better_symbol} instead."
                )
                self._listing_cache[ticker] = better_symbol
                ticker = better_symbol
                company_name = company_name or better_name
                try:
                    info = yf.Ticker(ticker).info or {}
                except Exception:
                    pass

        # Resolve company name (best-effort).
        if not company_name:
            company_name = info.get("longName") or ticker

        analysis_path = get_analysis_path(self.email, ticker, self.timestamp)
        ensure_analysis_paths(analysis_path)
        self.base_path = analysis_path
        if not self.session_name:
            self.session_name = f"{ticker.lower()}_{self.timestamp}"

        # Anchor the run logger to this ticker's folder. If we'd previously set up
        # a placeholder CHAT logger (before a ticker was known), REPOINT to the
        # ticker folder now so all subsequent logs (and the pipeline's own logging)
        # consolidate in one place instead of splitting CHAT/ vs TICKER/.
        self.logger = setup_logger(ticker, base_path=analysis_path, session_name=self.session_name)

        self.state = FinancialState(
            user_query=self.user_prompt,
            ticker=ticker,
            company_name=company_name,
            email=self.email,
            analysis_path=str(analysis_path),
            timestamp=self.timestamp,
        )
        self.ticker = ticker
        self.company_name = company_name

        # api-runner scrapes this exact line to label the job. Print once.
        if not self._ticker_announced:
            print(f"[SUPERVISOR] ✅ Identified ticker: {ticker}")
            self._ticker_announced = True
            self.logger.info(f"[SUPERVISOR] ✅ Identified ticker: {ticker}")

        return self.state


_TICKER_PARAM = {
    "ticker": {
        "type": "string",
        "description": "The stock ticker symbol to operate on, e.g. 'NVDA', 'AAPL'. "
                       "For non-US names resolve to a ticker first with resolve_symbol.",
    }
}


def _listing_price_note(state) -> dict:
    """
    When the listing trades in a different currency from its statements, the
    figures are in the statements' currency and the price was converted. Give
    the chat the original quote and the rate so it can say "£34.37 (≈$46.43)"
    rather than a dollar price a London investor has never seen.
    """
    try:
        km = state.financial_data.key_metrics if state.financial_data else {}
        bi = (km.get("basic_info") or {}) if isinstance(km, dict) else {}
        md = (km.get("market_data") or {}) if isinstance(km, dict) else {}
        lc, rc = bi.get("listing_currency"), bi.get("currency")
        px, fx = md.get("current_price_listing"), md.get("fx_listing_to_financial")
        if lc and rc and lc != rc and isinstance(px, (int, float)):
            return {"listing_currency": lc, "price_in_listing_currency": px,
                    "fx_rate_listing_to_reporting": fx,
                    "currency_note": (f"Figures are in {rc}, the currency of the financial statements. "
                                      f"The listing trades in {lc} at {px:,.2f}; the price was converted"
                                      + (f" at {fx:.4f} {rc}/{lc}." if fx else "."))}
    except Exception:
        pass
    return {}


def _listing_currency(state) -> Optional[str]:
    """
    The currency the scraped listing reports in.

    findings.py formats every monetary chip with this; without it a EUR
    valuation is published to the chat surface as "$388.27".
    """
    try:
        km = state.financial_data.key_metrics if state.financial_data else {}
        if isinstance(km, dict):
            return (km.get("basic_info", {}) or {}).get("currency") or None
    except Exception:
        pass
    return None


def _report_headline(content: Optional[str]) -> dict:
    """
    The rating and price target the report actually published.

    write_report returned a fair value and an upside but never the RATING, so the
    chat answer inferred its own call from the numbers. A user got a report
    headed "Investment Rating: SELL" and an answer that said "HOLD / Neutral"
    about the same company in the same turn.

    These lines are emitted by the recommendation engine in code, not written by
    the model, so reading them back is reliable.
    """
    out: dict = {}
    if not content:
        return out
    # Tolerates both depths: reports written before the heading was nested
    # under "Recommendation & Price Target" used a second H2.
    rating = re.search(r"^#{2,3}\s*Investment Rating:\s*(.+?)\s*$", content, re.M)
    if rating:
        out["rating"] = rating.group(1).strip()
    target = re.search(
        r"\*\*12-Month Price Target\*\*:\s*"
        r"((?:[A-Z]{3}\s+)?(?:[$€£¥₹]\s*)?[\d,]+(?:\.\d+)?)",
        content,
    )
    if target:
        out["price_target_12m"] = target.group(1).strip()
    expected = re.search(
        r"\*\*(?:Expected Return|Implied Return if Intrinsic Value Converges)\*\*:\s*"
        r"([+-]?[\d.]+)%",
        content,
    )
    if expected:
        out["price_target_expected_return_pct"] = float(expected.group(1))
    return out


def _bounded_report_headline(
    content: Optional[str], *, point_estimate_withheld: bool
) -> dict:
    """Return only headline claims permitted by the machine publication gate.

    Old or partially-written markdown can contain a directional rating/target
    even when the durable model manifest later says publication was withheld.
    Markdown is evidence for what was rendered, never authority to override the
    machine decision.  Fail closed so neither ``write_report`` nor
    ``read_report`` hands an unsafe headline back to the conversational model.
    """
    headline = _report_headline(content)
    if point_estimate_withheld:
        return {"rating": "NOT RATED"}
    return headline


def _bounded_news_payload(
    analysis,
    *,
    sentiment_key: str,
    freshness_key: str,
) -> dict:
    """Expose directional news sentiment only from a fresh admitted source set."""
    freshness = getattr(analysis, "freshness", {}) if analysis else {}
    freshness = freshness if isinstance(freshness, dict) else {}
    payload = {freshness_key: freshness or {"status": "unavailable"}}
    if freshness.get("status") == "fresh":
        sentiment = getattr(analysis, "overall_sentiment", None)
        if sentiment:
            payload[sentiment_key] = sentiment
    return payload


def _rehydrate_report_guard_state(base: Path, ticker: str, content: str):
    """Restore the machine publication boundary for a report follow-up.

    ``read_report`` often runs in a fresh process.  The markdown is still on
    disk, but the in-memory FinancialState that protected the original answer
    is gone.  Returning the report body without restoring that state let a
    follow-up prose model resurrect the workbook's audit-only midpoint or a
    sentiment computed from stale coverage.  Rebuild only the small state the
    deterministic final-answer guard consumes.  Missing/legacy metadata fails
    closed instead of implicitly granting publication permission.
    """
    import json
    from types import SimpleNamespace

    financial_path = base / "financials" / "financials_annual_modeling_latest.json"
    computed_path = base / "models" / f"{ticker}_financial_model_computed_values.json"
    screening_path = base / "screened" / "screening_data.json"

    financial_data = {}
    try:
        loaded = json.loads(financial_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            financial_data = loaded
    except Exception:
        financial_data = {}

    publication = {}
    computed = {}
    try:
        loaded = json.loads(computed_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            computed = loaded
            publication = ((computed.get("_vynn") or {}).get(
                "valuation_publication") or {})
    except Exception:
        computed = {}
        publication = {}

    method = publication.get("valuation_method")
    ready = publication.get("status") == "ready"
    withheld = bool(publication.get("point_estimate_withheld")) if ready else True
    canonical = publication.get("canonical_fair_value") if ready else None
    if not withheld and not (
        isinstance(canonical, (int, float)) and not isinstance(canonical, bool)
        and math.isfinite(float(canonical)) and float(canonical) > 0
    ):
        withheld = True

    reason = publication.get("withheld_reason") if ready else None
    if withheld and not reason:
        reason = (
            "The saved report does not contain a complete machine-readable "
            "publication decision, so its valuation can be reviewed for audit "
            "but no point fair value or directional rating can be republished."
        )

    method_values = publication.get("method_values_for_audit") or {}
    method_inputs = publication.get("valuation_method_inputs") or {}
    metrics = {
        "valuation_method": method or "dcf",
        "point_estimate_withheld": withheld,
        "publication_withheld_reason": reason,
        "valuation_confidence": publication.get("valuation_confidence"),
        "comps_included_in_blended_value": bool(
            publication.get("comps_included_in_blended_value")
        ),
    }
    if method == "justified_pb_roe":
        metrics.update({
            "bank_intrinsic_fair_value": method_inputs.get("intrinsic_fair_value"),
            "bank_forward_consensus_fair_value": method_inputs.get(
                "forward_consensus_fair_value"
            ),
            "bank_peer_fair_value": method_inputs.get("peer_fair_value"),
        })
    else:
        metrics.update({
            "perpetual_price": method_values.get("perpetual_dcf"),
            "exit_multiple_price": method_values.get("exit_multiple_dcf"),
            "comps_price": method_values.get("market_comps"),
        })
    if ready:
        # Retain the audit number only inside guard state so the guard can
        # recognize and reject it.  It is deliberately omitted from the tool's
        # public payload below when the point estimate was withheld.
        metrics.update({
            "fair_value": publication.get("model_value_for_audit"),
            "upside_vs_market": publication.get("canonical_upside_vs_market"),
        })

    if computed:
        try:
            from src.report_agent import extract_projections, extract_valuation
            extracted = extract_valuation(computed)
            reverse = extracted.get("reverse_dcf") or {}
            metrics.update({
                "market_implied_terminal_fcf": reverse.get(
                    "market_implied_terminal_fcf"),
                "market_implied_fcf_vs_model": reverse.get(
                    "market_implied_vs_model"),
                "model_revenue_forecast": (
                    (extract_projections(computed) or {}).get("revenue") or []
                ),
            })
            from src.external_expectations import (
                implied_discount_rate_for_enterprise_value,
                implied_fcf_path_scale_for_enterprise_value,
                implied_terminal_growth_for_enterprise_value,
                implied_terminal_fcf_for_enterprise_value,
            )
            target_ev = (((financial_data.get("external_expectations") or {}).get(
                "valuation_cross_check") or {}).get(
                    "target_implied_enterprise_value"))
            target_reverse = implied_terminal_fcf_for_enterprise_value(
                target_ev,
                pv_explicit_fcf=(extracted.get("dcf_perpetual") or {}).get(
                    "pv_fcfs"),
                pv_terminal_value=(extracted.get("dcf_perpetual") or {}).get(
                    "terminal_value"),
                model_terminal_fcf=reverse.get("model_terminal_fcf"),
            )
            if target_reverse.get("available"):
                metrics.update({
                    "analyst_target_implied_terminal_fcf":
                        target_reverse["implied_terminal_fcf"],
                    "analyst_target_implied_fcf_vs_model":
                        target_reverse["implied_fcf_vs_model"],
                })
            dcf_cells = (computed.get("Valuation (DCF)") or {}).get("cells") or {}
            model_ev = dcf_cells.get("(27, 2)")
            market_ev = (((computed.get("Summary") or {}).get("cells") or {}).get(
                "(51, 2)"
            ))
            market_scale = implied_fcf_path_scale_for_enterprise_value(
                market_ev, model_enterprise_value=model_ev
            )
            target_scale = implied_fcf_path_scale_for_enterprise_value(
                target_ev, model_enterprise_value=model_ev
            )
            if market_scale.get("available"):
                metrics["market_implied_fcf_path_vs_model"] = (
                    market_scale["implied_fcf_path_vs_model"]
                )
            if target_scale.get("available"):
                metrics["analyst_target_implied_fcf_path_vs_model"] = (
                    target_scale["implied_fcf_path_vs_model"]
                )
            explicit_fcf = [
                dcf_cells.get(f"(16, {column})") for column in range(2, 12)
            ]
            dcf_wacc = dcf_cells.get("(12, 2)")
            dcf_growth = dcf_cells.get("(23, 2)")
            mid_year_adjustment = (
                (computed.get("Sensitivity") or {}).get("cells", {}).get(
                    "(4, 2)", 0.0
                )
            )
            metrics["wacc"] = dcf_wacc
            metrics["terminal_growth"] = dcf_growth
            for prefix, benchmark_ev in (
                ("market", market_ev), ("analyst_target", target_ev),
            ):
                implied_rate = implied_discount_rate_for_enterprise_value(
                    benchmark_ev, explicit_fcf=explicit_fcf,
                    terminal_growth=dcf_growth, model_wacc=dcf_wacc,
                    mid_year_adjustment=mid_year_adjustment,
                )
                if implied_rate.get("available"):
                    metrics[f"{prefix}_implied_wacc"] = implied_rate["implied_wacc"]
                    metrics[f"{prefix}_implied_wacc_vs_model"] = implied_rate[
                        "implied_wacc_vs_model"
                    ]
                implied_growth = implied_terminal_growth_for_enterprise_value(
                    benchmark_ev, explicit_fcf=explicit_fcf, wacc=dcf_wacc,
                    model_terminal_growth=dcf_growth,
                    mid_year_adjustment=mid_year_adjustment,
                )
                if implied_growth.get("available"):
                    metrics[f"{prefix}_implied_terminal_growth"] = implied_growth[
                        "implied_terminal_growth"
                    ]
                    metrics[f"{prefix}_implied_terminal_growth_vs_model"] = (
                        implied_growth["implied_terminal_growth_vs_model"]
                    )
        except Exception:
            pass

    company = financial_data.get("company_data") or {}
    basic = company.get("basic_info") or {}
    market = company.get("market_data") or {}
    metrics["current_price"] = market.get("current_price")
    revenue_source = (((computed.get("_vynn") or {}).get("model_inputs") or {}).get(
        "revenue_growth_source") if computed else None)
    reinvestment = (
        ((computed.get("_vynn") or {}).get("reinvestment_sensitivity") or {})
        if computed else {}
    )
    if isinstance(reinvestment, dict):
        metrics["reinvestment_sensitivity"] = reinvestment

    freshness = {"status": "unavailable"}
    sentiment = None
    try:
        screening = json.loads(screening_path.read_text(encoding="utf-8"))
        if isinstance(screening, dict):
            candidate = screening.get("freshness") or {}
            freshness = candidate if isinstance(candidate, dict) else freshness
            summary = screening.get("analysis_summary") or {}
            if isinstance(summary, dict):
                sentiment = summary.get("overall_sentiment")
    except Exception:
        pass

    return SimpleNamespace(
        financial_data=SimpleNamespace(
            raw_data=financial_data,
            key_metrics={"basic_info": basic, "market_data": market},
        ),
        financial_model=SimpleNamespace(
            model_type=("bank_justified_pb_roe" if method == "justified_pb_roe"
                        else "DCF"),
            assumptions={"revenue_growth_source": revenue_source},
            valuation_metrics=metrics,
        ),
        news_analysis=SimpleNamespace(
            freshness=freshness,
            overall_sentiment=sentiment,
        ),
        report=SimpleNamespace(content=content),
    )


from src.currency import currency_symbol  # noqa: E402

# What "mega-cap" means, in USD. Roughly the top ~40 companies on earth.
_MEGACAP_USD = 200e9

# Units of local currency per USD, for the handful of markets this product
# actually reaches. Deliberately a STATIC table and not a live FX call: this is
# a sanity rail, so a network hiccup must never change whether a valuation is
# flagged, and an order-of-magnitude figure is all a "is this a mega-cap?"
# question needs. Rates need only be right to ~20% for the threshold to sort
# companies correctly.
_USD_PER_UNIT = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CHF": 1.12, "CAD": 0.73,
    "AUD": 0.66, "JPY": 0.0067, "CNY": 0.14, "HKD": 0.128, "TWD": 0.031,
    "KRW": 0.00072, "INR": 0.0113, "SGD": 0.74, "SEK": 0.093, "NOK": 0.091,
    "DKK": 0.145, "BRL": 0.18, "MXN": 0.050, "ZAR": 0.054, "ILS": 0.27,
    "THB": 0.028, "IDR": 0.000062, "MYR": 0.22, "PHP": 0.017, "VND": 0.000040,
    "TRY": 0.029, "PLN": 0.25, "SAR": 0.267, "AED": 0.272,
}


def _megacap_threshold(currency):
    """
    The mega-cap threshold expressed in `currency`.

    THE BUG this fixes: the rail compared a market cap in the LISTING's own
    currency against a bare 200e9, which is only USD. A 200bn KRW company is
    worth about $144M — a micro-cap — yet it cleared a threshold meant for the
    forty largest companies on earth and had its valuation suppressed as
    "a ~$200B mega-cap". Every yen, won, rupee and rupiah listing was affected.
    An unknown currency keeps the USD threshold, which fails toward flagging
    rather than toward silently suppressing.
    """
    code = (currency or "").strip().upper()
    if code == "GBP" or code == "GBX":       # pence handled upstream; treat as GBP
        code = "GBP"
    per_unit = _USD_PER_UNIT.get(code)
    if not per_unit:
        return _MEGACAP_USD
    return _MEGACAP_USD / per_unit


def _valuation_warning(fair_value, upside, market_cap=None, method=None, currency=None):
    """
    Sanity rail on valuation output. An FCF-projection DCF on a deeply
    FCF-negative or freshly listed company produces mathematically valid
    nonsense (negative fair value, -100% "upside") — e.g. SpaceX right after
    its IPO with -$14B FCF. And on mega-caps, a large implied mispricing is
    far more often a broken assumption than a broken market (a GOOGL DCF
    shipped -55% vs price to a real user). Flag both so the agent leads with
    the caveat instead of the number.

    `upside` is a FRACTION (e.g. -0.55 for -55%). `market_cap` is in the
    LISTING's currency, so the mega-cap threshold is converted into that
    currency before the comparison — see _megacap_threshold.
    """
    if method == "justified_pb_roe":
        return ("METHOD NOTE: fair value comes from a bank-appropriate "
                "justified P/B x ROE (Gordon) model on book value per share; "
                "the standard FCF DCF is suppressed as not meaningful for "
                "financials. Present the fair value WITH this method note.")
    try:
        fv = float(fair_value) if fair_value is not None else None
        up = float(upside) if upside is not None else None
        mcap = float(market_cap) if market_cap else None
    except (TypeError, ValueError):
        return None
    # upside is contractually a fraction everywhere it is produced — a plain
    # conversion keeps the rails armed even for absurd (>500%) upsides. (A
    # defensive "looks like a percent already" heuristic here disarmed both
    # rails precisely for the most broken valuations.)
    up_pct = up * 100 if up is not None else None
    if fv is not None and fv <= 0:
        return ("UNRELIABLE VALUATION: the DCF produced a non-positive fair value, "
                "which means the company's free cash flow profile (heavy investment / "
                "negative FCF, common for growth or recently listed names) breaks this "
                "method. Do NOT present this number as the company's worth. Say the DCF "
                "is not meaningful for this profile and analyze via growth, unit "
                "economics, and market pricing instead.")
    threshold = _megacap_threshold(currency)
    if mcap is not None and mcap >= threshold and up_pct is not None and abs(up_pct) > 40:
        sym = currency_symbol(currency) if currency else "$"
        return (f"SUSPECT VALUATION: the DCF implies {up_pct:+.0f}% vs the market "
                f"price for a ~{sym}{mcap/1e9:.0f}B mega-cap. Markets rarely misprice "
                "companies this large by 40%+; the far more likely culprit is the "
                "DCF's assumptions (WACC, terminal growth, FCF normalization). "
                "Cross-check against market multiples (trailing/forward P/E, "
                "EV/EBITDA vs peers) before presenting, and present the DCF as ONE "
                "method with this caveat leading — never as a headline fair value.")
    if up_pct is not None and up_pct <= -70:
        return ("SUSPECT VALUATION: the DCF implies more than 70% downside vs the "
                "market price. That can be real, but with negative or thin FCF history "
                "it usually means the method fits this company poorly. Present it with "
                "that caveat, not as a headline conclusion.")
    return None


def valuation_dispersion(legs: dict):
    """
    How much do the valuation methods disagree?

    THE GAP THIS CLOSES. Every rail above inspects only the FINAL blended
    number, so a fair value averaged from methods that wildly contradict each
    other sails through as long as the average lands near the market price.
    Measured across 39 real production models:

        EOG    perpetual $3.97   vs exit $215.64   -> blend $109.81, "-18.5%"
        META   perpetual $27.50  vs exit $906.98   -> blend $467.24, "-22.8%"
        BTSG   perpetual $30.93  vs exit $93.67    -> blend $62.30,  "+4.3%"

    None of those tripped an existing rail: the blend is positive, the company
    is not a mega-cap, and the implied upside is mild. The user is handed a
    confident number built from methods that disagree by up to 54x. The median
    spread across all 39 models was 1.85x, and 31 of 39 exceeded 1.5x.

    A blend of two numbers 54x apart is not a valuation — it is the midpoint of
    an interval so wide it excludes nothing. Reporting its centre as a fair
    value is the most misleading thing this pipeline can do, because it looks
    exactly like a precise answer.

    Returns (ratio, band, note) where band is one of
    tight / moderate / wide / unreliable, or (None, None, None) when fewer than
    two legs are usable.
    """
    usable, broken = {}, []
    for name, v in (legs or {}).items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f != f:                      # NaN
            continue
        # Non-positive legs are excluded from the blend upstream, so they must
        # not also widen the spread and double-count the same problem. They are
        # still recorded: a method that returned a negative share price did not
        # produce a low estimate, it FAILED.
        if f > 0:
            usable[name] = f
        elif f == 0 and "comp" in str(name).lower():
            # Workbook convention: zero market comps means the optional
            # provider/method was unavailable, not that it valued the equity
            # at zero.  Do not misclassify that absence as a failed method.
            continue
        else:
            broken.append(name)

    # One method blew up while another survived. The blend drops the broken leg
    # and hands over a confident single-method number with no hint that half the
    # analysis failed — HOOD shipped $38.05 with a perpetual DCF of -$7.23.
    if broken and usable:
        return None, "single-method", (
            f"HALF THE MODEL FAILED: {', '.join(broken)} produced a non-positive "
            f"value per share, so the fair value rests on "
            f"{' and '.join(usable)} alone. A negative share price is not a low "
            "estimate, it is a method that does not fit this company's cash-flow "
            "profile. Say the valuation rests on one method and why the other "
            "broke; do not present the survivor as a consensus fair value.")

    if len(usable) < 2:
        return None, None, None

    lo, hi = min(usable.values()), max(usable.values())
    ratio = hi / lo

    # The two DCF terminal-value variants are sensitivity cases inside ONE
    # methodology, not two independent valuation opinions.  When they agree
    # tightly but no market-comps leg exists, calling the result ``tight``
    # overstates the evidence: all of it still rests on the same forecast,
    # WACC and terminal economics.  Keep genuinely divergent DCF cases in the
    # normal moderate/wide/unreliable bands below, but identify a converged
    # DCF-only result as single-method so publication controls can require an
    # independent cross-check for exceptional claims.
    names = {str(name).lower().replace("_", " ") for name in usable}
    has_dcf_pair = (
        any("perpetual" in name for name in names)
        and any("exit" in name for name in names)
    )
    has_market_comps = any("comp" in name for name in names)
    if has_dcf_pair and not has_market_comps and ratio < 1.3:
        spread_txt = ", ".join(
            f"{k.replace('_', ' ')} {v:,.2f}"
            for k, v in sorted(usable.items(), key=lambda kv: kv[1])
        )
        return ratio, "single-method", (
            "DCF-ONLY VALUATION: the perpetuity and exit-multiple cases agree, "
            "but they share the same cash-flow forecast, discount rate and "
            f"terminal economics ({spread_txt}). No independent market-comps "
            "method was available. Present these as a DCF scenario range, not "
            "as independently triangulated fair value."
        )

    # No currency symbol here: this text reaches EUR and INR listings too.
    spread_txt = ", ".join(f"{k.replace('_', ' ')} {v:,.2f}" for k, v in sorted(usable.items(), key=lambda kv: kv[1]))

    if ratio < 1.3:
        return ratio, "tight", None
    if ratio < 1.8:
        return ratio, "moderate", (
            f"VALUATION RANGE: the methods span {lo:,.2f}–{hi:,.2f} per share "
            f"({ratio:.1f}x). Present the RANGE alongside the point estimate "
            f"({spread_txt}), not the average alone.")
    if ratio < 2.5:
        return ratio, "wide", (
            f"WIDE VALUATION SPREAD: the methods disagree by {ratio:.1f}x "
            f"({spread_txt}). The average is not a reliable point estimate. "
            "Lead with the RANGE and name the assumption driving the gap "
            "(usually terminal value: perpetual growth vs the exit multiple). "
            "Do NOT present a single fair value as if it were precise.")
    return ratio, "unreliable", (
        f"UNRELIABLE VALUATION — METHODS CONTRADICT: {spread_txt}, a "
        f"{ratio:.1f}x spread. An average of numbers this far apart is not a "
        "valuation; it is the midpoint of an interval so wide it excludes "
        "nothing. Do NOT quote a fair value or an upside percentage. Say the "
        "model does not converge for this company, show the range, and explain "
        "why (typically terminal-value assumptions the cash-flow profile "
        "cannot support). Analyse via growth, unit economics and market "
        "multiples instead.")


def valuation_publication_boundary(*, band, legs, fair_value, current_price,
                                   is_mega_cap=False, analyst_target=None,
                                   analyst_count=0, analyst_rating=None,
                                   analyst_rating_count=0,
                                   analyst_rating_evidence=None,
                                   analyst_target_evidence=None,
                                   reverse_dcf_gap=None):
    """Decide whether a precise fair value/rating is safe to publish.

    This does not alter a model or pull its answer toward the market.  It
    separates an auditable scenario output from a publishable investment call.
    Large claims about heavily covered mega-caps need independent support; two
    terminal-value variants of the same DCF do not provide it.

    Returns ``(withheld, reason)``.
    """
    positive = {
        str(name): float(value)
        for name, value in (legs or {}).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and value > 0 and abs(float(value)) != float("inf") and value == value
    }
    broken = {
        str(name) for name, value in (legs or {}).items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(float(value)) and value <= 0
        and not (value == 0 and "comp" in str(name).lower())
    }
    blocking_reasons = []

    def add_blocker(message):
        normalized = " ".join(str(message or "").split())
        if normalized and normalized not in blocking_reasons:
            blocking_reasons.append(normalized)

    def blocked_result(*context):
        parts = list(blocking_reasons)
        for value in context:
            normalized = " ".join(str(value or "").split())
            if normalized and not any(
                normalized in existing or existing in normalized
                for existing in parts
            ):
                parts.append(normalized)
        return True, " ".join(parts)

    # Do not return at the first failure.  The model may simultaneously have a
    # broken leg, an exceptional market gap, and conflicting human-analyst
    # evidence.  Returning here used to hide the latter two facts in exactly
    # the cases where a user most needs to see them (for example, a pre-cash-
    # flow growth company with one failed DCF terminal method).
    if positive and broken:
        add_blocker(
            "At least one valuation method failed with a non-positive value "
            f"({', '.join(sorted(broken))}). The surviving method may be shown "
            "for audit, but it is not sufficient for a point estimate, "
            "directional rating, or price target."
        )
    if band in {"wide", "unreliable"} and len(positive) >= 2:
        if band == "unreliable":
            add_blocker(
                "The valuation methods disagree by more than 2.5x, so no "
                "defensible point estimate exists."
            )
        else:
            add_blocker(
                "The valuation methods span more than 1.8x. That range is useful "
                "scenario evidence, but it is too wide for a defensible point "
                "estimate, directional rating, or price target."
            )

    try:
        value = float(fair_value)
    except (TypeError, ValueError):
        value = float("nan")
    if not math.isfinite(value) or value <= 0:
        add_blocker(
            "No finite positive intrinsic-value output was produced, so no "
            "point estimate, directional rating, or price target can be published."
        )
    try:
        price = float(current_price)
    except (TypeError, ValueError):
        price = float("nan")
    # An intrinsic estimate can remain available for an unquoted/private
    # instrument, but no price-relative recommendation can be derived. The
    # recommendation calculator independently enforces that rating boundary.
    if not math.isfinite(price) or price <= 0:
        return blocked_result() if blocking_reasons else (False, None)

    model_gap = value / price - 1.0 if math.isfinite(value) and value > 0 else None
    # A DCF-only result is two terminal-value variants of one cash-flow model,
    # not two independent measurements.  For every issuer, a claim this far
    # from the traded market needs a second valuation lens.  Well-covered
    # Street evidence becomes material one step earlier when it points the
    # other way: it is not averaged into intrinsic value, but it can identify
    # an assumption dispute large enough that publishing a directional target
    # would overstate what the model has established.
    # A BUY/SELL starts at a 15% gap in the deterministic recommendation
    # engine. That is also where a DCF-only result must earn independent
    # numeric corroboration; otherwise the product can still publish a 29%
    # mega-cap call while treating the human benchmark as optional.
    threshold = 0.15

    try:
        target = float(analyst_target)
        count = int(analyst_count or 0)
    except (TypeError, ValueError, OverflowError):
        target, count = 0.0, 0
    count = min(max(count, 0), 100_000)
    has_street_benchmark = bool(
        target > 0 and count >= 5
        and target == target and abs(target) != float("inf")
    )
    analyst_gap = target / price - 1.0 if has_street_benchmark else None
    # From a 15% model gap onward, well-covered consensus that is neutral or
    # points the other way is a material unresolved assumption dispute. The old
    # code returned above before evaluating consensus for any gap below 30/40%,
    # so a -28% mega-cap DCF could publish a SELL while 50+ analysts expected
    # positive return. Consensus remains a cross-check only: it is never
    # averaged into intrinsic value and cannot manufacture a rating.
    target_evidence_rows = []
    if isinstance(analyst_target_evidence, dict):
        target_evidence_rows.extend(
            {**row, "source": row.get("source") or source}
            for source, row in analyst_target_evidence.items()
            if isinstance(row, dict)
        )
    elif isinstance(analyst_target_evidence, list):
        target_evidence_rows.extend(
            row for row in analyst_target_evidence if isinstance(row, dict)
        )

    qualified_targets = []
    seen_targets = set()
    for row in target_evidence_rows:
        try:
            row_target = float(row.get("mean") or row.get("target"))
            row_count = min(max(int(row.get("analyst_count") or 0), 0), 100_000)
        except (TypeError, ValueError, OverflowError):
            continue
        source = str(row.get("source") or "provider").strip()[:50]
        key = (source.casefold(), round(row_target, 8), row_count)
        qualified_for_contradiction = (
            row.get("qualified_for_contradiction")
            if "qualified_for_contradiction" in row else row.get("qualified") is not False
        )
        if (qualified_for_contradiction and row_count >= 5 and row_target > 0
                and math.isfinite(row_target) and key not in seen_targets):
            seen_targets.add(key)
            row_gap = row_target / price - 1.0
            qualified_targets.append({
                "source": source,
                "count": row_count,
                "gap": row_gap,
                "corroboration_qualified": bool(
                    row.get("qualified_for_corroboration", True)
                ),
                "temporal_status": (
                    (row.get("temporal_quality") or {}).get("status")
                ),
            })

    # The active target remains the compatibility path for old artifacts.
    # Avoid printing/evaluating it twice when source evidence already carries
    # the exact same population and value.
    active_target_present = any(
        row["count"] == count and abs(row["gap"] - analyst_gap) < 1e-10
        for row in qualified_targets
    ) if analyst_gap is not None else False
    if has_street_benchmark and not active_target_present and not target_evidence_rows:
        qualified_targets.insert(0, {
            "source": "active consensus", "count": count, "gap": analyst_gap,
            # Compatibility path for artifacts that predate source evidence.
            "corroboration_qualified": True,
        })

    def target_corroborates_model(target_gap):
        """Require aligned direction *and* meaningful magnitude.

        A +6% Street target does not corroborate a +49% DCF claim merely
        because both numbers are positive. For a model conclusion of at least
        15%, the benchmark must point the same way and support at least half
        the claimed move (with a 5% absolute floor). It remains an external
        cross-check and never enters intrinsic value arithmetic.
        """
        return bool(
            model_gap is not None and model_gap * target_gap > 0
            and abs(target_gap) >= max(0.05, abs(model_gap) * 0.50)
        )

    has_target_corroboration = bool(
        model_gap is not None and abs(model_gap) >= 0.15
        and qualified_targets
        and any(
            row.get("corroboration_qualified")
            and target_corroborates_model(row["gap"])
            for row in qualified_targets
        )
    )
    has_provider_dated_current_target = any(
        row.get("corroboration_qualified") for row in qualified_targets
    )
    target_not_corroborated = bool(
        model_gap is not None and abs(model_gap) >= 0.15
        and qualified_targets
        and any(not target_corroborates_model(row["gap"])
                for row in qualified_targets)
    )

    def rating_direction(label):
        normalized = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"strong_buy", "buy", "outperform", "overweight"}:
            return 1
        if normalized in {"strong_sell", "sell", "underperform", "underweight"}:
            return -1
        if normalized in {"hold", "neutral", "market_perform", "equal_weight"}:
            return 0
        return None

    evidence_rows = []
    if isinstance(analyst_rating_evidence, dict):
        evidence_rows.extend(
            {**row, "source": row.get("source") or source}
            for source, row in analyst_rating_evidence.items()
            if isinstance(row, dict)
        )
    elif isinstance(analyst_rating_evidence, list):
        evidence_rows.extend(row for row in analyst_rating_evidence if isinstance(row, dict))

    def evidence_count(row):
        try:
            return min(max(int(
                row.get("analyst_count") or row.get("total")
                or row.get("unique_analyst_count") or 0
            ), 0), 100_000)
        except (TypeError, ValueError, OverflowError):
            return 0

    active_count = evidence_count({"analyst_count": analyst_rating_count})
    active_label = str(analyst_rating or "").strip()
    active_already_present = any(
        str(row.get("label") or "").strip().casefold() == active_label.casefold()
        and evidence_count(row) == active_count
        for row in evidence_rows
    )
    if analyst_rating and not active_already_present and not evidence_rows:
        evidence_rows.append({
            "label": analyst_rating,
            "analyst_count": active_count,
            "source": "active consensus",
        })

    qualified_ratings = []
    seen_ratings = set()
    for row in evidence_rows:
        label = str(row.get("label") or "").strip()
        direction = rating_direction(label)
        rating_count = evidence_count(row)
        source = str(row.get("source") or "provider").strip()[:50]
        key = (source.casefold(), label.casefold(), rating_count)
        if (row.get("qualified") is not False and direction is not None
                and rating_count >= 5 and key not in seen_ratings):
            seen_ratings.add(key)
            qualified_ratings.append({
                "direction": direction,
                "label": label.replace("_", " ").upper()[:40],
                "count": rating_count,
                "source": source,
            })

    model_direction = 1 if model_gap is not None and model_gap > 0 else -1
    rating_not_corroborated = bool(
        model_gap is not None and abs(model_gap) >= 0.15 and any(
            row["direction"] != model_direction for row in qualified_ratings
        )
    )
    not_corroborated = target_not_corroborated or rating_not_corroborated

    benchmark_parts = []
    for row in qualified_targets[:3]:
        prefix = "the" if row["source"] == "active consensus" else row["source"]
        temporal_note = (
            " (provider date unavailable; caution only)"
            if row.get("temporal_status") == "unknown" else ""
        )
        benchmark_parts.append(
            f"{prefix} {row['count']}-analyst target benchmark is {row['gap']:+.0%}"
            + temporal_note
        )
    for row in qualified_ratings[:3]:
        benchmark_parts.append(
            f"{row['source']} rates it {row['label']} ({row['count']} ratings)"
        )
    benchmark_note = (
        " External benchmarks: " + "; ".join(benchmark_parts) + "."
        if benchmark_parts else
        " A sufficiently covered external analyst benchmark was unavailable."
    )
    try:
        reverse_gap = float(reverse_dcf_gap)
    except (TypeError, ValueError, OverflowError):
        reverse_gap = float("nan")
    reverse_note = (
        " Terminal-only reverse DCF cross-check: with explicit-period cash flows "
        "held fixed, reproducing the current market price requires terminal free "
        f"cash flow {reverse_gap:+.0%} versus the model."
        if math.isfinite(reverse_gap) else ""
    )

    def finish(market_blocker=None):
        if market_blocker:
            add_blocker(market_blocker)
        if not blocking_reasons:
            return False, None
        # Once publication is blocked, make the independent market evidence
        # part of the explanation rather than a buried appendix.  It remains a
        # benchmark only and never enters intrinsic-value arithmetic.
        evidence_note = benchmark_note + reverse_note
        return blocked_result(evidence_note)

    names = {name.lower().replace("_", " ") for name in positive}
    has_market_comps = any("comp" in name for name in names)
    if model_gap is None:
        return finish()
    if abs(model_gap) < threshold:
        if not_corroborated:
            return finish(
                f"The intrinsic-value estimate is {model_gap:+.0%} from the market, "
                "while well-covered external analyst evidence points materially "
                "away from that directional conclusion."
                + " The external benchmark is not substituted for intrinsic value; "
                "publish the model cases, reconcile the assumption disagreement, "
                "and withhold the point rating in the meantime."
            )
        return finish()
    if not has_market_comps:
        # A large DCF-only call needs numeric external corroboration. A BUY or
        # SELL label supports direction, not the magnitude of a precise price
        # target. Qualified analyst targets can serve as the independent
        # benchmark the product deliberately collected, but only when their
        # direction and material magnitude agree and no other qualified source
        # contradicts the claim.
        if not has_target_corroboration or not_corroborated:
            target_explanation = (
                "no provider-dated current analyst target qualified to "
                "corroborate the direction and material magnitude of that gap"
                if qualified_targets and not has_provider_dated_current_target
                else (
                    "the available well-covered analyst-target evidence does not "
                    "corroborate both the direction and material magnitude of that gap"
                )
            )
            return finish(
                f"The DCF-only estimate is {model_gap:+.0%} from the market"
                + (" for a mega-cap" if is_mega_cap else "")
                + ", but no independent market-comps valuation qualified and "
                + target_explanation + "."
                + " The external benchmark is not substituted for intrinsic value."
                + " Publish the DCF cases as scenarios and withhold the point "
                "estimate and directional rating until the assumption gap is reconciled."
            )
        return finish()

    if not_corroborated:
        return finish(
            f"The model is {model_gap:+.0%} from the market for "
            f"{'a mega-cap' if is_mega_cap else 'the company'}. "
            "Well-covered independent evidence does not corroborate the model's "
            "exceptional gap."
            + " Publish the valuation methods as a range and "
            "withhold a directional rating."
        )
    return finish()


class _CtxTool(Tool):
    """Base for tools that share the run's AgentContext."""
    is_readonly = True
    repeatable = True

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx


class GetFinancialsTool(_CtxTool):
    name = "get_financials"
    description = (
        "Collect fundamental financial data for a company: income statement, balance "
        "sheet, cash flow, key metrics (market cap, P/E, margins), current price, and "
        "analyst estimates. Call this before build_model or write_report. Returns a "
        "summary of the company and its headline metrics."
    )
    parameters = {"type": "object", "properties": _TICKER_PARAM, "required": ["ticker"]}

    async def execute(self, ticker: str) -> str:
        from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
        state = self.ctx.ensure_state_for_ticker(ticker)
        state = await financial_data_agent(state)
        self.ctx.state = state
        if not state.is_financial_data_collected():
            return tool_error(
                f"Could not collect financial data for {ticker}.",
                ticker=ticker, detail=state.last_error,
            )
        km = state.financial_data.key_metrics if state.financial_data else {}
        basic = km.get("basic_info", {}) if isinstance(km, dict) else {}
        market = km.get("market_data", {}) if isinstance(km, dict) else {}
        return tool_ok(
            ticker=ticker,
            company_name=state.company_name,
            currency=basic.get("currency"),
            sector=basic.get("sector"),
            industry=basic.get("industry"),
            current_price=market.get("current_price"),
            market_cap=market.get("market_cap"),
            trailing_pe=market.get("trailing_pe"),
            note="Financial data collected and saved. You can now build_model or write_report.",
        )


class BuildModelTool(_CtxTool):
    name = "build_model"
    description = (
        "Build a 10-tab DCF valuation model (Excel) for a company and compute its "
        "fair value, current price, and upside/downside. Requires financial data — "
        "if not already collected, this will collect it first. Returns the valuation "
        "headline (fair value, upside) plus the path to the model file."
    )
    parameters = {"type": "object", "properties": _TICKER_PARAM, "required": ["ticker"]}
    is_readonly = False  # writes an Excel artifact

    async def execute(self, ticker: str) -> str:
        from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
        from src.agents.supervisor.task_agents.model_generation_agent import model_generation_agent
        state = self.ctx.ensure_state_for_ticker(ticker)
        if not state.is_financial_data_collected():
            state = await financial_data_agent(state)
            self.ctx.state = state
            if not state.is_financial_data_collected():
                return tool_error(f"Financial data needed for the model could not be collected for {ticker}.",
                                  ticker=ticker, detail=state.last_error)
        state = await model_generation_agent(state)
        self.ctx.state = state
        if not state.is_model_generated():
            return tool_error(f"Could not build the valuation model for {ticker}.",
                              ticker=ticker, detail=state.last_error)
        vm = state.financial_model.valuation_metrics if state.financial_model else {}
        fair_value = vm.get("fair_value") if isinstance(vm, dict) else None
        current_price = vm.get("current_price") if isinstance(vm, dict) else None
        upside = vm.get("upside_vs_market") if isinstance(vm, dict) else None
        method = vm.get("valuation_method") if isinstance(vm, dict) else None
        km = state.financial_data.key_metrics if state.financial_data else {}
        mcap = (km.get("market_data", {}) or {}).get("market_cap") if isinstance(km, dict) else None
        # The market cap is in the LISTING's currency, so the mega-cap rail
        # needs to know which one before comparing it to a threshold.
        mcap_ccy = (((km.get("basic_info", {}) or {}).get("listing_currency")
                     or (km.get("basic_info", {}) or {}).get("currency"))
                    if isinstance(km, dict) else None)
        warning = _valuation_warning(fair_value, upside, market_cap=mcap,
                                     method=method, currency=mcap_ccy)

        # How far apart are the methods? A blend is only meaningful when its
        # legs roughly agree; averaging contradictory methods produces a number
        # that looks precise and is not. Skipped for banks, where the DCF legs
        # are deliberately suppressed in favour of justified P/B x ROE.
        ratio, band, spread_note = (None, None, None)
        comps_in_blend = bool(
            isinstance(vm, dict)
            and vm.get("comps_included_in_blended_value", True)
        )
        if method != "justified_pb_roe" and isinstance(vm, dict):
            ratio, band, spread_note = valuation_dispersion({
                "perpetual DCF": vm.get("perpetual_price"),
                "exit multiple DCF": vm.get("exit_multiple_price"),
                "market comps": vm.get("comps_price") if comps_in_blend else None,
            })
        elif method == "justified_pb_roe" and isinstance(vm, dict):
            ratio = vm.get("dispersion_ratio")
            band = vm.get("dispersion_band")
            spread_note = vm.get("valuation_warning")
        # WHY the legs disagree, when they do. Terminal value is assumed twice:
        # once implicitly by the perpetuity formula, once explicitly as an exit
        # multiple. When those two disagree the model is internally
        # inconsistent, and naming that is far more useful to an analyst than
        # "the methods differ" — for META the perpetual method implied a 5.1x
        # exit EV/EBITDA while the exit leg assumed 11.2x, which is the whole
        # 44% gap between the legs.
        asmp = state.financial_model.assumptions if state.financial_model else {}
        tv_note, tv_recon = None, None
        if isinstance(asmp, dict) and method != "justified_pb_roe":
            from src.agents.fm.terminal_value import reconcile as _reconcile_tv
            tv_recon = _reconcile_tv(
                fcf_terminal=asmp.get("fcf_terminal"),
                ebitda_terminal=asmp.get("ebitda_terminal"),
                wacc=asmp.get("wacc"),
                terminal_growth=asmp.get("terminal_growth"),
                exit_multiple=asmp.get("exit_multiple"),
                # The perpetuity leg is capped at the currency's risk-free
                # rate; the exit leg is judged against the same ceiling.
                growth_cap=asmp.get("risk_free_rate"),
            )
            # Reported regardless of the spread band. An exit multiple implying
            # growth above nominal GDP is indefensible even when the two legs
            # happen to land close together — the agreement would be luck.
            tv_note = tv_recon.get("note")

        # Ordered strongest-first. A contradiction between methods explains the
        # suspect headline, not the other way round, so it must lead — followed
        # by the mechanical reason, then any generic rail.
        warning = " ".join(p for p in (spread_note, tv_note, warning) if p) or None

        # WITHHOLD the point estimate when the methods contradict each other.
        #
        # Instructing the model not to quote a number while still handing it
        # that number is a weak control: it is the most quotable thing in the
        # payload, it is what the user asked for, and one summarisation step
        # later the caveat is gone and "$109.81" is on screen. So when the legs
        # disagree past the unreliable threshold, fair_value and the upside are
        # replaced by the RANGE they actually support. Nothing is hidden — the
        # legs are published individually right below — but there is no longer a
        # single misleadingly precise figure to lift out of context.
        if method == "justified_pb_roe" and isinstance(vm, dict):
            raw_legs = {
                "justified_pb_roe": vm.get("bank_intrinsic_fair_value"),
                "forward_consensus_roe_scenario": vm.get(
                    "bank_forward_consensus_fair_value"
                ),
                "roe_adjusted_peer_pb": vm.get("bank_peer_fair_value"),
            }
        else:
            raw_legs = {
                "perpetual_dcf": (vm.get("perpetual_price") if isinstance(vm, dict) else None),
                "exit_multiple_dcf": (vm.get("exit_multiple_price") if isinstance(vm, dict) else None),
                "market_comps": (
                    vm.get("comps_price") if isinstance(vm, dict) and comps_in_blend else None
                ),
            }
        legs_pub = {
            k: v for k, v in raw_legs.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
        }
        positive_legs = [v for v in legs_pub.values() if v > 0]
        withheld = bool(
            (isinstance(vm, dict) and vm.get("point_estimate_withheld"))
            or (band in {"wide", "unreliable"} and len(positive_legs) >= 2)
        )
        withheld_reason = (
            vm.get("publication_withheld_reason") if isinstance(vm, dict) else None
        ) or (
            "The valuation methods disagree by more than 2.5x. No single fair "
            "value is defensible, so the range is reported instead."
        )
        withheld_payload = {}
        if withheld:
            fair_value_out, upside_out = None, None
            withheld_payload = {
                "fair_value_withheld": True,
                "fair_value_withheld_reason": withheld_reason,
            }
            if positive_legs:
                from src.summary_evidence import supported_valuation_span
                support = supported_valuation_span(positive_legs)
                withheld_payload["valuation_support_shape"] = support["shape"]
                if support["shape"] == "single_estimate":
                    withheld_payload["supported_valuation_estimate"] = round(
                        support["low"], 2
                    )
                else:
                    withheld_payload.update({
                        "fair_value_range_low": round(support["low"], 2),
                        "fair_value_range_high": round(support["high"], 2),
                    })
        else:
            fair_value_out, upside_out = fair_value, upside

        if method == "justified_pb_roe":
            note = ("Financial-sector company: fair value computed via justified "
                    "P/B x ROE on book value per share; the standard FCF DCF is "
                    "suppressed (not meaningful for banks). Present the fair value "
                    "with this method note.")
        else:
            note = "DCF model built and saved (downloadable)."

        raw_financials = state.financial_data.raw_data if state.financial_data else {}
        raw_financials = raw_financials if isinstance(raw_financials, dict) else {}
        external_expectations = raw_financials.get("external_expectations") or {}
        peer_cross_check = ((raw_financials.get("industry_data") or {}).get("peer_comps") or {})
        reverse_dcf = {
            key: vm.get(key) for key in (
                "market_implied_terminal_fcf",
                "market_implied_fcf_vs_model",
                "market_implied_fcf_path_vs_model",
                "analyst_target_implied_terminal_fcf",
                "analyst_target_implied_fcf_vs_model",
                "analyst_target_implied_fcf_path_vs_model",
                "market_implied_wacc",
                "market_implied_wacc_vs_model",
                "analyst_target_implied_wacc",
                "analyst_target_implied_wacc_vs_model",
                "market_implied_terminal_growth",
                "market_implied_terminal_growth_vs_model",
                "analyst_target_implied_terminal_growth",
                "analyst_target_implied_terminal_growth_vs_model",
            )
            if isinstance(vm, dict)
            and isinstance(vm.get(key), (int, float))
            and not isinstance(vm.get(key), bool)
            and math.isfinite(float(vm.get(key)))
        }
        try:
            from src.summary_evidence import external_benchmark, render_external_benchmark
            benchmark_reconciliation = render_external_benchmark(external_benchmark(
                raw_financials,
                vm.get("model_revenue_forecast") or (),
                revenue_growth_source=(
                    state.financial_model.assumptions.get("revenue_growth_source")
                    if state.financial_model and isinstance(
                        state.financial_model.assumptions, dict) else None
                ),
                valuation_metrics=vm,
            ))
        except Exception:
            benchmark_reconciliation = None

        return tool_ok(
            ticker=ticker,
            model_type=state.financial_model.model_type if state.financial_model else None,
            currency=_listing_currency(state),
            **_listing_price_note(state),
            fair_value=fair_value_out,
            current_price=current_price,
            upside_vs_market=upside_out,
            excel_path=state.financial_model.excel_path if state.financial_model else None,
            # What the methods actually support when they refuse to agree.
            **withheld_payload,
            # Publish the legs and the confidence band so the answer can show a
            # football field instead of a false point estimate.
            **({"valuation_legs": legs_pub} if legs_pub else {}),
            **({"street_expectations": external_expectations}
               if external_expectations else {}),
            **({"peer_cross_check": peer_cross_check} if peer_cross_check else {}),
            **({"reverse_dcf": reverse_dcf} if reverse_dcf else {}),
            **({"benchmark_reconciliation": benchmark_reconciliation}
               if benchmark_reconciliation else {}),
            **({"reinvestment_sensitivity": vm.get("reinvestment_sensitivity")}
               if isinstance(vm, dict)
               and isinstance(vm.get("reinvestment_sensitivity"), dict) else {}),
            **({"valuation_spread_ratio": round(ratio, 2)} if ratio else {}),
            **({"valuation_confidence": band} if band else {}),
            **({"valuation_method": method} if method else {}),
            **({"dcf_fair_value": vm.get("dcf_fair_value")}
               if isinstance(vm, dict) and vm.get("dcf_fair_value") is not None
               and method and method != "justified_pb_roe" else {}),
            **({"data_quality_warning": warning} if warning else {}),
            note=(note + " Treat Street targets/ratings as a decision-relevant external "
                  "benchmark, not intrinsic value. When benchmark_reconciliation is "
                  "present, surface its dated coverage, conflict/corroboration result, "
                  "and whole-path reverse DCF; do not reduce it to a generic caveat. "
                  "Never call a blended model value a DCF value; DCF means only the "
                  "perpetual/exit DCF midpoint or range. Reinvestment sensitivity is "
                  "an audit scenario only: surface it when material, but never count "
                  "it as an independent valuation vote or forward-capex guidance."),
        )


class AnalyzeNewsTool(_CtxTool):
    name = "analyze_news"
    description = (
        "Analyze recent news for a company and extract investment insights: growth "
        "catalysts, risks, and, only when fresh source-dated coverage is sufficient, "
        "an overall news sentiment. Scrapes and screens news articles "
        "(runs in parallel). Use for 'what's the latest on X', 'why did X move', "
        "sentiment, catalysts, or risks. Always returns freshness metadata; stale or "
        "limited coverage never returns a directional sentiment."
    )
    parameters = {"type": "object", "properties": _TICKER_PARAM, "required": ["ticker"]}

    async def execute(self, ticker: str) -> str:
        from src.agents.supervisor.task_agents.news_analysis_agent import news_analysis_agent
        state = self.ctx.ensure_state_for_ticker(ticker)
        state = await news_analysis_agent(state)
        self.ctx.state = state
        if not state.is_news_analyzed() or not state.news_analysis:
            return tool_error(f"Could not analyze news for {ticker}.",
                              ticker=ticker, detail=state.last_error)
        na = state.news_analysis
        news_payload = _bounded_news_payload(
            na, sentiment_key="overall_sentiment", freshness_key="freshness"
        )
        fresh = news_payload["freshness"].get("status") == "fresh"
        return tool_ok(
            ticker=ticker,
            articles_analyzed=na.articles_count,
            top_catalysts=(na.catalysts or [])[:3],
            top_risks=(na.risks or [])[:3],
            **news_payload,
            note=(
                "Fresh news analyzed; catalysts, risks, and news sentiment extracted."
                if fresh else
                "Fresh source-dated coverage is insufficient. Catalysts and risks are "
                "returned with their evidence, but no directional news sentiment is published."
            ),
        )


class WriteReportTool(_CtxTool):
    name = "write_report"
    description = (
        "Generate a full professional analyst research report (markdown) for a "
        "company, synthesizing financials, valuation, and news into an investment "
        "recommendation. Requires financial data, a model, and news analysis — this "
        "will run whichever are missing first. Use for 'analyze X comprehensively', "
        "'full report', or 'should I buy X'. If the user asked for the output in a "
        "specific language (e.g. Chinese, Japanese, Spanish), pass it as "
        "output_language so the report narrative is written in that language. "
        "Returns the report path and length."
    )
    parameters = {
        "type": "object",
        "properties": {
            **_TICKER_PARAM,
            "output_language": {
                "type": "string",
                "description": (
                    "Optional. The language to write the report narrative in, as a "
                    "plain name (e.g. 'Chinese', '日本語', 'Spanish'). Only set this "
                    "if the user asked for a non-English report. Omit for English."
                ),
            },
            "brief": {
                "type": "string",
                "description": (
                    "Optional. The user's own framing for the report, passed through "
                    "close to verbatim: the persona they asked you to adopt, a title "
                    "they specified, the sections or areas they want covered, and what "
                    "to emphasise. Set this whenever the user described the report they "
                    "want rather than just naming a company — e.g. 'act as a sell-side "
                    "analyst', 'cover these 10 areas', 'title it X'. It steers structure "
                    "and tone ONLY; never put a requested rating or price target here, "
                    "as those are derived from the model and cannot be requested."
                ),
            },
        },
        "required": ["ticker"],
    }
    is_readonly = False

    async def execute(self, ticker: str, output_language: str = "", brief: str = "") -> str:
        from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
        from src.agents.supervisor.task_agents.model_generation_agent import model_generation_agent
        from src.agents.supervisor.task_agents.news_analysis_agent import news_analysis_agent
        from src.agents.supervisor.task_agents.report_generator_agent import report_generator_agent

        import asyncio
        import copy as _copy
        state = self.ctx.ensure_state_for_ticker(ticker)
        if output_language and output_language.strip():
            state.output_language = output_language.strip()
        # The user's framing for the report. Falls back to their original
        # message when the agent did not pass one explicitly: a detailed brief
        # is far more often stated once up front than restated as a tool
        # argument, and losing it is what produced a stock-template report for
        # a request that specified a title and ten sections.
        _brief = (brief or "").strip() or (self.ctx.user_prompt or "").strip()
        if _brief:
            state.report_brief = _brief
        if not state.is_financial_data_collected():
            state = await financial_data_agent(state)
            self.ctx.state = state

        # Once we have financial data, model_generation and news_analysis are
        # independent — run them CONCURRENTLY (Phase-4 pattern): news is async, the
        # model is blocking so it runs on a shallow state copy in a thread, then its
        # output is merged back. Falls back to sequential on any error.
        if state.is_financial_data_collected() and (not state.is_model_generated() or not state.is_news_analyzed()):
            try:
                model_state = _copy.copy(state)
                cost_before = state.total_llm_cost

                async def _run_model():
                    if state.is_model_generated():
                        return None
                    def _drive():
                        return asyncio.run(model_generation_agent(model_state))
                    return await asyncio.to_thread(_drive)

                async def _run_news():
                    if state.is_news_analyzed():
                        return state
                    return await news_analysis_agent(state)

                model_res, news_res = await asyncio.gather(_run_model(), _run_news(), return_exceptions=True)
                # merge model output
                from src.agents.supervisor.state import FinancialState as _FS
                if isinstance(model_res, _FS):
                    state.financial_model = model_res.financial_model
                    state.total_llm_cost += max(0.0, model_res.total_llm_cost - cost_before)
                self.ctx.state = state
            except Exception:
                # Sequential fallback.
                if not state.is_model_generated():
                    state = await model_generation_agent(state); self.ctx.state = state
                if not state.is_news_analyzed():
                    state = await news_analysis_agent(state); self.ctx.state = state

        if not (state.is_financial_data_collected() and state.is_model_generated() and state.is_news_analyzed()):
            return tool_error(f"Could not gather all prerequisites for the report on {ticker}.",
                              ticker=ticker, detail=state.last_error)
        state = await report_generator_agent(state)
        self.ctx.state = state
        if not state.is_report_generated() or not state.report:
            return tool_error(f"Could not generate the report for {ticker}.",
                              ticker=ticker, detail=state.last_error)
        vm = state.financial_model.valuation_metrics if state.financial_model else {}
        na = state.news_analysis
        fair_value = vm.get("fair_value") if isinstance(vm, dict) else None
        upside = vm.get("upside_vs_market") if isinstance(vm, dict) else None
        method = vm.get("valuation_method") if isinstance(vm, dict) else None
        # If a balance-sheet (P/B x ROE) valuation replaced the DCF in state, the
        # REPORT was still built from the workbook's DCF. The chat then quoted a
        # fair value the document did not contain (PayPal: $61.01 vs $87.11).
        # Quote what the report shows; carry the other number alongside it.
        # The report now carries the balance-sheet valuation itself (see
        # apply_valuation_override), so for a bank the chat quotes that same
        # number. The suppressed DCF is offered as a cross-check only when it
        # actually produced a value — for banks it is 0.00, and an earlier
        # version of this block would have told the user "fair value $0.00".
        # An industrial FCF DCF is structurally inapplicable to a bank. Keep
        # it in internal artifacts for audit, but never hand it to the answer
        # model as an apparent alternative fair value.
        km = state.financial_data.key_metrics if state.financial_data else {}
        mcap = (km.get("market_data", {}) or {}).get("market_cap") if isinstance(km, dict) else None
        # The market cap is in the LISTING's currency, so the mega-cap rail
        # needs to know which one before comparing it to a threshold.
        mcap_ccy = (((km.get("basic_info", {}) or {}).get("listing_currency")
                     or (km.get("basic_info", {}) or {}).get("currency"))
                    if isinstance(km, dict) else None)
        warning = _valuation_warning(fair_value, upside, market_cap=mcap,
                                     method=method, currency=mcap_ccy)

        # The dispersion check runs in model_generation_agent and lands here as
        # `valuation_warning`. Surfacing it matters most on THIS path: the
        # report route is what a user gets when they ask for a full analysis,
        # and it previously reported a blended fair value with no indication of
        # how far the methods diverged. A real ASTS request came back as "DCF
        # fair value from the model: $31.78" when both DCF legs had returned
        # negative per-share values and $31.78 was the market-comps leg alone.
        spread_note = vm.get("valuation_warning") if isinstance(vm, dict) else None
        band = vm.get("dispersion_band") if isinstance(vm, dict) else None
        # Dispersion leads: it explains the headline rather than the reverse.
        warning = " ".join(p for p in (spread_note, warning) if p) or None

        # Match the report's publication boundary. The workbook retains the
        # arithmetic midpoint for audit, but when the methods disagree by more
        # than 2.5x neither the report nor the chat response may elevate it to a
        # fair value. Publish the football-field range instead.
        if method == "justified_pb_roe" and isinstance(vm, dict):
            raw_legs = {
                "justified_pb_roe": vm.get("bank_intrinsic_fair_value"),
                "forward_consensus_roe_scenario": vm.get(
                    "bank_forward_consensus_fair_value"
                ),
                "roe_adjusted_peer_pb": vm.get("bank_peer_fair_value"),
            }
        else:
            raw_legs = {
                "perpetual_dcf": vm.get("perpetual_price") if isinstance(vm, dict) else None,
                "exit_multiple_dcf": vm.get("exit_multiple_price") if isinstance(vm, dict) else None,
                "market_comps": (
                    vm.get("comps_price") if isinstance(vm, dict)
                    and vm.get("comps_included_in_blended_value", True) else None
                ),
            }
        legs_pub = {
            key: value for key, value in raw_legs.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        }
        positive_legs = [value for value in legs_pub.values() if value > 0]
        withheld = bool(
            (isinstance(vm, dict) and vm.get("point_estimate_withheld"))
            or (band in {"wide", "unreliable"} and len(positive_legs) >= 2)
        )
        withheld_reason = (
            vm.get("publication_withheld_reason") if isinstance(vm, dict) else None
        ) or (
            "The valuation methods disagree by more than 2.5x. The report "
            "publishes the supported range and no directional rating or target."
        )
        if withheld:
            fair_value = None
            upside = None
            range_fields = {
                "fair_value_withheld": True,
                "fair_value_withheld_reason": withheld_reason,
            }
            if positive_legs:
                from src.summary_evidence import supported_valuation_span
                support = supported_valuation_span(positive_legs)
                range_fields["valuation_support_shape"] = support["shape"]
                if support["shape"] == "single_estimate":
                    range_fields["supported_valuation_estimate"] = round(
                        support["low"], 2
                    )
                else:
                    range_fields.update({
                        "fair_value_range_low": round(support["low"], 2),
                        "fair_value_range_high": round(support["high"], 2),
                    })
        else:
            range_fields = {}

        bounded_headline = _bounded_report_headline(
            state.report.content, point_estimate_withheld=withheld
        )

        raw_financials = state.financial_data.raw_data if state.financial_data else {}
        raw_financials = raw_financials if isinstance(raw_financials, dict) else {}
        external_expectations = raw_financials.get("external_expectations") or {}
        peer_cross_check = ((raw_financials.get("industry_data") or {}).get("peer_comps") or {})
        reverse_dcf = {
            key: vm.get(key) for key in (
                "market_implied_terminal_fcf",
                "market_implied_fcf_vs_model",
                "market_implied_fcf_path_vs_model",
                "analyst_target_implied_terminal_fcf",
                "analyst_target_implied_fcf_vs_model",
                "analyst_target_implied_fcf_path_vs_model",
                "market_implied_wacc",
                "market_implied_wacc_vs_model",
                "analyst_target_implied_wacc",
                "analyst_target_implied_wacc_vs_model",
                "market_implied_terminal_growth",
                "market_implied_terminal_growth_vs_model",
                "analyst_target_implied_terminal_growth",
                "analyst_target_implied_terminal_growth_vs_model",
            )
            if isinstance(vm, dict)
            and isinstance(vm.get(key), (int, float))
            and not isinstance(vm.get(key), bool)
            and math.isfinite(float(vm.get(key)))
        }
        try:
            from src.summary_evidence import external_benchmark, render_external_benchmark
            benchmark_reconciliation = render_external_benchmark(external_benchmark(
                raw_financials,
                vm.get("model_revenue_forecast") or (),
                revenue_growth_source=(
                    state.financial_model.assumptions.get("revenue_growth_source")
                    if state.financial_model and isinstance(
                        state.financial_model.assumptions, dict) else None
                ),
                valuation_metrics=vm,
            ))
        except Exception:
            benchmark_reconciliation = None
        news_payload = _bounded_news_payload(
            na, sentiment_key="news_sentiment", freshness_key="news_freshness"
        )

        return tool_ok(
            ticker=ticker,
            report_path=state.report.report_path,
            content_length=len(state.report.content) if state.report.content else 0,
            currency=_listing_currency(state),
            **_listing_price_note(state),
            fair_value=fair_value,
            upside_vs_market=upside,
            **range_fields,
            **({"valuation_legs": legs_pub} if legs_pub else {}),
            **({"street_expectations": external_expectations}
               if external_expectations else {}),
            **({"peer_cross_check": peer_cross_check} if peer_cross_check else {}),
            **({"reverse_dcf": reverse_dcf} if reverse_dcf else {}),
            **({"benchmark_reconciliation": benchmark_reconciliation}
               if benchmark_reconciliation else {}),
            **news_payload,
            # The rating the report published, so the answer cannot contradict
            # the document the user downloads.
            **bounded_headline,
            **({"valuation_method": method} if method else {}),
            **({"valuation_confidence": band} if band else {}),
            **({"data_quality_warning": warning} if warning else {}),
            note=("Full report generated (downloadable). Summarize its findings for "
                  "the user. When `fair_value_withheld` is true, state the supplied "
                  "`fair_value_withheld_reason`; do not substitute dispersion as the "
                  "reason and do not turn range endpoints into scenario targets. "
                  "When benchmark_reconciliation is present, surface its dated human-"
                  "analyst coverage, conflict/corroboration conclusion, and whole-path "
                  "reverse DCF instead of merely calling the assumptions suspect. "
                  "Never call `fair_value`, `model_blended_value`, or a blend gap a "
                  "DCF value: DCF means only the midpoint/range of perpetual_dcf and "
                  "exit_multiple_dcf. Distinguish `news_sentiment` from Street analyst "
                  "recommendations. When `news_sentiment` is absent, fresh coverage was "
                  "insufficient: do not infer a directional sentiment from empty or "
                  "limited evidence. Summarize the supplied Street expectations and "
                  "their revenue/EPS benchmark whenever present. "
                  "If `rating` is present, state THAT rating — it is the "
                  "one printed in the report the user can open, and it is computed "
                  "from the model rather than judged. Do not substitute your own "
                  "call. Note that `upside_vs_market` is measured against the DCF "
                  "fair value while `price_target_expected_return_pct` belongs to "
                  "the 12-month target; never quote one with the other's figure."),
        )


class ReadReportTool(_CtxTool):
    name = "read_report"
    description = (
        "Read the full markdown of a report ALREADY generated for a company earlier "
        "in this conversation. Use this to answer follow-ups like 'summarize the "
        "report', 'break out the bull/base/bear cases', 'what were the key risks', or "
        "'explain the valuation' WITHOUT re-running write_report. Always prefer this "
        "over regenerating when a report for the ticker already exists. Returns the "
        "report text (or an error if none exists yet)."
    )
    parameters = {"type": "object", "properties": _TICKER_PARAM, "required": ["ticker"]}
    is_readonly = True

    async def execute(self, ticker: str) -> str:
        import asyncio
        ticker = (ticker or "").strip().upper()
        if not ticker or ticker in ("CHAT", "PENDING", "UNKNOWN", "NONE", "N/A"):
            return tool_error("read_report needs a real ticker.", ticker=ticker)

        def _read():
            from path_utils import get_latest_analysis_path
            base = get_latest_analysis_path(self.ctx.email, ticker)
            if not base:
                return None
            candidate = base / f"{ticker}_Professional_Analysis_Report.md"
            if candidate.exists():
                return base, candidate.read_text(encoding="utf-8", errors="ignore")
            # Fallback: any *Report*.md in the folder (filename conventions may vary).
            for p in sorted(base.glob("*Report*.md")) + sorted(base.glob("*report*.md")):
                if p.exists():
                    return base, p.read_text(encoding="utf-8", errors="ignore")
            return None

        try:
            loaded = await asyncio.to_thread(_read)
        except Exception as e:
            return tool_error(f"Could not read the report for {ticker}: {e}", ticker=ticker)
        if not loaded:
            return tool_error(
                f"No existing report found for {ticker}. Generate one with write_report first.",
                ticker=ticker,
            )
        base, content = loaded
        state = _rehydrate_report_guard_state(base, ticker, content)
        self.ctx.state = state
        self.ctx.ticker = ticker
        basic = getattr(state.financial_data, "key_metrics", {}).get("basic_info", {})
        self.ctx.company_name = basic.get("long_name") or basic.get("short_name") or ticker

        metrics = state.financial_model.valuation_metrics
        supported = []
        try:
            from src.summary_evidence import supported_valuation_values
            supported = supported_valuation_values(metrics)
        except Exception:
            supported = []
        withheld = bool(metrics.get("point_estimate_withheld"))
        headline = _bounded_report_headline(
            content, point_estimate_withheld=withheld
        )
        publication = {
            "rating": headline.get("rating"),
            "point_estimate_withheld": withheld,
            "valuation_confidence": metrics.get("valuation_confidence"),
        }
        if metrics.get("point_estimate_withheld"):
            publication["withheld_reason"] = metrics.get(
                "publication_withheld_reason")
            if supported:
                from src.summary_evidence import supported_valuation_span
                support = supported_valuation_span(supported)
                publication["valuation_support_shape"] = support["shape"]
                if support["shape"] == "single_estimate":
                    publication["supported_valuation_estimate"] = support["low"]
                else:
                    publication.update({
                        "supported_range_low": support["low"],
                        "supported_range_high": support["high"],
                    })
        else:
            publication.update({
                "fair_value": metrics.get("fair_value"),
                "upside_vs_market": metrics.get("upside_vs_market"),
            })
        # Cap the payload so a huge report doesn't blow the context; the model gets
        # plenty to summarize / extract cases from.
        MAX = 24000
        truncated = len(content) > MAX
        return tool_ok(
            ticker=ticker,
            publication=publication,
            news_freshness=getattr(state.news_analysis, "freshness", {}) or {
                "status": "unavailable"
            },
            **headline,
            report_markdown=content[:MAX],
            truncated=truncated,
            note=("Existing report and its machine publication boundary loaded. "
                  "Answer the user's follow-up from THIS content; do not regenerate. "
                  "The `publication` object controls any rating or valuation claim. "
                  "Audit-only numbers in the markdown never override it."),
        )


class CompareTickersTool(_CtxTool):
    name = "compare_tickers"
    description = (
        "Quickly compare 2-5 companies side by side on the fundamentals that matter "
        "for relative value: price, market cap, P/E, margins, growth, and sector. Use "
        "for 'compare NVDA with its peers', 'NVDA vs AMD vs AVGO', or peer/relative-value "
        "questions. This is LIGHTWEIGHT (no full DCF per name) — prefer it over running "
        "write_report on each peer. Returns a metrics table for all tickers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "tickers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 ticker symbols to compare, e.g. ['NVDA','AMD','AVGO'].",
                "minItems": 2,
                "maxItems": 8,
            }
        },
        "required": ["tickers"],
    }
    is_readonly = True

    async def execute(self, tickers) -> str:
        import asyncio
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
        tickers = [t.strip().upper() for t in (tickers or []) if t and t.strip()][:8]
        if len(tickers) < 2:
            return tool_error("compare_tickers needs at least 2 tickers.", tickers=tickers)

        def _one(tkr: str) -> dict:
            try:
                import yfinance as yf
                info = yf.Ticker(tkr).info or {}
            except Exception as e:
                return {"ticker": tkr, "error": f"lookup failed: {e}"}
            quote_type = str(info.get("quoteType") or "").strip().upper()
            if quote_type and quote_type != "EQUITY":
                return {
                    "ticker": tkr,
                    "error": (f"{quote_type} is not an operating company; use the "
                              "asset-specific research tool"),
                }
            if not info.get("regularMarketPrice") and not info.get("currentPrice"):
                return {"ticker": tkr, "error": "no data (unknown ticker?)"}

            def _pct(x):
                return round(x * 100, 1) if isinstance(x, (int, float)) else None
            return {
                "ticker": tkr,
                "company": info.get("longName") or info.get("shortName"),
                "sector": info.get("sector"),
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap": info.get("marketCap"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "gross_margin_pct": _pct(info.get("grossMargins")),
                "operating_margin_pct": _pct(info.get("operatingMargins")),
                "revenue_growth_pct": _pct(info.get("revenueGrowth")),
                "profit_margin_pct": _pct(info.get("profitMargins")),
            }

        try:
            rows = await asyncio.gather(*[asyncio.to_thread(_one, t) for t in tickers])
        except Exception as e:
            return tool_error(f"Comparison failed: {e}", tickers=tickers)
        return tool_ok(
            tickers=tickers,
            comparison=list(rows),
            note="Lightweight peer comparison (yfinance fundamentals). Synthesize the relative-value read for the user; no full model was run.",
        )


def build_analysis_tools(ctx: AgentContext):
    """Instantiate the wrapped-agent tools + memory/comparison tools bound to one run context."""
    return [
        GetFinancialsTool(ctx),
        BuildModelTool(ctx),
        AnalyzeNewsTool(ctx),
        WriteReportTool(ctx),
        ReadReportTool(ctx),
        CompareTickersTool(ctx),
    ]
