"""
Defects found by auditing the four most recent external runs (Sep 3-5, 2026).

Each class names the run that exposed it. These are the first real runs after
the Aug 24-25 deploys, and they showed that work holding — home-listing
resolution, currency, the recommendation section rendering, rating agreement —
while surfacing what it had not touched, and two things it had got wrong.

Run:  python -m pytest tests/test_run_audit_fixes.py -q
"""

import inspect
import re
import os
import sys
import types
from dataclasses import dataclass

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))


class TestSentimentReachesTheChat:
    """
    ALNY (chesko): the screening said bearish at 87% confidence, the report
    printed BEARISH, the chat said "neutral". PC Jeweller's chat also said
    "neutral". The news agent guarded with isinstance(dict) against a value
    that is an AnalysisSummary dataclass, so the default fired every time.
    """

    def test_the_guard_accepts_the_dataclass(self):
        from src.agents.supervisor.task_agents import news_analysis_agent
        source = inspect.getsource(news_analysis_agent)
        assert 'getattr(analysis_summary, "overall_sentiment"' in source

    def test_dataclass_and_dict_both_resolve(self):
        """The exact expression, evaluated against both shapes."""
        @dataclass
        class Summary:
            overall_sentiment: str

        def resolve(analysis_summary):
            return (analysis_summary.get("overall_sentiment", "neutral")
                    if isinstance(analysis_summary, dict)
                    else getattr(analysis_summary, "overall_sentiment", None) or "neutral")

        assert resolve(Summary("bearish")) == "bearish"
        assert resolve({"overall_sentiment": "bullish"}) == "bullish"
        assert resolve(None) == "neutral"
        assert resolve(Summary("")) == "neutral"


class TestDebtToEquityUnits:
    """
    PC Jeweller: "debt/equity at 14.27 ... Risk Rating: High". yfinance's
    debtToEquity is a percent — 14.27% is 0.14x, and debt was 9% of capital.
    """

    def test_scraper_converts_percent_to_ratio(self):
        source = open(os.path.join(_ROOT, "src", "financial_scraper.py"), encoding="utf-8").read()
        assert 'info["debtToEquity"] / 100.0' in source

    def test_the_conversion_itself(self):
        info = {"debtToEquity": 14.271}
        ratio = (info["debtToEquity"] / 100.0
                 if isinstance(info.get("debtToEquity"), (int, float)) else None)
        assert ratio == pytest.approx(0.14271)

    def test_missing_field_stays_none(self):
        info = {}
        ratio = (info["debtToEquity"] / 100.0
                 if isinstance(info.get("debtToEquity"), (int, float)) else None)
        assert ratio is None


class TestBankValuationScope:
    """
    PayPal (eplatty) was valued on justified P/B x ROE ($61.01) because Yahoo
    files it under "Financial Services / Credit Services". The report ran a DCF
    ($87.11). Narrowing the industry hints to fix that would have been its own
    regression: Capital One, Synchrony, Ally and Bajaj Finance are "Credit
    Services" too, and they ARE lenders. The interest-income share decides.
    """

    def test_payments_and_exchanges_are_not_lenders(self):
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Financial Services", "Credit Services", 0.02) is False    # PayPal
        assert is_financial_sector("Financial Services", "Credit Services", -0.01) is False   # Visa
        assert is_financial_sector("Financial Services", "Financial Data & Stock Exchanges", -0.01) is False  # Coinbase

    def test_lenders_in_the_same_industry_still_qualify(self):
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Financial Services", "Credit Services", 1.22) is True    # Capital One
        assert is_financial_sector("Financial Services", "Credit Services", 2.28) is True    # Synchrony
        assert is_financial_sector("Financial Services", "Credit Services", 1.56) is True    # Bajaj Finance
        assert is_financial_sector("Financial Services", "Credit Services", 0.36) is True    # Amex

    def test_banks_and_insurers_qualify(self):
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Financial Services", "Banks—Regional", 1.14) is True
        assert is_financial_sector("Financial Services", "Insurance—Life") is True

    def test_without_an_income_statement_the_deployed_behaviour_holds(self):
        """No ratio available: fall back to the hints exactly as production does."""
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Financial Services", "Credit Services") is True
        assert is_financial_sector("Financial Services", None) is True
        assert is_financial_sector("Technology", "Software") is False

    def test_a_non_financial_is_never_a_bank_whatever_the_ratio(self):
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Technology", "Software", 5.0) is False


class TestShareCountSeed:
    """
    sharesOutstanding is Class A only for Alphabet (5.9B against 12.2B implied)
    and misses Samsung's preferreds. Seeding the bridge from it doubled
    Alphabet's value per share. impliedSharesOutstanding is market cap / price.
    """

    def test_implied_is_preferred(self):
        from src.agents.fm.assumption_grounding import _current_shares
        assert _current_shares({"shares_outstanding_implied": 12.23e9, "shares_outstanding_basic": 5.87e9,
                                "market_cap": 4.1e12, "current_price": 338.46}) == 12.23e9

    def test_basic_is_accepted_only_when_it_reconciles(self):
        from src.agents.fm.assumption_grounding import _current_shares
        ok = _current_shares({"shares_outstanding_basic": 855e6, "market_cap": 855e6 * 54.96, "current_price": 54.96})
        assert ok == 855e6
        bad = _current_shares({"shares_outstanding_basic": 5.87e9, "market_cap": 4.1e12, "current_price": 338.46})
        assert bad is None

    def test_basic_is_taken_when_nothing_to_reconcile_against(self):
        from src.agents.fm.assumption_grounding import _current_shares
        assert _current_shares({"shares_outstanding_basic": 9.75e9}) == 9.75e9

    def test_nothing_usable_returns_none(self):
        from src.agents.fm.assumption_grounding import _current_shares
        assert _current_shares({}) is None


