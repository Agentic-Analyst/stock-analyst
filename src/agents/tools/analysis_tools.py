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
        self._ticker_announced = False

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

        # If we already have state for this ticker, reuse it (chain continuity).
        if self.state is not None and self.ticker == ticker:
            return self.state

        # Resolve company name (best-effort).
        if not company_name:
            try:
                import yfinance as yf
                company_name = yf.Ticker(ticker).info.get("longName") or ticker
            except Exception:
                company_name = ticker

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


def _valuation_warning(fair_value, upside):
    """
    Sanity rail on DCF output. An FCF-projection DCF on a deeply FCF-negative
    or freshly listed company produces mathematically valid nonsense (negative
    fair value, -100% "upside") — e.g. SpaceX right after its IPO with -$14B
    FCF. Flag it so the agent leads with the caveat instead of the number.
    """
    try:
        fv = float(fair_value) if fair_value is not None else None
        up = float(upside) if upside is not None else None
    except (TypeError, ValueError):
        return None
    if fv is not None and fv <= 0:
        return ("UNRELIABLE VALUATION: the DCF produced a non-positive fair value, "
                "which means the company's free cash flow profile (heavy investment / "
                "negative FCF, common for growth or recently listed names) breaks this "
                "method. Do NOT present this number as the company's worth. Say the DCF "
                "is not meaningful for this profile and analyze via growth, unit "
                "economics, and market pricing instead.")
    if up is not None and up <= -70:
        return ("SUSPECT VALUATION: the DCF implies more than 70% downside vs the "
                "market price. That can be real, but with negative or thin FCF history "
                "it usually means the method fits this company poorly. Present it with "
                "that caveat, not as a headline conclusion.")
    return None


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
        warning = _valuation_warning(fair_value, upside)

        return tool_ok(
            ticker=ticker,
            model_type=state.financial_model.model_type if state.financial_model else None,
            fair_value=fair_value,
            current_price=current_price,
            upside_vs_market=upside,
            excel_path=state.financial_model.excel_path if state.financial_model else None,
            **({"data_quality_warning": warning} if warning else {}),
            note="DCF model built and saved (downloadable).",
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
        },
        "required": ["ticker"],
    }
    is_readonly = False

    async def execute(self, ticker: str, output_language: str = "") -> str:
        from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
        from src.agents.supervisor.task_agents.model_generation_agent import model_generation_agent
        from src.agents.supervisor.task_agents.news_analysis_agent import news_analysis_agent
        from src.agents.supervisor.task_agents.report_generator_agent import report_generator_agent

        import asyncio
        import copy as _copy
        state = self.ctx.ensure_state_for_ticker(ticker)
        if output_language and output_language.strip():
            state.output_language = output_language.strip()
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
        warning = _valuation_warning(fair_value, upside)
        return tool_ok(
            ticker=ticker,
            report_path=state.report.report_path,
            content_length=len(state.report.content) if state.report.content else 0,
            fair_value=fair_value,
            upside_vs_market=upside,
            overall_sentiment=na.overall_sentiment if na else None,
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
                "maxItems": 5,
            }
        },
        "required": ["tickers"],
    }
    is_readonly = True

    async def execute(self, tickers) -> str:
        import asyncio
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.replace(",", " ").split() if t.strip()]
        tickers = [t.strip().upper() for t in (tickers or []) if t and t.strip()][:5]
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
