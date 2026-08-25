"""
The discount rate must be derived, and the derivation must be visible.

THE BUG. A user compared our LVMH report against one a frontier model wrote.
Ours said SELL at EUR 390; theirs said HOLD at EUR 480 against a EUR 452.50
market price. The entire disagreement was the discount rate.

src/agents/fm/tabs/tab_assumptions.py wrote literal constants into the cells the
DCF reads — Rf 4.5%, ERP 6.5%, levered beta 1.2, Kd 5.5%, equity weight 85% —
for every company on earth. LVMH's observed beta is 0.84 and it is a euro
issuer, so its risk-free rate is the Bund, not a US Treasury. Those constants
produced a WACC of 11.01% and a fair value of EUR 269 on projections that return
roughly EUR 433 at 8%.

Two aggravating facts. compute_capm_wacc already derived a defensible 8.57% and
threw the components away, so nothing could be written into the cells. And the
report PRINTED that derived rate while the workbook discounted at 11.01% — the
reader was shown a number the model never used.

Run:  python -m pytest tests/test_cost_of_capital.py -q
"""

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "src"))

from src.agents.fm.assumption_grounding import (
    capm_components,
    compute_capm_wacc,
    risk_free_rate,
    _RF_STATIC,
)

# LVMH as scraped, the run that exposed this.
LVMH = {
    "basic_info": {"currency": "EUR"},
    "capital_structure": {"beta": 0.842, "total_debt": 36_731_000_000},
    "market_data": {"market_cap": 226_443_575_296},
    "growth_profitability": {},
}
US_MEGACAP = {
    "basic_info": {"currency": "USD"},
    "capital_structure": {"beta": 1.05, "total_debt": 30_000_000_000},
    "market_data": {"market_cap": 3_000_000_000_000},
    "growth_profitability": {},
}


class TestRiskFreeByCurrency:
    def test_euro_issuer_does_not_get_a_us_treasury(self):
        """
        Discounting euro cash flows at a US Treasury yield is a currency
        mismatch in the cost of capital — the same class of error as quoting a
        EUR company in dollars.
        """
        rate, source = risk_free_rate("EUR")
        assert rate == _RF_STATIC["EUR"][0]
        assert "Bund" in source

    def test_dated_rates_disclose_their_date(self):
        """
        yfinance carries no non-US sovereign yield (^GDBR10, DE10Y-DE,
        GB10YT=RR and every variant 404) and no FRED key is configured, so
        non-USD rates are dated figures. A stale rate a reader can see beats a
        live US rate silently applied to a euro company.
        """
        _, source = risk_free_rate("EUR")
        assert "as of" in source

    def test_unknown_currency_is_labelled_a_proxy_not_passed_off_as_local(self):
        rate, source = risk_free_rate("SEK")
        assert rate > 0
        assert "proxy" in source.lower()
        assert "SEK" in source

    def test_operator_can_override_without_a_deploy(self, monkeypatch):
        monkeypatch.setenv("RISK_FREE_EUR", "0.0290")
        rate, source = risk_free_rate("EUR")
        assert rate == pytest.approx(0.0290)
        assert "override" in source

    def test_a_nonsense_override_is_ignored(self, monkeypatch):
        monkeypatch.setenv("RISK_FREE_EUR", "not-a-number")
        rate, _ = risk_free_rate("EUR")
        assert rate == _RF_STATIC["EUR"][0]

    def test_missing_currency_defaults_to_usd(self):
        _, source = risk_free_rate(None)
        assert "US 10Y" in source