class TestPenceQuotedListings:
    """
    London quotes in pence. The price, previous close and 52-week range arrived
    in GBp while the market cap and every statement were in GBP, so a £25
    valuation was compared to a "price" of 3,437 and every LSE listing showed a
    99% downside. Pre-existing; found while reconciling share counts.
    """

    def test_pence_are_converted_to_pounds(self):
        from src.financial_scraper import _price_in_major_units
        assert _price_in_major_units(3437.0, "GBp") == pytest.approx(34.37)

    def test_other_currencies_are_untouched(self):
        from src.financial_scraper import _price_in_major_units
        assert _price_in_major_units(459.35, "EUR") == 459.35
        assert _price_in_major_units(54.96, "USD") == 54.96

    def test_missing_price_stays_missing(self):
        from src.financial_scraper import _price_in_major_units
        assert _price_in_major_units(None, "GBp") is None

    def test_currency_is_reported_in_the_statements_currency(self):
        """GBp becomes GBP; and a listing that reports in another currency is
        labelled in that currency, since that is what a value per share is in."""
        import src.financial_scraper as fs
        assert fs._reporting_currency({"currency": "GBp"}) == "GBP"
        assert fs._reporting_currency({"currency": "GBp", "financialCurrency": "USD"}) == "USD"
        assert fs._reporting_currency({"currency": "USD", "financialCurrency": "JPY"}) == "JPY"
        assert fs._reporting_currency({"currency": "EUR", "financialCurrency": "EUR"}) == "EUR"


class TestChatQuotesTheReportsFairValue:
    """
    Even when the balance-sheet method legitimately fires, the report is built
    from the workbook DCF. The chat must quote the number the document shows.
    """

    def test_write_report_quotes_the_number_the_report_shows(self):
        """
        The report now carries the balance-sheet valuation (apply_valuation_
        override), so the chat quotes THAT for a bank. An earlier version of
        this fix preferred the DCF number — which for a bank is 0.00.
        """
        from src.agents.tools.analysis_tools import WriteReportTool
        source = inspect.getsource(WriteReportTool.execute)
        assert 'fair_value = vm.get("dcf_fair_value")' not in source
        assert "dcf_fair_value_cross_check" in source

    def test_the_cross_check_logic(self):
        def cross_check(vm, method):
            dcf = None
            if method == "justified_pb_roe":
                _dcf = vm.get("dcf_fair_value")
                if isinstance(_dcf, (int, float)) and _dcf > 0:
                    dcf = _dcf
            return dcf
        assert cross_check({"dcf_fair_value": 0.0}, "justified_pb_roe") is None      # a bank's zeroed DCF
        assert cross_check({"dcf_fair_value": 87.11}, "justified_pb_roe") == 87.11
        assert cross_check({"dcf_fair_value": 87.11}, "dcf") is None


class TestTaxRateInTheWorkbook:
    """
    PC Jeweller: Tax Provision -9.7M on Pretax Income 7.1B gave -0.14%, and the
    DCF discounted debt at an after-tax cost above its pre-tax cost. Yahoo
    publishes "Tax Rate For Calcs" (0.40 that year).
    """

    def _formula(self):
        """The CODE that builds row 20, with comment lines removed — the
        comment explaining this fix necessarily names the forms it rejects."""
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs", "tab_assumptions.py"),
                      encoding="utf-8").read()
        block = source[source.index('value="Effective Tax Rate (FY0)"'):]
        block = block[:block.index("ws.cell(row=20, column=2")]
        return "\n".join(l for l in block.splitlines() if not l.strip().startswith("#"))

    def test_prefers_yahoo_s_calculation_rate(self):
        assert '"Tax Rate For Calcs"' in self._formula()

    def test_clamped_to_a_sane_band_with_if_only(self):
        """
        The clamp must not wrap a function call in MAX/MIN. Until the evaluator
        was fixed, MIN(0.5, SUMIFS(...)) evaluated to 0.5 and the first version
        of this clamp to 0 — zero tax on every forecast year, lifting PayPal's
        perpetual leg from $98 to $146. The evaluator is fixed too, but the
        formula stays in the form that never depended on it.
        """
        f = self._formula()
        assert "MAX(" not in f and "MIN(" not in f
        assert f.count("IF(") >= 4
        assert ">0.5,0.5," in f and "<0,0," in f

    def test_capm_side_already_rejects_nonsense(self):
        from src.agents.fm.assumption_grounding import _effective_tax_rate, _TAX_DEFAULT
        assert _effective_tax_rate({"growth_profitability": {"effective_tax_rate": -0.0014}}) == _TAX_DEFAULT
        assert _effective_tax_rate({"growth_profitability": {"effective_tax_rate": 0.4}}) == 0.4


