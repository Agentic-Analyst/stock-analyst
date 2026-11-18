"""A chat does not redraw its charts or re-download what it just fetched.

Every chat message runs in a fresh worker. Before this, a follow-up about the
same company drew the same price chart again under every answer, and fetched
the same quote, headlines, technicals and statements the message before it
had fetched seconds earlier.
"""
import asyncio
import json
import os
import sys
import types

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.tools import ui_tools  # noqa: E402
from src.agents.generalist_agent import (  # noqa: E402
    GeneralistAgent, _cache_tool_result, _cached_tool_result, _tool_cache_seconds,
)


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, line):
        self.lines.append(line)


def _ctx(shown=None):
    logger = _Logger()
    return types.SimpleNamespace(
        charts_in_chat=set(shown or ()), charts_this_turn=[], logger=logger,
        ensure_base_logger=lambda: None,
    )


@pytest.fixture(autouse=True)
def _prices_exist(monkeypatch):
    monkeypatch.setattr(ui_tools, "_has_price_data", lambda symbol: True)


def _draw(ctx, symbol, timeframe):
    return json.loads(asyncio.run(ui_tools.ShowChartTool(ctx).execute(symbol=symbol, timeframe=timeframe)))


# ---- charts --------------------------------------------------------------------

def test_a_chart_already_in_the_chat_is_not_drawn_again():
    ctx = _ctx({("HSN.AX", "1Y")})
    out = _draw(ctx, "hsn.ax", "1y")
    assert out["already_shown"] is True and "not drawn again" in out["note"]
    assert not any("[CHART_DIRECTIVE]" in line for line in ctx.logger.lines)
    assert ctx.charts_this_turn == []


def test_another_timeframe_or_company_is_a_new_chart_and_is_remembered():
    ctx = _ctx({("HSN.AX", "1Y")})
    out = _draw(ctx, "HSN.AX", "1D")
    assert "already_shown" not in out
    assert sum("[CHART_DIRECTIVE]" in line for line in ctx.logger.lines) == 1
    assert ctx.charts_this_turn == [{"symbol": "HSN.AX", "timeframe": "1D"}]
    # The same chart twice in one message is drawn once.
    assert _draw(ctx, "HSN.AX", "1D")["already_shown"] is True
    assert sum("[CHART_DIRECTIVE]" in line for line in ctx.logger.lines) == 1


def _agent(tmp_path, monkeypatch, session_id="chat-1"):
    monkeypatch.setenv("DATA_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    ag = GeneralistAgent.__new__(GeneralistAgent)
    ag.email, ag.session_id, ag.user_prompt, ag.timestamp = "u@example.com", session_id, "q", "t"
    return ag


def test_the_charts_of_earlier_messages_are_loaded_from_the_chat(tmp_path, monkeypatch):
    from src.session_manager import SessionManager
    ag = _agent(tmp_path, monkeypatch)
    sm = SessionManager(email="u@example.com", ticker="CHAT", session_name="chat-1")
    for charts in ([{"symbol": "HSN.AX", "timeframe": "1Y"}], None, [{"symbol": "^AXJO", "timeframe": "1M"}]):
        idx = sm.start_conversation(user_query="q", company_name=None)
        sm.update_conversation(conversation_index=idx, completion_status="completed",
                               analysis_results={"charts": charts} if charts else None)
    assert ag._charts_in_chat() == {("HSN.AX", "1Y"), ("^AXJO", "1M")}
    summary = SessionManager(email="u@example.com", ticker="CHAT",
                             session_name="chat-1").get_conversation_summary(limit=3)
    assert "Charts shown (still on screen, live): HSN.AX 1Y" in summary
    # A chat without an id has no earlier charts.
    ag.session_id = None
    assert ag._charts_in_chat() == set()


# ---- recent lookups ------------------------------------------------------------------

def test_a_lookup_is_reused_for_a_few_minutes_and_an_error_never(tmp_path, monkeypatch):
    monkeypatch.setenv("VYNN_CACHE_DIR", str(tmp_path))
    args = {"ticker": "HSN.AX", "period": "1y"}
    ok = json.dumps({"status": "ok", "latest": 3.57})
    assert _cached_tool_result("get_prices", args) is None
    _cache_tool_result("get_prices", args, ok)
    assert _cached_tool_result("get_prices", args) == ok
    assert _cached_tool_result("get_prices", {**args, "period": "5y"}) is None
    _cache_tool_result("get_technicals", {"ticker": "X"}, json.dumps({"status": "error"}))
    assert _cached_tool_result("get_technicals", {"ticker": "X"}) is None


def test_only_lookups_that_touch_no_analysis_state_are_reused():
    # A live quote ages fast; the analysis tools set the run's state and are never reused.
    assert _tool_cache_seconds("get_prices", {"period": "1d"}) == 60
    assert _tool_cache_seconds("get_prices", {"period": "1y"}) == 600
    for name in ("get_financials", "build_model", "write_report", "read_report", "analyze_news",
                 "show_chart", "compare_tickers"):
        assert _tool_cache_seconds(name, {}) == 0


def test_without_a_cache_folder_nothing_is_reused(monkeypatch):
    monkeypatch.delenv("VYNN_CACHE_DIR", raising=False)
    monkeypatch.setattr(os.path, "isdir", lambda path: False if path == "/data" else os.path.exists(path))
    _cache_tool_result("get_macro", {}, json.dumps({"status": "ok"}))
    assert _cached_tool_result("get_macro", {}) is None


# ---- statements ----------------------------------------------------------------------

def test_a_companys_statements_are_reused_within_fifteen_minutes(tmp_path, monkeypatch):
    import importlib
    fda = importlib.import_module("src.agents.supervisor.task_agents.financial_data_agent")
    monkeypatch.setenv("VYNN_CACHE_DIR", str(tmp_path / "cache"))
    downloads = []

    class _Scraper:
        def __init__(self, ticker, base_path):
            self.ticker, self.financials_dir = ticker, base_path / "financials"
            self.yf_ticker = types.SimpleNamespace(info={"quoteType": "EQUITY"})

        def set_logger(self, logger):
            pass

        def scrape_financial_modeling_data(self, annual=True):
            downloads.append(self.ticker)
            return {"company_data": {"basic_info": {"quote_type": "EQUITY", "currency": "AUD",
                                                    "long_name": "Hansen"},
                                     "market_data": {"current_price": 3.57}},
                    "data_summary": {"data_completeness": {"income_statement_periods": 4}}}

        def save_financial_data(self, data):
            self.financials_dir.mkdir(parents=True, exist_ok=True)
            path = self.financials_dir / "financials_annual_modeling_latest.json"
            path.write_text(json.dumps(data))
            return path

    monkeypatch.setattr(fda, "FinancialScraper", _Scraper)

    def _state(folder):
        logs = []
        return types.SimpleNamespace(
            ticker="HSN.AX", company_name="Hansen", analysis_path=tmp_path / folder,
            financial_data=None, current_stage=None, logs=logs,
            log_action=lambda agent, msg: logs.append(msg), log_error=lambda agent, msg: logs.append(msg),
            get_effective_logger=lambda name: None,
        )

    first = asyncio.run(fda.financial_data_agent(_state("run1")))
    second = asyncio.run(fda.financial_data_agent(_state("run2")))
    assert downloads == ["HSN.AX"]
    assert any("Reusing financial data for HSN.AX" in line for line in second.logs)
    assert second.financial_data.raw_data == first.financial_data.raw_data
    # The second run still saves its own copy for the model builder.
    assert (tmp_path / "run2" / "financials" / "financials_annual_modeling_latest.json").exists()