class TestCapmBuild:
    def test_it_returns_the_derivation_not_just_the_answer(self):
        """
        The components existed as locals and were discarded, which is why the
        workbook had to invent its own constants.
        """
        c = capm_components(LVMH)
        for key in ("risk_free_rate", "risk_free_source", "beta", "beta_source",
                    "equity_risk_premium", "cost_of_equity", "pre_tax_cost_of_debt",
                    "after_tax_cost_of_debt", "equity_weight", "debt_weight", "wacc"):
            assert key in c, key

    def test_beta_is_the_company_s_own_not_1_point_2(self):
        c = capm_components(LVMH)
        # Blume: 0.67 * 0.842 + 0.33
        assert c["beta"] == pytest.approx(0.67 * 0.842 + 0.33, abs=1e-6)
        assert "0.84" in c["beta_source"]

    def test_a_low_beta_euro_issuer_is_not_discounted_at_eleven_percent(self):
        """The shipped model returned 11.01% here and a EUR 269 fair value."""
        c = capm_components(LVMH)
        assert 0.065 <= c["wacc"] <= 0.090, c["wacc"]

    def test_weights_come_from_the_actual_capital_structure(self):
        c = capm_components(LVMH)
        expected_w_d = 36_731_000_000 / (226_443_575_296 + 36_731_000_000)
        assert c["debt_weight"] == pytest.approx(expected_w_d, abs=1e-6)
        assert c["equity_weight"] + c["debt_weight"] == pytest.approx(1.0)

    def test_a_us_company_still_gets_a_us_risk_free(self):
        c = capm_components(US_MEGACAP)
        assert c["currency"] == "USD"
        assert "US 10Y" in c["risk_free_source"]

    def test_missing_beta_falls_back_to_the_market(self):
        c = capm_components({"basic_info": {"currency": "USD"},
                             "capital_structure": {}, "market_data": {}})
        assert c["beta"] == 1.0
        assert "no observed beta" in c["beta_source"]

    def test_the_note_still_works_for_existing_callers(self):
        wacc, note = compute_capm_wacc(LVMH)
        assert 0.0 < wacc < 0.2
        assert "CAPM WACC" in note

    def test_clamping_is_disclosed(self):
        """A clamped WACC is a modelling decision, not a derivation."""
        wild = {"basic_info": {"currency": "USD"},
                "capital_structure": {"beta": 5.0, "total_debt": 0},
                "market_data": {"market_cap": 1_000_000_000}}
        c = capm_components(wild)
        if c["wacc_clamped"]:
            _, note = compute_capm_wacc(wild)
            assert "clamped" in note


class TestWorkbookUsesTheDerivation:
    def test_the_assumptions_tab_no_longer_hardcodes_capm_inputs(self):
        """The literals that produced 11.01% for every company on earth."""
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs",
                                   "tab_assumptions.py"), encoding="utf-8").read()
        dcf_block = source[source.index("_setup_dcf_parameters"):]
        for literal in ("value=0.045", "value=0.065", "value=1.2", "value=0.055",
                        "value=0.85"):
            assert literal not in dcf_block, literal

    def test_the_assumptions_tab_reads_the_capm_build(self):
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs",
                                   "tab_assumptions.py"), encoding="utf-8").read()
        assert 'self.llm_assumptions.get("capm")' in source

    def test_grounding_publishes_the_build_for_the_workbook(self):
        import inspect
        from src.agents.fm import assumption_grounding
        source = inspect.getsource(assumption_grounding.ground_assumptions)
        assert 'a["capm"] = capm' in source

    def test_seeded_cells_reproduce_the_derived_wacc(self):
        """
        The workbook computes Ke = Rf + beta*ERP and blends it with after-tax Kd
        at the capital-structure weights. Seeding those five cells must land on
        the same WACC the grounding computed, or the workbook and the report
        disagree again.
        """
        c = capm_components(LVMH)
        ke = c["risk_free_rate"] + c["beta"] * c["equity_risk_premium"]
        rebuilt = (c["equity_weight"] * ke
                   + c["debt_weight"] * c["after_tax_cost_of_debt"])
        assert rebuilt == pytest.approx(c["wacc"], abs=1e-6)


class TestLeasesAreNotChargedTwice:
    def test_fcf_does_not_deduct_lease_repayments(self):
        """
        A tempting fix that is wrong here. This model treats leases as debt: it
        adds back total D&A (including right-of-use depreciation) and its equity
        bridge deducts balance-sheet Total Debt, which INCLUDES capital lease
        obligations — EUR 16.4bn of LVMH's EUR 36.7bn. Deducting lease principal
        from the cash flow as well charges the same obligation twice.
        """
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs",
                                   "tab_projections.py"), encoding="utf-8").read()
        fcf = source[source.index("def _setup_fcf_row"):
                     source.index("def _setup_analytics_section")]
        assert "Assumptions!$B$32" not in fcf
        assert "leases as debt" in fcf

    def test_the_equity_bridge_still_deducts_total_debt(self):
        """The other half of the convention. If this changes, the FCF must too."""
        source = open(os.path.join(_ROOT, "src", "agents", "fm", "tabs",
                                   "tab_valuation_perpetual_growth_dcf.py"),
                      encoding="utf-8").read()
        assert "Total Debt" in source