class TestShareCount:
    """
    Per-share value divided by last year's diluted AVERAGE. PC Jeweller: 8.61B
    against 9.75B outstanding (value 13% too high). PayPal: 968M against 855M
    after buybacks (13% too low).
    """

    def test_grounding_publishes_the_live_count(self):
        from src.agents.fm.assumption_grounding import ground_assumptions
        a, _ = ground_assumptions(
            {"wacc": 0.09, "terminal_growth_rate": 0.025},
            {"company_data": {"basic_info": {"currency": "USD"},
                              "capital_structure": {"beta": 1.0, "total_debt": 0},
                              "market_data": {"market_cap": 1e9,
                                              "shares_outstanding_basic": 9_752_134_855}}},
        )
        assert a["shares_outstanding_current"] == 9_752_134_855

    def test_workbook_seeds_from_the_live_count(self):
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs", "tab_assumptions.py"),
                      encoding="utf-8").read()
        assert 'self.llm_assumptions.get("shares_outstanding_current")' in source

    def test_fallback_prefers_year_end_over_average(self):
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs", "tab_assumptions.py"),
                      encoding="utf-8").read()
        block = source[source.index("live_shares = "):source.index("ws.cell(row=18, column=3")]
        assert block.index('"Ordinary Shares Number"') < block.index('"Diluted Average Shares"')


class TestEveryLegInTheAverage:
    """
    PayPal: "$98.34", "$89.59", then "Average Intrinsic Value $87.11". The
    workbook blends a third, market-comps leg ($73.41) that the table omitted.
    """

    def test_extract_valuation_exposes_the_comps_leg(self):
        from src.report_agent import extract_valuation
        v = extract_valuation({'Summary': {'cells': {'(18, 2)': 98.34, '(22, 2)': 89.59,
                                                      '(26, 2)': 87.11, '(30, 2)': 73.41}}})
        assert v['summary']['comps_intrinsic'] == 73.41

    def test_the_table_shows_it(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=73.41)
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("commentary", 0.0))
        assert "| Present-Valued Market Comps | $73.41 |" in text
        assert "Blended Fair Value (50% DCF view / 50% present-valued market comps)" in text

    def test_no_comps_no_phantom_row(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=None)
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("commentary", 0.0))
        assert "Market Comps" not in text
        assert "| **DCF Fair Value** |" in text


class TestReportGridRunsTheHeadlineModel:
    """
    ALNY: report grid centre 287, headline $333.84, identical inputs. The grid
    recomputed five explicit years while the DCF discounts ten with a fade.
    """

    ALNY_FCF = [0.50e9, 0.90e9, 1.37e9, 1.85e9, 2.34e9, 2.60e9, 2.83e9, 3.02e9, 3.16e9, 3.23e9]

    def test_grid_uses_the_dcf_tab_s_own_path(self):
        from src.report_agent import build_sensitivity_grid
        source = inspect.getsource(build_sensitivity_grid)
        assert "dcf_inputs" in source
        assert "[:5]" not in source

    def test_ten_periods_beat_five_for_a_growing_profile(self):
        """The truncation is what produced 287; ten periods land near 334."""
        w, g = 0.0794, 0.025
        def value(fcf):
            pv = sum(f / (1 + w) ** (i + 1) for i, f in enumerate(fcf))
            tv = fcf[-1] * (1 + g) / (w - g) / (1 + w) ** len(fcf)
            return pv + tv
        assert value(self.ALNY_FCF) > value(self.ALNY_FCF[:5]) * 1.10

    def test_extract_valuation_carries_the_inputs(self):
        from src.report_agent import extract_valuation
        cells = {f'(16, {c})': v for c, v in zip(range(2, 12), self.ALNY_FCF)}
        cells.update({'(30, 2)': 1e9, '(31, 2)': 2e9, '(32, 2)': 0.5e9, '(36, 2)': 130e6})
        v = extract_valuation({'Valuation (DCF)': {'cells': cells}})
        assert v['dcf_inputs']['fcf'] == self.ALNY_FCF
        assert v['dcf_inputs']['shares'] == 130e6


