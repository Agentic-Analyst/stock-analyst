"""
Findings must be denominated in the currency they were measured in.

THE BUG. A verified LVMH run produced a correct EUR report — the currency work
inside report_agent held — and then published the finding chip "$388.27" next to
it on the chat surface the user watches while waiting. The number was LVMH's
fair value in euros; the symbol was hardcoded.

That is the same mislabelling that was fixed inside reports, surviving one layer
out because findings.py formatted money with a literal "$" and no tool payload
carried a currency at all.

These tests pin the formatter, the plumbing that feeds it, and the specific
figure from the run that exposed it.

Run:  python -m pytest tests/test_finding_currency.py -q
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.findings import _money, _symbol, extract_findings
from src.currency import currency_symbol


class TestSymbolTable:
    def test_shared_table_needs_no_llm_stack(self):
        """
        src/currency.py must stay dependency-free. findings runs on the hot log
        path, and when this table lived in report_agent the only safe way to
        reach it was a try/except import that silently fell back to dollars.
        """
        import ast
        source = open(os.path.join(_ROOT, "src", "currency.py"), encoding="utf-8").read()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        # Checked against real imports, not the file text: the module docstring
        # names report_agent when explaining why the table moved out of it.
        assert imported <= {"__future__", "typing"}, imported

    def test_report_agent_still_exports_it(self):
        """Existing callers import currency_symbol from report_agent."""
        from src.report_agent import currency_symbol as from_report_agent
        assert from_report_agent("EUR") == "€"

    @pytest.mark.parametrize("code,expected",
                             [("EUR", "€"), ("USD", "$"), ("JPY", "¥"), ("GBP", "£")])
    def test_known_codes(self, code, expected):
        assert currency_symbol(code) == expected

    def test_unknown_code_falls_back_to_itself(self):
        assert currency_symbol("XYZ") == "XYZ "

    def test_missing_currency_is_dollars(self):
        assert _symbol(None) == "$"
        assert _symbol("") == "$"


class TestMoneyFormatting:
    def test_the_figure_from_the_run(self):
        """LVMH's fair value. This exact chip read "$388.27" in production."""
        assert _money(388.27, "EUR") == "€388.27"
        assert "$" not in _money(388.27, "EUR")

    def test_defaults_to_dollars_when_unknown(self):
        assert _money(388.27) == "$388.27"

    def test_scales_keep_the_symbol(self):
        assert _money(226_443_575_296, "EUR") == "€226.4B"
        assert _money(37_003_290_738_688, "JPY") == "¥37.00T"
        assert _money(5_103_432, "GBP") == "£5.1M"

    def test_non_numeric_yields_nothing(self):
        assert _money(None, "EUR") is None
        assert _money("n/a", "EUR") is None


class TestFindingsCarryCurrency:
    def test_fair_value_chip_is_euros(self):
        found = extract_findings("build_model",
                                 {"fair_value": 388.27, "currency": "EUR",
                                  "upside_vs_market": -0.15})
        assert found[0]["value"] == "€388.27"

    def test_report_chip_is_euros(self):
        found = extract_findings("write_report",
                                 {"fair_value": 388.27, "currency": "EUR"})
        assert any("€388.27" == f["value"] for f in found)

    def test_price_chip_is_euros(self):
        found = extract_findings("get_prices",
                                 {"ticker": "MC.PA", "latest_price": 459.35,
                                  "currency": "EUR", "day_change_pct": 1.5})
        assert found[0]["value"] == "€459.35"

    def test_market_cap_chip_is_euros(self):
        found = extract_findings("get_financials",
                                 {"company_name": "LVMH", "market_cap": 226_443_575_296,
                                  "currency": "EUR"})
        assert found[0]["value"] == "€226.4B"

    def test_us_listings_are_unchanged(self):
        """The default path must not regress: no currency means dollars."""
        found = extract_findings("get_prices",
                                 {"ticker": "NVDA", "latest_price": 209.22,
                                  "day_change_pct": -2.1})
        assert found[0]["value"] == "$209.22"


class TestToolsReportTheirCurrency:
    """A formatter that reads `currency` is useless if no tool ever sends one."""

    def test_price_tool_publishes_currency(self):
        import inspect
        from src.agents.tools.data_tools import GetPricesTool
        source = inspect.getsource(GetPricesTool.execute)
        assert 'payload["currency"] = currency' in source

    def test_listing_identity_returns_name_and_currency(self, monkeypatch):
        import types
        from src.agents.tools import data_tools

        module = types.ModuleType("yfinance")

        class _Ticker:
            def __init__(self, symbol):
                pass

            @property
            def info(self):
                return {"longName": "LVMH", "currency": "EUR"}

        module.Ticker = _Ticker
        monkeypatch.setitem(sys.modules, "yfinance", module)
        assert data_tools.listing_identity("MC.PA") == ("LVMH", "EUR")

    def test_listing_identity_never_raises(self, monkeypatch):
        import types
        from src.agents.tools import data_tools

        module = types.ModuleType("yfinance")

        class _Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("Yahoo is down")

        module.Ticker = _Boom
        monkeypatch.setitem(sys.modules, "yfinance", module)
        assert data_tools.listing_identity("MC.PA") == (None, None)

    def test_analysis_tools_publish_currency(self):
        source = open(os.path.join(_ROOT, "src", "agents", "tools",
                                   "analysis_tools.py"), encoding="utf-8").read()
        # build_model and write_report both derive it from the scraped listing.
        assert source.count("currency=_listing_currency(state)") == 2
        # get_financials reads it straight off basic_info.
        assert 'currency=basic.get("currency")' in source

    def test_listing_currency_helper_tolerates_missing_state(self):
        from src.agents.tools.analysis_tools import _listing_currency

        class _NoData:
            financial_data = None

        assert _listing_currency(_NoData()) is None
        assert _listing_currency(None) is None
