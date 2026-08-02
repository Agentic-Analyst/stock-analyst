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

    def __init__(self, email: str, timestamp: str, user_prompt: str, logger=None):
        self.email = email
        self.timestamp = timestamp
        self.user_prompt = user_prompt
        self.logger = logger
        self.state = None            # FinancialState, created when a ticker is set
        self.ticker: Optional[str] = None
        self.company_name: Optional[str] = None
        self.session_name: Optional[str] = None
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
        return tool_ok(
            ticker=ticker,
            model_type=state.financial_model.model_type if state.financial_model else None,
            fair_value=vm.get("fair_value") if isinstance(vm, dict) else None,
            current_price=vm.get("current_price") if isinstance(vm, dict) else None,
            upside_vs_market=vm.get("upside_vs_market") if isinstance(vm, dict) else None,
            excel_path=state.financial_model.excel_path if state.financial_model else None,
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
        "'full report', or 'should I buy X'. Returns the report path and length."
    )
    parameters = {"type": "object", "properties": _TICKER_PARAM, "required": ["ticker"]}
    is_readonly = False

    async def execute(self, ticker: str) -> str:
        from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
        from src.agents.supervisor.task_agents.model_generation_agent import model_generation_agent
        from src.agents.supervisor.task_agents.news_analysis_agent import news_analysis_agent
        from src.agents.supervisor.task_agents.report_generator_agent import report_generator_agent

        import asyncio
        import copy as _copy
        state = self.ctx.ensure_state_for_ticker(ticker)
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
        return tool_ok(
            ticker=ticker,
            report_path=state.report.report_path,
            content_length=len(state.report.content) if state.report.content else 0,
            fair_value=vm.get("fair_value") if isinstance(vm, dict) else None,
            upside_vs_market=vm.get("upside_vs_market") if isinstance(vm, dict) else None,
            overall_sentiment=na.overall_sentiment if na else None,
            note="Full report generated (downloadable). Summarize its findings for the user.",
        )


def build_analysis_tools(ctx: AgentContext):
    """Instantiate the four wrapped-agent tools bound to one run context."""
    return [
        GetFinancialsTool(ctx),
        BuildModelTool(ctx),
        AnalyzeNewsTool(ctx),
        WriteReportTool(ctx),
    ]