class TestRiskFreeProvenanceIsPrinted:
    """
    PC Jeweller was discounted on a US Treasury (4.78%) for rupee cash flows.
    The Assumptions tab said so — "[US 10Y 4.78% used as a proxy — no INR
    sovereign yield source available]" — and the report never printed it.
    """

    def test_extract_reads_the_notes(self):
        from src.report_agent import extract_cost_of_capital
        coc = extract_cost_of_capital({
            'Valuation (DCF)': {'cells': {'(12, 1)': 'WACC', '(12, 2)': 0.0792}},
            'Assumptions': {'cells': {
                '(23, 3)': '[US 10Y 4.78% used as a proxy — no INR sovereign yield source available]',
                '(25, 3)': '[Blume-adjusted from observed 0.33]'}},
        })
        assert coc['risk_free_source'].startswith('US 10Y 4.78% used as a proxy')
        assert coc['beta_source'] == 'Blume-adjusted from observed 0.33'

    def test_the_table_prints_them(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=None)
        data['cost_of_capital'].update({'risk_free_source': 'US 10Y 4.78% used as a proxy — no INR sovereign yield source available',
                                        'beta_source': 'Blume-adjusted from observed 0.33'})
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("commentary", 0.0))
        assert "| Risk-free source | US 10Y 4.78% used as a proxy" in text
        assert "| Beta source | Blume-adjusted from observed 0.33 |" in text

    def test_the_cost_of_debt_build_is_printed(self):
        """Kd is priced off the government bond, not the default-free rate; the row says so."""
        from src.report_agent import extract_cost_of_capital, generate_section_valuation
        coc = extract_cost_of_capital({
            'Valuation (DCF)': {'cells': {'(12, 1)': 'WACC', '(12, 2)': 0.0792}},
            'Assumptions': {'cells': {'(27, 3)': '[10Y government yield 6.89% + 1.5% credit spread]'}},
        })
        assert coc['kd_source'] == '10Y government yield 6.89% + 1.5% credit spread'
        data = _valuation_data(comps=None)
        data['cost_of_capital']['kd_source'] = coc['kd_source']
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("commentary", 0.0))
        assert "| Cost of debt build | 10Y government yield 6.89% + 1.5% credit spread |" in text

    def test_the_terminal_growth_basis_is_printed_when_it_was_capped(self):
        from src.report_agent import extract_cost_of_capital, generate_section_valuation
        coc = extract_cost_of_capital({
            'Valuation (DCF)': {'cells': {'(12, 1)': 'WACC', '(12, 2)': 0.0509}},
            'Assumptions': {'cells': {'(30, 3)': '[capped at the JPY risk-free rate 2.31% — a perpetuity cannot outgrow its currency\'s economy]'}},
        })
        data = _valuation_data(comps=None)
        data['cost_of_capital']['terminal_growth_source'] = coc['terminal_growth_source']
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("commentary", 0.0))
        assert "| Terminal growth basis | capped at the JPY risk-free rate 2.31%" in text
        # The default "[LLM]" note is not a basis worth a row.
        data['cost_of_capital']['terminal_growth_source'] = 'LLM'
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("commentary", 0.0))
        assert "Terminal growth basis" not in text


class TestTablesAreEmittedByCode:
    """
    PC Jeweller's valuation section had zero tables: the model was asked to
    reproduce seven and reproduced none, then wrote prose citing a grid it had
    declined to print.
    """

    def _section(self, llm_text):
        from src.report_agent import generate_section_valuation
        return generate_section_valuation(_valuation_data(comps=73.41),
                                          lambda m, temperature=0.5: (llm_text, 0.0))[0]

    def test_every_table_is_present_whatever_the_model_returns(self):
        text = self._section("Three paragraphs of prose and no tables.")
        for heading in ("### Model Assumptions", "### Cost of Capital",
                        "### Sensitivity: Value per Share", "### 5-Year Projections",
                        "### DCF Valuation — Perpetual Growth Method",
                        "### DCF Valuation — Exit Multiple Method", "### Valuation Summary"):
            assert heading in text, heading
        assert text.count("|---") >= 7

    def test_the_commentary_follows_the_tables(self):
        text = self._section("Rates dominate.")
        assert text.index("### Valuation Summary") < text.index("### Commentary")
        assert text.rstrip().endswith("Rates dominate.")

    def test_an_echoed_table_is_not_printed_twice(self):
        echoed = "### Model Assumptions\n\n| Assumption | Value |\n|---|---|\n| x | 1 |\n\n### Commentary\n\nOnly this."
        text = self._section(echoed)
        assert text.count("### Model Assumptions") == 1
        assert text.rstrip().endswith("Only this.")

    def test_the_prompt_forbids_reproduction(self):
        prompt = open(os.path.join(_ROOT, "prompts", "report_valuation.md"), encoding="utf-8").read()
        assert "Do NOT reproduce" in prompt
        assert "{tables}" in prompt


class TestDispersionWarningIsCurrencyNeutral:
    def test_no_dollar_sign_in_the_spread_text(self):
        from src.agents.tools import analysis_tools
        source = inspect.getsource(analysis_tools._valuation_dispersion) \
            if hasattr(analysis_tools, "_valuation_dispersion") else inspect.getsource(analysis_tools)
        assert "${v:,.2f}" not in source


def _valuation_data(comps):
    five = [0.03, 0.028, 0.026, 0.024, 0.022]
    return {
        'company_overview': {'company_name': 'PayPal Holdings, Inc.', 'current_price': 54.93},
        'assumptions': {'wacc': 0.0995, 'terminal_growth': 0.025, 'revenue_growth_rates': five,
                        'gross_margins': five, 'ebitda_margins': five, 'operating_margins': five},
        'cost_of_capital': {'risk_free_rate': 0.0478, 'equity_risk_premium': 0.055, 'beta': 1.1997,
                            'cost_of_equity': 0.1138, 'pre_tax_cost_of_debt': 0.0628, 'tax_rate': 0.1683,
                            'after_tax_cost_of_debt': 0.0522, 'equity_weight': 0.7677,
                            'debt_weight': 0.2323, 'wacc': 0.0995},
        'projections': {'revenue': [35e9] * 5, 'ebitda': [8e9] * 5,
                        'fcf': [8.31e9, 5.99e9, 6.32e9, 6.62e9, 6.88e9]},
        'valuation': {
            'dcf_perpetual': {'pv_fcfs': 40e9, 'terminal_value': 60e9, 'enterprise_value': 100e9,
                              'equity_value': 95e9, 'intrinsic_value_per_share': 98.34},
            'dcf_exit': {'terminal_ev': 80e9, 'enterprise_value': 92e9, 'equity_value': 87e9,
                         'intrinsic_value_per_share': 89.59, 'exit_multiple': 11.0},
            'summary': {'dcf_intrinsic': 98.34, 'exit_intrinsic': 89.59, 'comps_intrinsic': comps,
                        'average_intrinsic': 87.11, 'upside': 0.586, 'shares_outstanding': 855e6,
                        'cash': 10e9, 'debt': 12e9, 'net_debt': 2e9},
            'dcf_inputs': {'fcf': [8.31e9, 5.99e9, 6.32e9, 6.62e9, 6.88e9, 7.0e9, 7.1e9, 7.2e9, 7.3e9, 7.4e9],
                           'cash': 10e9, 'debt': 12e9, 'investments': 0.0, 'shares': 855e6},
        },
    }