class TestReportShowsTheDerivation:
    """
    The report printed a bare WACC and asserted it was reasonable. Worse, it
    printed LLM_Inferred's rate while the workbook discounted with the
    Assumptions cells — one number shown, another used.
    """

    def _computed(self):
        return {
            'Valuation (DCF)': {'cells': {
                '(3, 2)': 0.0324, '(4, 2)': 0.055, '(5, 2)': 0.894,
                '(6, 2)': 0.0816, '(7, 2)': 0.0474, '(8, 2)': 0.3279,
                '(9, 2)': 0.0319, '(10, 2)': 0.8604, '(11, 2)': 0.1396,
                '(12, 2)': 0.0746,
            }}
        }

    def test_reads_the_rate_the_dcf_actually_used(self):
        from src.report_agent import extract_cost_of_capital
        coc = extract_cost_of_capital(self._computed())
        assert coc['wacc'] == pytest.approx(0.0746)
        assert coc['risk_free_rate'] == pytest.approx(0.0324)
        assert coc['beta'] == pytest.approx(0.894)

    def test_missing_tab_degrades_quietly(self):
        from src.report_agent import extract_cost_of_capital
        coc = extract_cost_of_capital({})
        assert coc['wacc'] is None

    def test_non_numeric_cells_are_dropped(self):
        from src.report_agent import extract_cost_of_capital
        coc = extract_cost_of_capital(
            {'Valuation (DCF)': {'cells': {'(12, 2)': 'A. WACC CALCULATION'}}})
        assert coc['wacc'] is None


class TestSensitivityGrid:
    PROJECTIONS = {'fcf': [15.34e9, 14.93e9, 14.35e9, 13.71e9, 12.96e9]}
    VALUATION = {'dcf_perpetual': {
        'enterprise_value': 145.7e9,
        'equity_value': 131.3e9,
        'intrinsic_value_per_share': 263.7,
    }}

    def _grid(self, wacc=0.0746, g=0.025):
        from src.report_agent import build_sensitivity_grid
        return build_sensitivity_grid(self.PROJECTIONS, g, self.VALUATION, wacc)

    def test_the_grid_is_recomputed_not_read_from_the_workbook(self):
        """
        The Sensitivity tab exists but its interior cells carry formatting and
        no values, so there is nothing to read back.
        """
        grid = self._grid()
        assert grid
        assert grid.count("\n") >= 6          # header, rule, five rows

    def test_the_base_case_row_is_marked(self):
        grid = self._grid(wacc=0.0746)
        assert "**7.46%**" in grid

    def test_value_falls_as_the_discount_rate_rises(self):
        grid = self._grid()
        rows = [r for r in grid.splitlines() if r.startswith("|") and "%" in r][1:]
        first = int(rows[0].split("|")[3].strip().replace(",", ""))
        last = int(rows[-1].split("|")[3].strip().replace(",", ""))
        assert last < first

    def test_a_diverging_terminal_value_is_marked_not_printed(self):
        """g >= WACC makes the Gordon formula meaningless, not merely large."""
        grid = self._grid(wacc=0.03, g=0.035)
        assert "n/m" in grid

    def test_missing_inputs_yield_no_grid_rather_than_a_wrong_one(self):
        from src.report_agent import build_sensitivity_grid
        assert build_sensitivity_grid({'fcf': []}, 0.025, self.VALUATION, 0.08) == ""
        assert build_sensitivity_grid(self.PROJECTIONS, 0.025, {}, 0.08) == ""

    def test_the_prompt_asks_which_input_dominates(self):
        """
        The point of the grid: on these projections the value moves far more per
        50bp of WACC than per point of growth, and the reader should be told.
        """
        prompt = open(os.path.join(_ROOT, "prompts", "report_valuation.md"),
                      encoding="utf-8").read()
        assert "{cost_of_capital_table}" in prompt
        assert "{sensitivity_table}" in prompt
        assert "most sensitive" in prompt


