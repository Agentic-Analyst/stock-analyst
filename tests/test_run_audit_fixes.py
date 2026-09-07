"""
Defects found by auditing the four most recent external runs (Sep 3-5, 2026).

Each class names the run that exposed it. These are the first real runs after
the Aug 24-25 deploys, and they showed that work holding — home-listing
resolution, currency, the recommendation section rendering, rating agreement —
while surfacing what it had not touched, and two things it had got wrong.

Run:  python -m pytest tests/test_run_audit_fixes.py -q
"""

import inspect
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
    ($87.11). The chat told a user who asked for a DCF that one was not used.
    """

    def test_payments_and_fintech_are_not_banks(self):
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Financial Services", "Credit Services") is False   # PayPal
        assert is_financial_sector("Financial Services", "Capital Markets") is False   # Coinbase, exchanges
        assert is_financial_sector("Financial Services", "Asset Management") is False
        assert is_financial_sector("Financial Services", "Financial Data & Stock Exchanges") is False

    def test_banks_and_insurers_still_qualify(self):
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Financial Services", "Banks—Regional") is True
        assert is_financial_sector("Financial Services", "Banks—Diversified") is True
        assert is_financial_sector("Financial Services", "Insurance—Life") is True
        assert is_financial_sector("Financial Services", "Insurance—Reinsurance") is True

    def test_sector_alone_is_not_enough(self):
        from src.agents.fm.bank_valuation import is_financial_sector
        assert is_financial_sector("Financial Services", None) is False
        assert is_financial_sector("Financial Services", "") is False


class TestChatQuotesTheReportsFairValue:
    """
    Even when the balance-sheet method legitimately fires, the report is built
    from the workbook DCF. The chat must quote the number the document shows.
    """

    def test_write_report_prefers_the_dcf_number_when_overridden(self):
        from src.agents.tools.analysis_tools import WriteReportTool
        source = inspect.getsource(WriteReportTool.execute)
        assert 'fair_value = vm.get("dcf_fair_value")' in source
        assert "bank_fair_value_cross_check" in source

    def test_the_override_logic(self):
        vm = {"fair_value": 61.01, "dcf_fair_value": 87.11, "current_price": 54.93,
              "valuation_method": "justified_pb_roe", "upside_vs_market": 0.111}
        fair_value, upside, method = vm["fair_value"], vm["upside_vs_market"], vm["valuation_method"]
        bank_fair_value = None
        if vm.get("dcf_fair_value") is not None and method == "justified_pb_roe":
            bank_fair_value = fair_value
            fair_value = vm.get("dcf_fair_value")
            price = vm.get("current_price")
            upside = (float(fair_value) / float(price) - 1.0) if price and fair_value else upside
        assert fair_value == 87.11
        assert bank_fair_value == 61.01
        assert upside == pytest.approx(0.586, abs=0.001)


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
        assert "| Market Comps Intrinsic Value | $73.41 |" in text
        assert "Average Intrinsic Value (3 methods)" in text

    def test_no_comps_no_phantom_row(self):
        from src.report_agent import generate_section_valuation
        data = _valuation_data(comps=None)
        text, _ = generate_section_valuation(data, lambda m, temperature=0.5: ("commentary", 0.0))
        assert "Market Comps" not in text
        assert "| **Average Intrinsic Value** |" in text


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