class TestEvaluatorNestedCallsInAggregates:
    """
    MAX/MIN/SUM shortcut any argument containing ':' to a range read. A
    function call whose arguments include a range — SUMIFS(Raw!$D:$D, ...) —
    was swallowed whole and contributed nothing, so MIN(0.5, SUMIFS(...))
    returned 0.5 and the workbook's tax rate evaluated to 0.
    """

    def _evaluate(self, formula):
        openpyxl = pytest.importorskip("openpyxl")
        import logging
        from src.agents.fm.formula_evaluator import FormulaEvaluator
        wb = openpyxl.Workbook(); raw = wb.active; raw.title = "Raw"
        raw.append(["Statement", "Field", "Year", "Value"])
        raw.append(["Income Statement", "Tax Rate For Calcs", "2026-03-31", 0.4])
        raw.append(["Income Statement", "Tax Provision", "2026-03-31", -9.7e6])
        raw.append(["Income Statement", "Pretax Income", "2026-03-31", 7.1349e9])
        a = wb.create_sheet("Assumptions"); a["B2"] = 2026; a["B20"] = formula
        ev = FormulaEvaluator(wb); ev.set_logger(logging.getLogger("t"))
        return ev.evaluate_all_tabs().get("Assumptions", {}).get("cells", {}).get("(20, 2)")

    CALCS = 'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Tax Rate For Calcs",Raw!$C:$C,$B$2&"*")'

    def test_min_over_a_nested_call(self):
        assert self._evaluate(f"=MIN(0.5,{self.CALCS})") == pytest.approx(0.4)

    def test_max_over_a_nested_call(self):
        assert self._evaluate(f"=MAX(0,{self.CALCS})") == pytest.approx(0.4)

    def test_the_originally_shipped_clamp_now_evaluates(self):
        ratio = ('SUMIFS(Raw!$D:$D,Raw!$B:$B,"Tax Provision",Raw!$C:$C,$B$2&"*")/'
                 'SUMIFS(Raw!$D:$D,Raw!$B:$B,"Pretax Income",Raw!$C:$C,$B$2&"*")')
        f = f"=IFERROR(MAX(0,MIN(0.5,IF({self.CALCS}>0,{self.CALCS},{ratio}))),\"\")"
        assert self._evaluate(f) == pytest.approx(0.4)

    def test_bare_ranges_still_work(self):
        assert self._evaluate("=MAX(Raw!D2:D4)") == pytest.approx(7.1349e9)
        assert self._evaluate("=MIN(Raw!D2:D4)") == pytest.approx(-9.7e6)

    def test_the_shipped_if_only_form_evaluates(self):
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs", "tab_assumptions.py"),
                      encoding="utf-8").read()
        block = source[source.index('value="Effective Tax Rate (FY0)"'):]
        block = block[:block.index("ws.cell(row=20, column=2")]
        # Reconstruct the formula exactly as the builder assembles it.
        ns = {}
        exec("calcs = " + block[block.index("calcs = ") + 8: block.index("\n", block.index("calcs = "))], ns)
        exec("ratio = (" + block[block.index("ratio = (") + 9: block.index(")\n", block.index("ratio = ")) + 1], ns)
        f = (f'=IFERROR(IF({ns["calcs"]}>0,IF({ns["calcs"]}>0.5,0.5,{ns["calcs"]}),'
             f'IF({ns["ratio"]}<0,0,IF({ns["ratio"]}>0.5,0.5,{ns["ratio"]}))),"")')
        assert self._evaluate(f) == pytest.approx(0.4)


class TestRatingIgnoresBrokenLegs:
    """
    PC Jeweller, with a real beta and India's premium: perpetual DCF -2.03,
    exit 6.82, price 12.87. The summary averages positive legs to 12.14 (a 6%
    discount). The calculator averaged BOTH — (-2.03 + 6.82) / 2 = 2.40 — and
    rated it STRONG SELL on an 81% "discount" the report never shows. A
    negative per-share value is a method that does not fit the company, not a
    low estimate.
    """

    def _calc(self, perp, exit_, price=12.87):
        from src.recommendation_calculator import RecommendationCalculator
        try:
            calc = RecommendationCalculator()
        except TypeError:
            calc = RecommendationCalculator(sector="default")
        return calc.calculate_fixed_numbers(
            ticker="PCJEWELLER.NS", current_price=price, dcf_perpetual=perp, dcf_exit=exit_,
            catalyst_score_pct=0.0, risk_score_pct=0.0, momentum_score_pct=0.0,
            hist_vol_annual_pct=30.0,
        )

    def test_a_negative_leg_is_excluded_from_the_gap(self):
        fn = self._calc(-2.03, 6.82)
        gap = fn["inputs"]["raw_val_gap_pct"]
        assert gap == pytest.approx((6.82 / 12.87 - 1) * 100, abs=0.01)
        assert fn["inputs"]["dcf_legs_used"] == 1

    def test_two_positive_legs_are_averaged(self):
        fn = self._calc(10.0, 14.0)
        assert fn["inputs"]["raw_val_gap_pct"] == pytest.approx((12.0 / 12.87 - 1) * 100, abs=0.01)
        assert fn["inputs"]["dcf_legs_used"] == 2

    def test_no_positive_leg_is_a_zero_gap_not_a_crash(self):
        fn = self._calc(-2.0, -5.0)
        assert fn["inputs"]["raw_val_gap_pct"] == 0
        assert fn["inputs"]["dcf_legs_used"] == 0

    def test_a_zero_leg_is_still_treated_as_missing(self):
        fn = self._calc(0.0, 14.0)
        assert fn["inputs"]["dcf_legs_used"] == 1