class TestReportAssemblyRuns:
    """
    Two NameErrors shipped from this area in one day: `validation_report` in the
    recommendation formatter (eleven days live, hidden by a bare except), and a
    reference to `assumptions` in integrate_report_sections placed a hundred
    lines above where that local is bound.

    Source inspection catches neither reliably. Assembling a report does.
    """

    def _data(self):
        five = [0.03, 0.028, 0.026, 0.024, 0.022]
        return {
            'company_overview': {
                'company_name': 'LVMH', 'ticker': 'MC.PA', 'sector': 'Consumer Cyclical',
                'industry': 'Luxury Goods', 'current_price': 459.35,
                'market_cap': 226_443_575_296, 'currency': 'EUR',
                'exchange': 'PAR', 'country': 'France', 'website': 'https://lvmh.com',
                'employees': 211_000, 'business_summary': 'Luxury goods group.',
            },
            'historical': {'years': ['2023', '2024', '2025'], 'revenue': [86.2e9, 84.7e9, 80.8e9],
                           'gross_profit': [0, 0, 0], 'operating_income': [0, 0, 0],
                           'net_income': [0, 0, 0], 'ebitda': [0, 0, 0],
                           'free_cash_flow': [0, 0, 0]},
            'assumptions': {
                'wacc': 0.0857, 'terminal_growth': 0.025,
                'revenue_growth_rates': five, 'gross_margins': five,
                'ebitda_margins': five, 'operating_margins': five,
            },
            'cost_of_capital': {
                'risk_free_rate': 0.0324, 'equity_risk_premium': 0.055, 'beta': 0.894,
                'cost_of_equity': 0.0816, 'pre_tax_cost_of_debt': 0.0474,
                'tax_rate': 0.3279, 'after_tax_cost_of_debt': 0.0319,
                'equity_weight': 0.8591, 'debt_weight': 0.1409, 'wacc': 0.0746,
            },
            'projections': {
                'revenue': [83.2e9] * 5, 'ebitda': [26.6e9] * 5,
                'fcf': [15.34e9, 14.93e9, 14.35e9, 13.71e9, 12.96e9],
                'ebit': [18.4e9] * 5, 'nopat': [12.4e9] * 5,
            },
            'valuation': {
                'dcf_perpetual': {'pv_fcfs': 83.6e9, 'terminal_value': 176.6e9,
                                  'enterprise_value': 247.3e9, 'equity_value': 232.8e9,
                                  'intrinsic_value_per_share': 467.58},
                'dcf_exit': {'terminal_ev': 200e9, 'enterprise_value': 240e9,
                             'equity_value': 225e9, 'intrinsic_value_per_share': 452.0,
                             'exit_multiple': 12.0},
                'summary': {'dcf_intrinsic': 467.58, 'exit_intrinsic': 452.0,
                            'average_intrinsic': 459.79, 'upside': 0.018,
                            'shares_outstanding': 497_976_118, 'cash': 8.79e9,
                            'debt': 36.73e9, 'net_debt': 27.94e9},
            },
            'news': {
                'summary': {'articles_analyzed': 6, 'overall_sentiment': 'neutral',
                            'confidence_score': 0.6},
                'articles': [], 'catalysts': [], 'risks': [], 'evidence': [],
                'mitigations': [], 'themes': [],
            },
        }

    def _sections(self):
        keys = ('executive_summary', 'company_overview', 'financial_performance',
                'valuation', 'news_analysis', 'investment_thesis', 'recommendation')
        return {k: f"_{k} body_" for k in keys}

    def test_it_assembles_without_raising(self):
        from src.report_agent import integrate_report_sections
        report = integrate_report_sections(self._sections(), self._data())
        assert isinstance(report, str) and len(report) > 500

    def test_the_appendix_quotes_the_rate_the_dcf_used(self):
        """
        It printed assumptions['wacc'] — a different tab's number. On a shipped
        AAPL report that was 8.5% against a model discounting at 11.15%.
        """
        from src.report_agent import integrate_report_sections
        report = integrate_report_sections(self._sections(), self._data())
        assert "| WACC | 7.5%" in report or "| WACC | 7.46%" in report
        assert "8.6%" not in report.split("### C. Key Model Assumptions")[-1]

    def test_it_survives_a_model_with_no_cost_of_capital(self):
        """Older runs and degraded models have no such key."""
        from src.report_agent import integrate_report_sections
        data = self._data()
        data.pop('cost_of_capital')
        report = integrate_report_sections(self._sections(), data)
        assert "| WACC |" in report
