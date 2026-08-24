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


def _valuation_warning(fair_value, upside, market_cap=None, method=None):
    """
    Sanity rail on valuation output. An FCF-projection DCF on a deeply
    FCF-negative or freshly listed company produces mathematically valid
    nonsense (negative fair value, -100% "upside") — e.g. SpaceX right after
    its IPO with -$14B FCF. And on mega-caps, a large implied mispricing is
    far more often a broken assumption than a broken market (a GOOGL DCF
    shipped -55% vs price to a real user). Flag both so the agent leads with
    the caveat instead of the number.

    `upside` is a FRACTION (e.g. -0.55 for -55%).
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
    if mcap is not None and mcap >= 200e9 and up_pct is not None and abs(up_pct) > 40:
        return (f"SUSPECT VALUATION: the DCF implies {up_pct:+.0f}% vs the market "
                f"price for a ~${mcap/1e9:.0f}B mega-cap. Markets rarely misprice "
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

    spread_txt = ", ".join(f"{k.replace('_', ' ')} ${v:,.2f}" for k, v in sorted(usable.items(), key=lambda kv: kv[1]))

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
        warning = _valuation_warning(fair_value, upside, market_cap=mcap, method=method)

        # How far apart are the methods? A blend is only meaningful when its
        # legs roughly agree; averaging contradictory methods produces a number
        # that looks precise and is not. Skipped for banks, where the DCF legs
        # are deliberately suppressed in favour of justified P/B x ROE.
        ratio, band, spread_note = (None, None, None)
        if method != "justified_pb_roe" and isinstance(vm, dict):
            ratio, band, spread_note = valuation_dispersion({
                "perpetual DCF": vm.get("perpetual_price"),
                "exit multiple DCF": vm.get("exit_multiple_price"),
                "market comps": vm.get("comps_price"),
            })
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
        legs_pub = {
            k: v for k, v in {
                "perpetual_dcf": (vm.get("perpetual_price") if isinstance(vm, dict) else None),
                "exit_multiple_dcf": (vm.get("exit_multiple_price") if isinstance(vm, dict) else None),
                "market_comps": (vm.get("comps_price") if isinstance(vm, dict) else None),
            }.items() if isinstance(v, (int, float))
        }
        positive_legs = [v for v in legs_pub.values() if v > 0]
        withheld = False
        if band == "unreliable" and len(positive_legs) >= 2:
            withheld = True
            fair_value_out, upside_out = None, None
            low, high = min(positive_legs), max(positive_legs)
        else:
            fair_value_out, upside_out = fair_value, upside
            low = high = None

        if method == "justified_pb_roe":
            note = ("Financial-sector company: fair value computed via justified "
                    "P/B x ROE on book value per share; the standard FCF DCF is "
                    "suppressed (not meaningful for banks). Present the fair value "
                    "with this method note.")
        else:
            note = "DCF model built and saved (downloadable)."

        return tool_ok(
            ticker=ticker,
            model_type=state.financial_model.model_type if state.financial_model else None,
            currency=_listing_currency(state),
            fair_value=fair_value_out,
            current_price=current_price,
            upside_vs_market=upside_out,
            excel_path=state.financial_model.excel_path if state.financial_model else None,
            # What the methods actually support when they refuse to agree.
            **({"fair_value_range_low": round(low, 2),
                "fair_value_range_high": round(high, 2),
                "fair_value_withheld": True,
                "fair_value_withheld_reason":
                    "The valuation methods disagree by more than 2.5x. No single "
                    "fair value is defensible, so the range is reported instead. "
                    "Quote the range, never a midpoint."}
               if withheld else {}),
            # Publish the legs and the confidence band so the answer can show a
            # football field instead of a false point estimate.
            **({"valuation_legs": legs_pub} if legs_pub else {}),
            **({"valuation_spread_ratio": round(ratio, 2)} if ratio else {}),
            **({"valuation_confidence": band} if band else {}),
            **({"valuation_method": method} if method else {}),
            **({"dcf_fair_value": vm.get("dcf_fair_value")}
               if isinstance(vm, dict) and vm.get("dcf_fair_value") is not None and method else {}),
            **({"data_quality_warning": warning} if warning else {}),
            note=note,
        )


class AnalyzeNewsTool(_CtxTool):
    name = "analyze_news"
    description = (
        "Analyze recent news for a company and extract investment insights: growth "
        "catalysts, risks, and overall sentiment. Scrapes and screens news articles "
        "(runs in parallel). Use for 'what's the latest on X', 'why did X move', "
        "sentiment, catalysts, or risks. Returns sentiment plus the top catalysts/risks."
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
        return tool_ok(
            ticker=ticker,
            overall_sentiment=na.overall_sentiment,
            articles_analyzed=na.articles_count,
            top_catalysts=(na.catalysts or [])[:3],
            top_risks=(na.risks or [])[:3],
            note="News analyzed. Catalysts and risks extracted.",
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
        km = state.financial_data.key_metrics if state.financial_data else {}
        mcap = (km.get("market_data", {}) or {}).get("market_cap") if isinstance(km, dict) else None
        warning = _valuation_warning(fair_value, upside, market_cap=mcap, method=method)

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

        return tool_ok(
            ticker=ticker,
            report_path=state.report.report_path,
            content_length=len(state.report.content) if state.report.content else 0,
            currency=_listing_currency(state),
            fair_value=fair_value,
            upside_vs_market=upside,
            overall_sentiment=na.overall_sentiment if na else None,
            **({"valuation_method": method} if method else {}),
            **({"valuation_confidence": band} if band else {}),
            **({"data_quality_warning": warning} if warning else {}),
            note="Full report generated (downloadable). Summarize its findings for the user.",
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

        def _read() -> Optional[str]:
            from path_utils import get_latest_analysis_path
            base = get_latest_analysis_path(self.ctx.email, ticker)
            if not base:
                return None
            candidate = base / f"{ticker}_Professional_Analysis_Report.md"
            if candidate.exists():
                return candidate.read_text(encoding="utf-8", errors="ignore")
            # Fallback: any *Report*.md in the folder (filename conventions may vary).
            for p in sorted(base.glob("*Report*.md")) + sorted(base.glob("*report*.md")):
                if p.exists():
                    return p.read_text(encoding="utf-8", errors="ignore")
            return None

        try:
            content = await asyncio.to_thread(_read)
        except Exception as e:
            return tool_error(f"Could not read the report for {ticker}: {e}", ticker=ticker)
        if not content:
            return tool_error(
                f"No existing report found for {ticker}. Generate one with write_report first.",
                ticker=ticker,
            )
        # Cap the payload so a huge report doesn't blow the context; the model gets
        # plenty to summarize / extract cases from.
        MAX = 24000
        truncated = len(content) > MAX
        return tool_ok(
            ticker=ticker,
            report_markdown=content[:MAX],
            truncated=truncated,
            note="Existing report loaded. Answer the user's follow-up from THIS content; do not regenerate.",
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