class TestBankValuationReachesTheReport:
    """
    Deployed today: Capital One and JPMorgan reports print "DCF $0.00 /
    Average $0.00 / Implied Upside -100%" and rate STRONG SELL, while the chat
    quotes $159.34 and $304.65 from justified P/B x ROE. The override lived in
    state; the report was built from the workbook, whose DCF was zeroed.
    """

    def _data(self):
        return {'company_overview': {'current_price': 219.60},
                'valuation': {'dcf_perpetual': {'intrinsic_value_per_share': 0.0},
                              'dcf_exit': {'intrinsic_value_per_share': 0.0},
                              'summary': {'average_intrinsic': 0.0, 'upside': -1.0, 'comps_intrinsic': 180.0}}}

    def test_the_report_adopts_the_bank_number(self):
        from src.report_agent import apply_valuation_override, generate_section_valuation
        d = apply_valuation_override(self._data(), {'valuation_method': 'justified_pb_roe', 'fair_value': 159.34})
        assert d['valuation']['bank']['fair_value'] == 159.34
        assert d['valuation']['summary']['average_intrinsic'] == 159.34
        assert d['valuation']['summary']['upside'] == pytest.approx(159.34 / 219.60 - 1)
        # the engine rates on the same number
        assert d['valuation']['dcf_perpetual']['intrinsic_value_per_share'] == 159.34
        assert d['valuation']['dcf_exit']['intrinsic_value_per_share'] == 159.34

    def test_discarded_dcf_dispersion_cannot_withhold_the_bank_method(self):
        from src.report_agent import apply_valuation_override
        d = apply_valuation_override(self._data(), {
            'valuation_method': 'justified_pb_roe', 'fair_value': 159.34,
            'dispersion_band': 'unreliable', 'dispersion_ratio': 8.0,
            'valuation_warning': 'discarded DCF methods disagree',
        })
        assert d['valuation']['summary']['average_intrinsic'] == 159.34
        assert 'reliability' not in d['valuation']

    def test_modeling_json_builds_the_same_override_for_the_comprehensive_path(self):
        from src.agents.fm.bank_valuation import build_bank_valuation_override

        financial_data = {
            'company_data': {
                'basic_info': {
                    'sector': 'Financial Services',
                    'industry': 'Banks - Diversified',
                },
                'valuation_metrics': {'book_value': 133.007},
                'growth_profitability': {'return_on_equity': 0.17789},
                'market_data': {'current_price': 353.56},
                'capital_structure': {'beta': 1.11},
            },
            'modeling_metrics': {'financial_ratios': {'financial_profile': {
                'interest_income_to_revenue': 1.06,
            }}},
        }
        capm = {
            'risk_free_rate': 0.0471,
            'equity_risk_premium_total': 0.0443,
            'beta': 1.11,
        }
        override = build_bank_valuation_override(financial_data, 0.025, capm)

        assert override['valuation_method'] == 'justified_pb_roe'
        assert override['fair_value'] > 0
        assert override['current_price'] == 353.56
        assert override['bank_inputs']['cost_of_equity_source'].endswith('(CAPM build)')

    def test_low_interest_share_does_not_misclassify_a_payment_processor(self):
        from src.agents.fm.bank_valuation import build_bank_valuation_override

        financial_data = {
            'company_data': {
                'basic_info': {
                    'sector': 'Financial Services',
                    'industry': 'Credit Services',
                },
                'valuation_metrics': {'book_value': 20.0},
                'growth_profitability': {'return_on_equity': 0.20},
                'market_data': {'current_price': 80.0},
                'capital_structure': {'beta': 1.0},
            },
            'modeling_metrics': {'financial_ratios': {'financial_profile': {
                'interest_income_to_revenue': 0.02,
            }}},
        }

        assert build_bank_valuation_override(financial_data) is None

    def test_non_bank_data_is_untouched(self):
        from src.report_agent import apply_valuation_override
        d = self._data()
        assert apply_valuation_override(d, {'valuation_method': 'dcf', 'fair_value': 87.11}) is d
        assert d['valuation']['summary']['average_intrinsic'] == 0.0
        assert apply_valuation_override(d, None) is d

    def test_a_zero_bank_value_is_not_adopted(self):
        from src.report_agent import apply_valuation_override
        d = apply_valuation_override(self._data(), {'valuation_method': 'justified_pb_roe', 'fair_value': 0.0})
        assert 'bank' not in d['valuation']

    def test_the_summary_table_names_the_method(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=None)
        data['valuation']['bank'] = {'fair_value': 159.34, 'method': 'Justified P/B x ROE', 'inputs': {}}
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("c", 0.0))
        assert "| Justified P/B x ROE Intrinsic Value | $159.34 |" in text
        assert "not applied — balance-sheet financial" in text
        assert "**Intrinsic Value (justified P/B x ROE)**" in text

    def test_write_report_never_quotes_a_zero_dcf_for_a_bank(self):
        from src.agents.tools.analysis_tools import WriteReportTool
        source = inspect.getsource(WriteReportTool.execute)
        assert 'fair_value = vm.get("dcf_fair_value")' not in source
        assert "dcf_fair_value_cross_check" in source
        assert "_dcf > 0" in source


class TestUnreliableValuationReachesTheReport:
    OVERRIDE = {
        'valuation_method': 'dcf',
        'fair_value': 477.42,
        'perpetual_price': 188.30,
        'exit_multiple_price': 231.65,
        'comps_price': 744.86,
        'dispersion_band': 'unreliable',
        'dispersion_ratio': 3.956,
        'valuation_warning': 'UNRELIABLE VALUATION — METHODS CONTRADICT.',
    }

    def test_override_carries_the_dispersion_boundary(self):
        from src.report_agent import apply_valuation_override
        data = _valuation_data(comps=744.86)
        result = apply_valuation_override(data, self.OVERRIDE)
        reliability = result['valuation']['reliability']
        assert reliability['point_estimate_withheld'] is True
        assert reliability['range_low'] == 188.30
        assert reliability['range_high'] == 744.86
        # Kept internally for audit; downstream decides what may be published.
        assert result['valuation']['summary']['average_intrinsic'] == 87.11

    def test_dcf_only_megacap_publication_boundary_reaches_the_report(self):
        from src.report_agent import apply_valuation_override, generate_section_valuation
        reason = (
            "The DCF-only estimate is -50% from the market for a mega-cap, but "
            "no independent market-comps valuation was available."
        )
        override = {
            'valuation_method': 'dcf',
            'fair_value': 167.67,
            'perpetual_price': 151.66,
            'exit_multiple_price': 183.68,
            'comps_price': 0.0,
            'dispersion_band': 'single-method',
            'dispersion_ratio': 1.21,
            'point_estimate_withheld': True,
            'publication_withheld_reason': reason,
        }
        result = apply_valuation_override(_valuation_data(comps=None), override)
        reliability = result['valuation']['reliability']
        assert reliability['point_estimate_withheld'] is True
        assert reliability['withheld_reason'] == reason
        assert reliability['range_low'] == 151.66
        assert reliability['range_high'] == 183.68
        text, _ = generate_section_valuation(
            result, lambda messages, temperature=0.5: ("commentary", 0.0))
        assert "Withheld — DCF-only result lacks independent corroboration" in text
        assert "valuation methods do not converge" not in text

    def test_valuation_section_withholds_midpoint_and_upside(self):
        from src.report_agent import apply_valuation_override, generate_section_valuation
        data = apply_valuation_override(_valuation_data(comps=744.86), self.OVERRIDE)
        text, _ = generate_section_valuation(
            data, lambda messages, temperature=0.5: ("commentary", 0.0))
        assert "Point Estimate** | **Withheld" in text
        assert "Supported Valuation Range** | **$188.30 – $744.86" in text
        assert "not meaningful without a defensible point estimate" in text
        assert "UNRELIABLE VALUATION" in text
        assert "**$87.11**" not in text

    def test_thesis_prompt_never_receives_the_hidden_midpoint(self):
        from src.report_agent import apply_valuation_override, generate_section_investment_thesis
        seen = []
        data = apply_valuation_override(_valuation_data(comps=744.86), self.OVERRIDE)
        data['news'] = {'summary': {'overall_sentiment': 'neutral'}, 'catalysts': [], 'risks': []}
        generate_section_investment_thesis(
            data,
            lambda messages, temperature=0.6: (seen.append(messages[0]['content']) or "thesis", 0.0),
        )
        assert "point estimate withheld" in seen[0]
        assert "do not convert the valuation-range endpoints" in seen[0]
        assert "$87.11" not in seen[0]

    def test_code_assembly_keeps_the_marker_when_a_narrative_section_fails(self):
        from src.report_agent import apply_valuation_override, valuation_publication_status
        data = apply_valuation_override(_valuation_data(comps=744.86), self.OVERRIDE)
        status = valuation_publication_status(data)
        assert "**Valuation Confidence**: Unreliable" in status
        assert "**Point Estimate**: Withheld" in status
        assert "**Supported Valuation Range**: $188.30 – $744.86" in status
        assert "No directional rating" in status


class TestDepositaryReceiptGuard:
    """
    Toyota's ADR: yen financials, a dollar price, 1.3B ADRs — value per share
    ¥77,233 against $197, "+21,000%", STRONG BUY, live in production.
    """

    def test_guard_substitutes_only_when_it_resolves_the_mismatch(self):
        from src.agents.tools.analysis_tools import AgentContext
        source = inspect.getsource(AgentContext.ensure_state_for_ticker)
        assert 'info.get("currency") != info.get("financialCurrency")' in source
        assert 'cand.get("currency") != cand.get("financialCurrency")' in source
        assert '"." not in ticker' in source          # never fires on a home listing

    def test_price_is_converted_into_the_financial_currency(self, monkeypatch):
        import src.financial_scraper as fs
        monkeypatch.setattr(fs, "_fx_rate", lambda a, b: 156.15 if (a, b) == ("USD", "JPY") else None)
        info = {"currency": "USD", "financialCurrency": "JPY"}
        assert fs._price_in_financial_currency(197.11, info) == pytest.approx(197.11 * 156.15)
        assert fs._reporting_currency(info) == "JPY"
        assert fs._listing_ccy(info) == "USD"

    def test_no_rate_leaves_the_price_alone(self, monkeypatch):
        import src.financial_scraper as fs
        monkeypatch.setattr(fs, "_fx_rate", lambda a, b: None)
        info = {"currency": "USD", "financialCurrency": "CNY"}
        assert fs._price_in_financial_currency(120.25, info) == 120.25

    def test_same_currency_is_a_no_op(self):
        import src.financial_scraper as fs
        info = {"currency": "USD", "financialCurrency": "USD"}
        assert fs._price_in_financial_currency(319.97, info) == 319.97
        assert fs._fx_listing_to_financial(info) is None

    def test_pence_then_financial_currency(self, monkeypatch):
        """Shell: GBp quote, USD books. Pence -> pounds -> dollars."""
        import src.financial_scraper as fs
        monkeypatch.setattr(fs, "_fx_rate", lambda a, b: 1.351 if (a, b) == ("GBP", "USD") else None)
        info = {"currency": "GBp", "financialCurrency": "USD"}
        pounds = fs._price_in_major_units(3437.0, "GBp")
        assert fs._price_in_financial_currency(pounds, info) == pytest.approx(34.37 * 1.351)
        assert fs._reporting_currency(info) == "USD"


class TestMoneyFormattingFollowsTheReportCurrency:
    """
    format_number hardcoded "$". It went unnoticed because the LLM rewrote the
    symbol while echoing the tables; emitted verbatim, LVMH's projections read
    "$83.23B" and PC Jeweller's "$44.26B".
    """

    def test_euro_report(self):
        from src.report_agent import format_number, set_report_currency
        set_report_currency("EUR")
        try:
            assert format_number(83.23e9) == "€83.23B"
            assert format_number(459.35) == "€459.35"
        finally:
            set_report_currency(None)

    def test_rupee_report(self):
        from src.report_agent import format_number, set_report_currency
        set_report_currency("INR")
        try:
            assert format_number(44.26e9).startswith("₹")
        finally:
            set_report_currency(None)

    def test_dollar_when_unpinned(self):
        from src.report_agent import format_number, set_report_currency
        set_report_currency(None)
        assert format_number(1.5e6) == "$1.50M"


class TestWorkbookGridIsPresent:
    """
    The Aug 25 grid commit (b3f0f0d) reached the production image but never
    reached git main — `git push origin main` was run from the feature branch.
    Every branch cut from main since then lacked it, and merging one would have
    shipped a workbook with an empty grid. This pins the code's presence.
    """

    def test_grid_formulas_are_written(self):
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs", "tab_sensitivity.py"),
                      encoding="utf-8").read()
        assert "_value_per_share_formula" in source
        assert "_exit_value_per_share_formula" in source
        written = re.findall(r'value="([^"]*)"', source)
        assert not any(v.startswith("NOTE: Select") for v in written)


class TestNoGridForABank:
    def test_bank_valuation_has_no_dcf_grid(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=None)
        data['valuation']['bank'] = {'fair_value': 159.34, 'method': 'Justified P/B x ROE', 'inputs': {}}
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("c", 0.0))
        assert "Not applicable — valued on justified P/B x ROE" in text
        assert "terminal g" not in text


class TestConvertedPriceIsDisclosed:
    """
    Shell's report now prices in dollars against dollar statements. Without
    a note, "$46.43" is a number no London holder has seen; the quote is
    3,437p. The summary and the chat must both carry the original and the rate.
    """

    def test_summary_shows_the_listing_quote_and_rate(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=None)
        data['company_overview'].update({'currency': 'USD', 'listing_currency': 'GBP',
                                         'current_price_listing': 34.37, 'fx_listing_to_financial': 1.351})
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("c", 0.0))
        assert "| Price on the listing exchange | £34.37 (GBP, converted at 1.3510 USD/GBP) |" in text

    def test_no_row_when_currencies_match(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=None)
        data['company_overview'].update({'currency': 'USD', 'listing_currency': 'USD',
                                         'current_price_listing': 54.96, 'fx_listing_to_financial': None})
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("c", 0.0))
        assert "Price on the listing exchange" not in text

    def test_chat_note(self):
        from src.agents.tools.analysis_tools import _listing_price_note
        class _FD:
            key_metrics = {"basic_info": {"listing_currency": "GBP", "currency": "USD"},
                           "market_data": {"current_price_listing": 34.37, "fx_listing_to_financial": 1.351}}
        class _S:
            financial_data = _FD()
        note = _listing_price_note(_S())
        assert note["listing_currency"] == "GBP"
        assert note["price_in_listing_currency"] == 34.37
        assert "converted at 1.3510 USD/GBP" in note["currency_note"]

    def test_chat_note_absent_when_matching(self):
        from src.agents.tools.analysis_tools import _listing_price_note
        class _FD:
            key_metrics = {"basic_info": {"listing_currency": "USD", "currency": "USD"},
                           "market_data": {"current_price_listing": 54.96}}
        class _S:
            financial_data = _FD()
        assert _listing_price_note(_S()) == {}
