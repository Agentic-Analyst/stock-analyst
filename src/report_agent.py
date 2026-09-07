#!/usr/bin/env python3
"""
report_agent.py - Professional Financial Report Generator (V2)

Generates comprehensive, institutional-quality financial analyst reports by:
1. Loading data from JSON files (no more open_excel dependency)
2. Extracting company data, financial model results, and news analysis
3. Using LLM to synthesize all data into a professional markdown report

Data Sources:
- financial_json: financials_annual_modeling_latest.json (company info, historical data)
- computed_values_json: *_computed_values.json (evaluated financial model)
- screening_json: screening_data.json (news catalysts, risks, mitigations)

Output: Professional analyst report in markdown format
"""

from __future__ import annotations
import asyncio
import contextvars
# Used by _strip_echoed_heading. Its absence broke EVERY report for one
# deploy: the helper referenced `re` at call time and the module never
# imported it.
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json

from llms.config import get_llm
from logger import StockAnalystLogger
from recommendation_engine import RecommendationEngineV3


# Free-text output language for the report narrative. Set once per report run
# (from the user's request, e.g. "Chinese", "日本語", "Spanish"). Empty/"English"
# means no directive. A contextvar avoids threading a param through ~10 nested
# report functions and keeps the change generalizable — ANY language works, no
# enum. load_prompt() appends the directive to every section prompt so all
# LLM-written sections honor it automatically.
_OUTPUT_LANGUAGE: contextvars.ContextVar[str] = contextvars.ContextVar("report_output_language", default="")


def set_report_language(language: Optional[str]) -> None:
    """Set the target output language for the current report run (best-effort)."""
    lang = (language or "").strip()
    # Treat English (the template default) as "no directive".
    if lang.lower() in ("", "english", "en", "en-us", "default"):
        _OUTPUT_LANGUAGE.set("")
    else:
        _OUTPUT_LANGUAGE.set(lang)


def _language_directive() -> str:
    """Instruction appended to each section prompt so the LLM writes in the
    requested language. Numbers, tickers, and cited figures stay as-is."""
    lang = _OUTPUT_LANGUAGE.get()
    if not lang:
        return ""
    return (
        f"\n\n---\nIMPORTANT: Write your ENTIRE response in {lang}. Translate all "
        f"prose, section prose, and analysis into {lang}. Keep tickers, currency "
        f"symbols, and numeric values exactly as given (do not translate or convert "
        f"numbers). If a table's column labels were provided in English, you may keep "
        f"them or translate them, but keep the data values unchanged."
    )


# Listing currency for the current report run. Same contextvar pattern as the
# output language directly above, and for the same reason: threading a param
# through ~10 nested report functions is worse than one run-scoped value that
# load_prompt() appends to every section prompt.
#
# Without this the writer had no idea what currency it was reporting in and
# defaulted to dollars for everything. A real LVMH request — a EUR listing,
# with a brief that said "use EUR" — produced a report containing 500 "$" and
# not a single "€". Every figure in it was mislabelled.
_REPORT_CURRENCY: contextvars.ContextVar[str] = contextvars.ContextVar("report_currency", default="")


def set_report_currency(code: Optional[str]) -> None:
    """Set the listing currency for the current report run (best-effort)."""
    _REPORT_CURRENCY.set((code or "").strip())


def _currency_directive() -> str:
    """Instruction appended to each section prompt so every figure the LLM
    writes carries the listing's own currency rather than a default dollar."""
    code = _REPORT_CURRENCY.get()
    if not code or code.upper() == "USD":
        # USD needs no directive: it is what the prompts already assume.
        return ""
    sym = currency_symbol(code)
    return (
        f"\n\n---\nCURRENCY: this company reports and trades in {code}. Every "
        f"monetary figure you write MUST use {code} (symbol \"{sym.strip()}\"). Do NOT "
        f"write \"$\" and do NOT convert values into dollars — the figures you have "
        f"been given are already in {code}. Prices, market cap, revenue, targets and "
        f"table cells all follow this."
    )


# The user's own framing for this report — persona, title, the sections they
# asked for, what to emphasise. Same contextvar mechanism as language and
# currency above.
#
# Without it, write_report took only {ticker, output_language} and the brief
# never reached the writer at all. A user asked for a ~10-page sell-side
# initiation on LVMH with a specific title and ten named sections, and received
# the stock template: no title, none of the requested structure. The brief
# steered the chat answer and nothing else, so the downloadable artifact — the
# part a professional would actually keep — ignored the request entirely.
#
# HARD BOUNDARY: the brief may shape STRUCTURE, EMPHASIS and TONE. It may not
# change a number. Every figure still comes from the model and the calculator,
# and the validator still rejects any the engine did not compute. A brief that
# says "target 800" must not produce one.
_REPORT_BRIEF: contextvars.ContextVar[str] = contextvars.ContextVar("report_brief", default="")

# Long enough for a detailed brief, short enough that it cannot dominate a
# section prompt or blow up token cost across ~8 parallel sections.
_BRIEF_MAX_CHARS = 2000


def set_report_brief(brief: Optional[str]) -> None:
    """Set the user's framing for the current report run (best-effort)."""
    _REPORT_BRIEF.set((brief or "").strip()[:_BRIEF_MAX_CHARS])


def _brief_directive() -> str:
    """Instruction appended to each section prompt carrying the user's brief."""
    brief = _REPORT_BRIEF.get()
    if not brief:
        return ""
    return (
        "\n\n---\nUSER BRIEF for this report. Follow it for STRUCTURE, EMPHASIS and "
        "TONE — the section's framing, what to foreground, the register to write in, "
        "and any title or headings requested:\n\n"
        f"{brief}\n\n"
        "STRICT LIMITS. Do NOT invent, alter or round any figure to satisfy the "
        "brief; every number is supplied to you and is computed elsewhere. If the "
        "brief asks for data you were not given, say it is unavailable rather than "
        "estimating it. If the brief asks for a specific rating or price target, "
        "IGNORE that instruction — the recommendation is derived from the model, not "
        "requested. Cover only what belongs in THIS section; other sections handle "
        "the rest of the brief. Do NOT restate the report title and do NOT open with a "
        "top-level '#' heading — you are writing ONE SECTION of a document that "
        "already has its title and its section heading."
    )


def load_prompt(prompt_name: str) -> str:
    """Load a prompt template from the prompts folder.

    Args:
        prompt_name: Name of the prompt file (without .md extension)

    Returns:
        Prompt template string (with a language directive appended when the
        current report run requested a non-English output language)
    """
    prompt_path = Path(__file__).parent.parent / "prompts" / f"{prompt_name}.md"
    with open(prompt_path, 'r') as f:
        template = f.read()
    return template + _currency_directive() + _brief_directive() + _language_directive()


def load_financial_json(json_path: Path) -> Dict[str, Any]:
    """Load financial data JSON."""
    with open(json_path, 'r') as f:
        return json.load(f)


def load_computed_values_json(json_path: Path) -> Dict[str, Any]:
    """Load computed values JSON from formula_evaluator."""
    with open(json_path, 'r') as f:
        return json.load(f)


def load_screening_json(json_path: Path) -> Dict[str, Any]:
    """Load screening data JSON."""
    with open(json_path, 'r') as f:
        return json.load(f)


def extract_company_overview(financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract company overview from financial JSON."""
    company_data = financial_data.get('company_data', {})
    basic_info = company_data.get('basic_info', {})
    market_data = company_data.get('market_data', {})
    valuation_metrics = company_data.get('valuation_metrics', {})
    capital_structure = company_data.get('capital_structure', {})
    growth_profitability = company_data.get('growth_profitability', {})
    forward_guidance = company_data.get('forward_guidance', {})
    
    return {
        'ticker': financial_data.get('ticker', 'N/A'),
        'company_name': basic_info.get('long_name', 'Unknown Company'),
        'sector': basic_info.get('sector', 'N/A'),
        'industry': basic_info.get('industry', 'N/A'),
        'description': basic_info.get('business_summary', ''),
        'website': basic_info.get('website', ''),
        'employees': basic_info.get('employees', 0),
        'country': basic_info.get('country', 'N/A'),
        'exchange': basic_info.get('exchange', 'N/A'),
        # The listing currency. Captured by the scraper all along and never
        # read here, so every report denominated a foreign listing in dollars:
        # an LVMH report came back with 500 "$" and not one "€", against a
        # brief that explicitly said EUR.
        'currency': basic_info.get('currency') or 'USD',
        # The listing's own quote, when it differs from the reporting currency:
        # Shell trades at 3,437p in London and reports in dollars, so the
        # valuation is in USD and the price was converted to match. A reader
        # is told both numbers and the rate, or the "$46.43" looks invented.
        'listing_currency': basic_info.get('listing_currency') or basic_info.get('currency') or 'USD',
        'current_price_listing': market_data.get('current_price_listing'),
        'fx_listing_to_financial': market_data.get('fx_listing_to_financial'),
        'current_price': market_data.get('current_price', 0),
        'market_cap': market_data.get('market_cap', 0),
        'enterprise_value': market_data.get('enterprise_value', 0),
        'shares_outstanding': market_data.get('shares_outstanding_basic', 0),
        'week_52_high': market_data.get('52_week_high', 0),
        'week_52_low': market_data.get('52_week_low', 0),
        'pe_trailing': valuation_metrics.get('pe_ratio_trailing', 0),
        'pe_forward': valuation_metrics.get('pe_ratio_forward', 0),
        'price_to_book': valuation_metrics.get('price_to_book', 0),
        'price_to_sales': valuation_metrics.get('price_to_sales', 0),
        'ev_to_revenue': valuation_metrics.get('enterprise_to_revenue', 0),
        'ev_to_ebitda': valuation_metrics.get('enterprise_to_ebitda', 0),
        'total_debt': capital_structure.get('total_debt', 0),
        'total_cash': capital_structure.get('total_cash', 0),
        'net_debt': capital_structure.get('net_debt', 0),
        'debt_to_equity': capital_structure.get('debt_to_equity', 0),
        'current_ratio': capital_structure.get('current_ratio', 0),
        'quick_ratio': capital_structure.get('quick_ratio', 0),
        'beta': capital_structure.get('beta', 0),
        'gross_margin': growth_profitability.get('gross_margins', 0),
        'operating_margin': growth_profitability.get('operating_margins', 0),
        'ebitda_margin': growth_profitability.get('ebitda_margins', 0),
        'net_margin': growth_profitability.get('profit_margins', 0),
        'roe': growth_profitability.get('return_on_equity', 0),
        'roa': growth_profitability.get('return_on_assets', 0),
        'revenue_growth': growth_profitability.get('revenue_growth', 0),
        'earnings_growth': growth_profitability.get('earnings_growth', 0),
        'dividend_yield': market_data.get('dividend_yield', 0),
        'target_mean_price': forward_guidance.get('target_mean_price', 0),
        'target_high_price': forward_guidance.get('target_high_price', 0),
        'target_low_price': forward_guidance.get('target_low_price', 0),
        'recommendation': forward_guidance.get('recommendation_key', 'N/A'),
        'num_analysts': forward_guidance.get('number_of_analyst_opinions', 0),
    }


def extract_historical_financials(financial_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract 5-year historical financial statements."""
    statements = financial_data.get('financial_statements', {})
    income_statement = statements.get('income_statement', {})
    balance_sheet = statements.get('balance_sheet', {})
    cash_flow = statements.get('cash_flow', {})
    
    # Get years (sorted from oldest to newest)
    years = sorted(income_statement.keys())
    
    historical = {
        'years': years,
        'revenue': [],
        'gross_profit': [],
        'operating_income': [],
        'ebitda': [],
        'net_income': [],
        'operating_cf': [],
        'capex': [],
        'fcf': [],
        'total_assets': [],
        'total_equity': [],
        'cash': [],
        'debt': [],
    }
    
    for year in years:
        is_data = income_statement.get(year, {})
        bs_data = balance_sheet.get(year, {})
        cf_data = cash_flow.get(year, {})
        
        historical['revenue'].append(is_data.get('Total Revenue', 0) or is_data.get('Operating Revenue', 0))
        historical['gross_profit'].append(is_data.get('Gross Profit', 0))
        historical['operating_income'].append(is_data.get('Operating Income', 0))
        historical['ebitda'].append(is_data.get('EBITDA', 0))
        historical['net_income'].append(is_data.get('Net Income', 0))
        historical['operating_cf'].append(cf_data.get('Operating Cash Flow', 0))
        historical['capex'].append(cf_data.get('Capital Expenditure', 0))
        historical['fcf'].append(cf_data.get('Free Cash Flow', 0))
        historical['total_assets'].append(bs_data.get('Total Assets', 0))
        historical['total_equity'].append(bs_data.get('Stockholders Equity', 0))
        historical['cash'].append(bs_data.get('Cash And Cash Equivalents', 0))
        historical['debt'].append(bs_data.get('Total Debt', 0))
    
    return historical


def extract_model_assumptions(computed_values: Dict[str, Any]) -> Dict[str, Any]:
    """Extract model assumptions from LLM_Inferred tab."""
    llm_inferred = computed_values.get('LLM_Inferred', {}).get('cells', {})
    
    return {
        'wacc': llm_inferred.get('(2, 2)', 0.09),
        'terminal_growth': llm_inferred.get('(3, 2)', 0.025),
        'revenue_growth_rates': [
            llm_inferred.get('(4, 2)', 0),
            llm_inferred.get('(4, 3)', 0),
            llm_inferred.get('(4, 4)', 0),
            llm_inferred.get('(4, 5)', 0),
            llm_inferred.get('(4, 6)', 0),
        ],
        'gross_margins': [
            llm_inferred.get('(5, 2)', 0),
            llm_inferred.get('(5, 3)', 0),
            llm_inferred.get('(5, 4)', 0),
            llm_inferred.get('(5, 5)', 0),
            llm_inferred.get('(5, 6)', 0),
        ],
        'ebitda_margins': [
            llm_inferred.get('(6, 2)', 0),
            llm_inferred.get('(6, 3)', 0),
            llm_inferred.get('(6, 4)', 0),
            llm_inferred.get('(6, 5)', 0),
            llm_inferred.get('(6, 6)', 0),
        ],
        'operating_margins': [
            llm_inferred.get('(7, 2)', 0),
            llm_inferred.get('(7, 3)', 0),
            llm_inferred.get('(7, 4)', 0),
            llm_inferred.get('(7, 5)', 0),
            llm_inferred.get('(7, 6)', 0),
        ],
    }


def extract_cost_of_capital(computed_values: Dict[str, Any]) -> Dict[str, Any]:
    """
    The WACC build the DCF actually used, from the Valuation (DCF) tab.

    The report used to print `LLM_Inferred!(2,2)` — a rate the workbook did not
    discount with. The DCF tab computed its own from the Assumptions cells, so a
    reader was shown one number and sold a valuation built on another. These are
    the cells the DCF formulas reference, so what is printed is what was used.
    """
    cells = computed_values.get('Valuation (DCF)', {}).get('cells', {}) or {}

    # Index by the tab's own row LABELS, not by row number. The builder writes
    # the label in column 1 and the value in column 2; keying on position means
    # inserting a row in the tab silently reads the wrong number here, which is
    # the failure mode this whole section exists to stop. Row numbers remain a
    # fallback so models built before the labels existed still parse.
    by_label = {}
    for key, value in cells.items():
        try:
            row, col = eval(key)
        except Exception:
            continue
        if col != 1 or not isinstance(value, str):
            continue
        pair = cells.get(f'({row}, 2)')
        if isinstance(pair, (int, float)):
            by_label[value.strip().lower()] = pair

    def read(label: str, row: int):
        value = by_label.get(label.lower())
        if value is not None:
            return value
        fallback = cells.get(f'({row}, 2)')
        return fallback if isinstance(fallback, (int, float)) else None

    # Provenance lives in column 3 of the Assumptions tab — "[US 10Y 4.78% used
    # as a proxy — no INR sovereign yield source available]", "[Blume-adjusted
    # from observed 0.33]". It was written there and never printed, so a rupee
    # valuation discounted on a US Treasury said nothing about it.
    assumptions = computed_values.get('Assumptions', {}).get('cells', {}) or {}

    def note(row: int):
        value = assumptions.get(f'({row}, 3)')
        return value.strip('[] ') if isinstance(value, str) and value.strip() else None

    return {
        'risk_free_source': note(23),
        'erp_source': note(24),
        'beta_source': note(25),
        'kd_source': note(27),
        'terminal_growth_source': note(30),
        'risk_free_rate': read('Risk-Free Rate (Rf)', 3),
        'equity_risk_premium': read('Equity Risk Premium (ERP)', 4),
        'beta': read('Levered Beta (β)', 5),
        'cost_of_equity': read('Cost of Equity (Ke)', 6),
        'pre_tax_cost_of_debt': read('Pre-Tax Cost of Debt (Kd)', 7),
        'tax_rate': read('Tax Rate (T)', 8),
        'after_tax_cost_of_debt': read('After-Tax Cost of Debt', 9),
        'equity_weight': read('Equity Weight (E/V)', 10),
        'debt_weight': read('Debt Weight (D/V)', 11),
        'wacc': read('WACC', 12),
    }


def build_sensitivity_grid(projections: Dict[str, Any], terminal_growth: float,
                           valuation: Dict[str, Any], wacc: float) -> str:
    """
    Value per share across WACC and terminal growth, as markdown.

    Runs the SAME model as the headline. The first version recomputed from the
    five explicit projection years with a Gordon terminal on FY5, while the DCF
    tab discounts ten periods — FY1-5 plus a FY6-10 fade — before its terminal.
    For a flat cash-flow profile the difference was a rounding error; for a
    growing one it was not: Alnylam's report showed a grid centre of 287 two
    lines under a headline of $333.84. The workbook's own Sensitivity tab (which
    does carry values now) reproduces the headline exactly, and so must this.
    """
    try:
        inputs = valuation.get('dcf_inputs') or {}
        fcf = [float(x) for x in (inputs.get('fcf') or []) if isinstance(x, (int, float))]
        cash = float(inputs.get('cash') or 0)
        debt = float(inputs.get('debt') or 0)
        investments = float(inputs.get('investments') or 0)
        shares = float(inputs.get('shares') or 0)
        if len(fcf) < 5 or shares <= 0 or not wacc:
            return ""
    except (TypeError, ValueError):
        return ""

    n = len(fcf)
    waccs = [wacc + d for d in (-0.010, -0.005, 0.0, 0.005, 0.010)]
    # Two steps either side of the base case. The step shrinks when the base
    # growth is under 1% (a franc or yuan perpetuity capped at its risk-free
    # rate) so the axis never goes negative.
    step = 0.005 if terminal_growth >= 0.01 else max(terminal_growth / 2.0, 0.0)
    growths = ([terminal_growth + k * step for k in (-2, -1, 0, 1, 2)] if step > 0
               else [0.0, 0.005, 0.010, 0.015, 0.020])

    header = "| WACC \\ terminal g | " + " | ".join(f"{g*100:.1f}%" for g in growths) + " |\n"
    header += "|---" * (len(growths) + 1) + "|\n"

    rows = ""
    for w in waccs:
        cells = []
        for g in growths:
            if w <= g + 0.001:
                cells.append("n/m")      # terminal value diverges
                continue
            pv = sum(f / (1 + w) ** (i + 1) for i, f in enumerate(fcf))
            tv = fcf[-1] * (1 + g) / (w - g)
            value = (pv + tv / (1 + w) ** n + cash - debt + investments) / shares
            # Whole units for a $300 stock; two decimals for a ₹19 one, where
            # integer rounding would erase the very differences the grid exists
            # to show (PC Jeweller: every cell in a row read "19").
            cells.append(f"{value:,.2f}" if abs(value) < 100 else f"{value:,.0f}")
        label = f"**{w*100:.2f}%**" if abs(w - wacc) < 1e-9 else f"{w*100:.2f}%"
        rows += f"| {label} | " + " | ".join(cells) + " |\n"

    return header + rows


def apply_valuation_override(data: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Carry the model's balance-sheet valuation into the report.

    For a bank or lender the model replaces the FCF DCF with a justified
    P/B x ROE fair value in state — and left the workbook's DCF at zero. The
    report was built from the workbook alone, so it printed "DCF $0.00 /
    Average $0.00 / Implied Upside -100%" and rated Capital One and JPMorgan
    STRONG SELL, while the chat quoted $159.34 and $304.65 from the real
    method. Here the report's headline, its summary rows and the numbers the
    recommendation engine rates on are all set to the method actually used.
    """
    if not override or override.get("valuation_method") != "justified_pb_roe":
        return data
    fair_value = override.get("fair_value")
    if not isinstance(fair_value, (int, float)) or fair_value <= 0:
        return data
    v = data.get("valuation") or {}
    price = (data.get("company_overview") or {}).get("current_price") or override.get("current_price")
    upside = (fair_value / float(price) - 1.0) if price else override.get("upside_vs_market")
    v["bank"] = {
        "fair_value": fair_value,
        "method": "Justified P/B x ROE",
        "inputs": override.get("bank_inputs") or {},
    }
    # The engine and the summary must rate and print the same number.
    v.setdefault("dcf_perpetual", {})["intrinsic_value_per_share"] = fair_value
    v.setdefault("dcf_exit", {})["intrinsic_value_per_share"] = fair_value
    summary = v.setdefault("summary", {})
    summary["dcf_intrinsic"] = fair_value
    summary["exit_intrinsic"] = fair_value
    summary["comps_intrinsic"] = None
    summary["average_intrinsic"] = fair_value
    if upside is not None:
        summary["upside"] = upside
    data["valuation"] = v
    return data


def extract_projections(computed_values: Dict[str, Any]) -> Dict[str, Any]:
    """Extract 5-year projections from Projections tab."""
    projections = computed_values.get('Projections', {}).get('cells', {})
    
    return {
        'revenue': [
            projections.get('(3, 2)', 0),
            projections.get('(3, 3)', 0),
            projections.get('(3, 4)', 0),
            projections.get('(3, 5)', 0),
            projections.get('(3, 6)', 0),
        ],
        'gross_profit': [
            projections.get('(4, 2)', 0),
            projections.get('(4, 3)', 0),
            projections.get('(4, 4)', 0),
            projections.get('(4, 5)', 0),
            projections.get('(4, 6)', 0),
        ],
        'ebitda': [
            projections.get('(21, 2)', 0),
            projections.get('(21, 3)', 0),
            projections.get('(21, 4)', 0),
            projections.get('(21, 5)', 0),
            projections.get('(21, 6)', 0),
        ],
        'fcf': [
            projections.get('(19, 2)', 0),
            projections.get('(19, 3)', 0),
            projections.get('(19, 4)', 0),
            projections.get('(19, 5)', 0),
            projections.get('(19, 6)', 0),
        ],
    }


def extract_valuation(computed_values: Dict[str, Any]) -> Dict[str, Any]:
    """Extract valuation results from Summary and Valuation tabs."""
    summary = computed_values.get('Summary', {}).get('cells', {})
    dcf_tab = computed_values.get('Valuation (DCF)', {}).get('cells', {})
    exit_tab = computed_values.get('Valuation (Exit Multiple)', {}).get('cells', {})
    
    return {
        'dcf_perpetual': {
            'pv_fcfs': dcf_tab.get('(19, 2)', 0),  # Sum of PV of FCFs
            'terminal_value': dcf_tab.get('(26, 2)', 0),  # PV of Terminal Value (not row 20!)
            'enterprise_value': dcf_tab.get('(27, 2)', 0),  # Enterprise Value (EV)
            'equity_value': summary.get('(13, 2)', 0),  # Equity Value (Perpetual DCF) from Summary
            'intrinsic_value_per_share': summary.get('(18, 2)', 0),  # Value per Share (Perpetual DCF) from Summary
        },
        'dcf_exit': {
            'terminal_ev': exit_tab.get('(14, 2)', 0),  # Terminal Value (Un-discounted)
            'enterprise_value': exit_tab.get('(17, 2)', 0),  # Enterprise Value (EV) - row 17, not 18!
            'equity_value': exit_tab.get('(22, 2)', 0),  # Equity Value (Firm Value)
            'intrinsic_value_per_share': exit_tab.get('(25, 2)', 0),  # Intrinsic Value per Share - row 25, not 24!
            'exit_multiple': exit_tab.get('(3, 2)', 0),  # Terminal EV/EBITDA Multiple
        },
        'summary': {
            'dcf_intrinsic': summary.get('(18, 2)', 0),
            'exit_intrinsic': summary.get('(22, 2)', 0),
            # The third leg of the average. It was blended into row 26 and never
            # shown, so the two rows a reader could see did not average to the
            # figure beneath them (PayPal: $98.34 and $89.59 -> "$87.11").
            'comps_intrinsic': summary.get('(30, 2)'),
            'average_intrinsic': summary.get('(26, 2)', 0),
            'upside': summary.get('(27, 2)', 0),
            'shares_outstanding': summary.get('(8, 2)', 0),
            'cash': summary.get('(14, 2)', 0),
            'debt': summary.get('(15, 2)', 0),
            'net_debt': summary.get('(16, 2)', 0),
        },
        # The DCF tab's own inputs, so anything recomputed for the report — the
        # sensitivity grid — runs the SAME model as the headline: ten explicit
        # FCF periods (FY1-5 plus the FY6-10 fade) and the tab's equity bridge.
        'dcf_inputs': {
            'fcf': [dcf_tab.get(f'({16}, {c})') for c in range(2, 12)],
            'cash': dcf_tab.get('(30, 2)'),
            'debt': dcf_tab.get('(31, 2)'),
            'investments': dcf_tab.get('(32, 2)'),
            'shares': dcf_tab.get('(36, 2)'),
        },
    }


def extract_news_analysis(screening_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract news screening analysis."""
    return {
        'summary': screening_data.get('analysis_summary', {}),
        'catalysts': screening_data.get('catalysts', []),
        'risks': screening_data.get('risks', []),
        'mitigations': screening_data.get('mitigations', []),
        'screening_method': screening_data.get('analysis_method', 'LLM-based screening'),
    }


# Symbols for the venues this product actually covers. Anything unlisted
# falls back to the ISO code, which is unambiguous even when unlovely
# ("SEK 1.2bn" beats a wrong "$1.2bn").
# Re-exported so existing callers keep working; the table itself lives in
# src/currency.py, which has no dependencies and can be imported from the hot
# log path without dragging in the LLM clients.
from src.currency import _CURRENCY_SYMBOLS, currency_symbol  # noqa: E402,F401


def _requested_title() -> str:
    """
    The title the user asked for, if their brief named one.

    Sections are told not to restate the title, so unless the document header
    uses it the requested title vanishes entirely — which is what happened on
    the first pass of this fix: a brief saying 'titled "X"' produced a report
    where X appeared zero times.

    Deliberately conservative. Only well-formed, explicitly-quoted or
    explicitly-labelled titles are picked up; anything ambiguous falls through
    to the default company header rather than guessing a title from prose.
    """
    brief = _REPORT_BRIEF.get()
    if not brief:
        return ""
    patterns = [
        r'titled\s*[:\-]?\s*[\u201c"\u2018\']([^\u201d"\u2019\']{4,120})',
        r'title\s*it\s*[:\-]?\s*[\u201c"\u2018\']?([^\u201d"\u2019\'\n]{4,120})',
        r'\btitle\s*[:\-]\s*[\u201c"\u2018\']?([^\u201d"\u2019\'\n]{4,120})',
    ]
    for pat in patterns:
        m = re.search(pat, brief, re.I)
        if m:
            t = m.group(1).strip().strip('*').strip(' .;,')
            # Reject a fragment that is obviously the rest of a sentence.
            if 4 <= len(t) <= 120:
                return t
    return ""


def _strip_echoed_heading(body: str, title: str) -> str:
    """
    Drop the report title and the section's own heading when a model repeats
    them at the top of a section.

    Two things get echoed, and both were visible in a shipped report:

      * The SECTION HEADING. The prompts never ask for one, but models add it
        and the assembler adds its own -> "## Company Overview" twice.
      * The REPORT TITLE. Once the user's brief reaches the section prompts, a
        brief saying "title it X" makes every section restate X as an H1. Eight
        sections, eight copies of the title mid-document.

    So this walks past a leading H1 and any blank lines before looking for an
    echoed section heading — an earlier version only inspected line 1, found
    the title there, and gave up, leaving the duplicate heading in place.

    Only a heading MATCHING the section title is removed. A section that opens
    with a genuinely different heading keeps it: silently eating the first line
    of every section would trade a cosmetic defect for a content one.
    """
    if not body:
        return body

    lines = body.lstrip().split("\n")

    def norm(x: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", x.lower()).strip()

    want = norm(title)
    i = 0
    changed = True
    while changed and i < len(lines):
        changed = False
        # Skip blanks between echoed elements.
        while i < len(lines) and not lines[i].strip():
            i += 1
            changed = True
        if i >= len(lines):
            break
        m = re.match(r"^(#{1,6})\s*(.+?)\s*$", lines[i])
        if not m:
            break
        level, text = len(m.group(1)), norm(m.group(2))
        # A section never owns the document title, so any leading H1 goes.
        if level == 1:
            i += 1
            changed = True
            continue
        # Otherwise only remove it when it restates this section's own title.
        if text and want and (text == want or text in want or want in text):
            i += 1
            changed = True
            continue
        break

    return "\n".join(lines[i:]).lstrip()


def _money_symbol() -> str:
    """The current report's currency symbol; a dollar when no run is pinned."""
    code = _REPORT_CURRENCY.get()
    return currency_symbol(code) if code else "$"


def format_number(num, decimals=2):
    """
    Format a monetary figure in the REPORT'S currency.

    This hardcoded "$" for years without anyone noticing, because the tables it
    built travelled inside the LLM prompt and the model rewrote the symbol to
    match the currency directive while echoing them. Once the tables were
    emitted by code verbatim, LVMH's projections read "$83.23B" and PC
    Jeweller's "$44.26B" — 29 and 20 dollar amounts in euro and rupee reports.
    """
    if num is None:
        return "N/A"
    sym = _money_symbol()
    try:
        num = float(num)
        if abs(num) >= 1e9:
            return f"{sym}{num/1e9:.{decimals}f}B"
        elif abs(num) >= 1e6:
            return f"{sym}{num/1e6:.{decimals}f}M"
        elif abs(num) >= 1e3:
            return f"{sym}{num/1e3:.{decimals}f}K"
        else:
            return f"{sym}{num:.{decimals}f}"
    except:
        return str(num)


def format_percent(num, decimals=1):
    """Format number as percentage."""
    if num is None:
        return "N/A"
    try:
        return f"{float(num)*100:.{decimals}f}%"
    except:
        return str(num)


def generate_section_company_overview(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Company Overview section."""
    company = data['company_overview']
    
    # Handle None values for employees
    employees_str = f"{company['employees']:,}" if company['employees'] else "N/A"
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_company_overview")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        ticker=company['ticker'],
        sector=company['sector'],
        industry=company['industry'],
        description=company['description'][:500] + "..." if company['description'] else "N/A",
        employees=employees_str,
        market_cap=format_number(company['market_cap']),
        current_price=format_number(company['current_price'], 2),
        week_52_low=format_number(company['week_52_low'], 2),
        week_52_high=format_number(company['week_52_high'], 2)
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def generate_section_financial_performance(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Financial Performance Analysis section with pre-built tables."""
    historical = data['historical']
    company = data['company_overview']
    
    # Build revenue table from actual JSON data
    years = historical['years']
    revenue_table = "| Year | Revenue | Gross Profit | EBITDA | Net Income | Operating CF | Free Cash Flow |\n"
    revenue_table += "|------|---------|--------------|--------|------------|--------------|----------------|\n"
    for i, year in enumerate(years):
        revenue_table += f"| {year} | {format_number(historical['revenue'][i])} | {format_number(historical['gross_profit'][i])} | {format_number(historical['ebitda'][i])} | {format_number(historical['net_income'][i])} | {format_number(historical['operating_cf'][i])} | {format_number(historical['fcf'][i])} |\n"
    
    # Calculate YoY growth rates
    growth_table = "| Year | Revenue Growth | Gross Profit Growth | EBITDA Growth | Net Income Growth | Operating CF Growth | FCF Growth |\n"
    growth_table += "|------|----------------|---------------------|---------------|-------------------|---------------------|------------|\n"
    for i in range(1, len(years)):
        rev_growth = ((historical['revenue'][i] / historical['revenue'][i-1]) - 1) if historical['revenue'][i-1] else 0
        gp_growth = ((historical['gross_profit'][i] / historical['gross_profit'][i-1]) - 1) if historical['gross_profit'][i-1] else 0
        ebitda_growth = ((historical['ebitda'][i] / historical['ebitda'][i-1]) - 1) if historical['ebitda'][i-1] else 0
        ni_growth = ((historical['net_income'][i] / historical['net_income'][i-1]) - 1) if historical['net_income'][i-1] else 0
        ocf_growth = ((historical['operating_cf'][i] / historical['operating_cf'][i-1]) - 1) if historical['operating_cf'][i-1] else 0
        fcf_growth = ((historical['fcf'][i] / historical['fcf'][i-1]) - 1) if historical['fcf'][i-1] else 0
        
        growth_table += f"| {years[i-1]}-{years[i]} | {rev_growth:.2%} | {gp_growth:.2%} | {ebitda_growth:.2%} | {ni_growth:.2%} | {ocf_growth:.2%} | {fcf_growth:.2%} |\n"
    
    # Margins table
    margins_table = "| Metric | Current Value |\n"
    margins_table += "|--------|---------------|\n"
    margins_table += f"| Gross Margin | {format_percent(company['gross_margin'])} |\n"
    margins_table += f"| Operating Margin | {format_percent(company['operating_margin'])} |\n"
    margins_table += f"| EBITDA Margin | {format_percent(company['ebitda_margin'])} |\n"
    margins_table += f"| Net Margin | {format_percent(company['net_margin'])} |\n"
    margins_table += f"| ROE | {format_percent(company['roe'])} |\n"
    margins_table += f"| ROA | {format_percent(company['roa'])} |\n"
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_financial_performance")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        num_years=len(years),
        revenue_table=revenue_table,
        growth_table=growth_table,
        margins_table=margins_table
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def generate_section_valuation(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Financial Model & Valuation section with pre-built tables."""
    assumptions = data['assumptions']
    projections = data['projections']
    valuation = data['valuation']
    company = data['company_overview']
    
    # Model assumptions table
    assumptions_table = "| Assumption | Value |\n"
    assumptions_table += "|------------|-------|\n"
    # WACC is deliberately NOT repeated here — it is shown with its full
    # derivation in the Cost of Capital table below, sourced from the cells the
    # DCF actually discounted with. Printing it in both places invites the two
    # to drift apart, which is the failure this section is recovering from.
    assumptions_table += f"| Terminal Growth Rate | {format_percent(assumptions['terminal_growth'])} |\n"
    _tg_src = (data.get('cost_of_capital') or {}).get('terminal_growth_source')
    if _tg_src and _tg_src.strip().upper() != "LLM":
        assumptions_table += f"| Terminal growth basis | {_tg_src} |\n"
    assumptions_table += f"| Revenue Growth (FY1) | {format_percent(assumptions['revenue_growth_rates'][0])} |\n"
    assumptions_table += f"| Revenue Growth (FY2) | {format_percent(assumptions['revenue_growth_rates'][1])} |\n"
    assumptions_table += f"| Revenue Growth (FY3) | {format_percent(assumptions['revenue_growth_rates'][2])} |\n"
    assumptions_table += f"| Revenue Growth (FY4) | {format_percent(assumptions['revenue_growth_rates'][3])} |\n"
    assumptions_table += f"| Revenue Growth (FY5) | {format_percent(assumptions['revenue_growth_rates'][4])} |\n"
    assumptions_table += f"| EBITDA Margin (FY1) | {format_percent(assumptions['ebitda_margins'][0])} |\n"
    assumptions_table += f"| EBITDA Margin (FY2) | {format_percent(assumptions['ebitda_margins'][1])} |\n"
    assumptions_table += f"| EBITDA Margin (FY3) | {format_percent(assumptions['ebitda_margins'][2])} |\n"
    assumptions_table += f"| EBITDA Margin (FY4) | {format_percent(assumptions['ebitda_margins'][3])} |\n"
    assumptions_table += f"| EBITDA Margin (FY5) | {format_percent(assumptions['ebitda_margins'][4])} |\n"
    
    # 5-year projections table
    projections_table = "| Fiscal Year | Revenue | EBITDA | Free Cash Flow |\n"
    projections_table += "|-------------|---------|--------|----------------|\n"
    for i in range(5):
        projections_table += f"| FY{i+1} | {format_number(projections['revenue'][i])} | {format_number(projections['ebitda'][i])} | {format_number(projections['fcf'][i])} |\n"
    
    # DCF Perpetual Growth results
    dcf_perp_table = "| Metric | Value |\n"
    dcf_perp_table += "|--------|-------|\n"
    dcf_perp_table += f"| PV of Free Cash Flows | {format_number(valuation['dcf_perpetual']['pv_fcfs'])} |\n"
    dcf_perp_table += f"| Terminal Value | {format_number(valuation['dcf_perpetual']['terminal_value'])} |\n"
    dcf_perp_table += f"| Enterprise Value | {format_number(valuation['dcf_perpetual']['enterprise_value'])} |\n"
    dcf_perp_table += f"| Equity Value | {format_number(valuation['dcf_perpetual']['equity_value'])} |\n"
    dcf_perp_table += f"| Intrinsic Value per Share | {format_number(valuation['dcf_perpetual']['intrinsic_value_per_share'], 2)} |\n"
    
    # DCF Exit Multiple results
    dcf_exit_table = "| Metric | Value |\n"
    dcf_exit_table += "|--------|-------|\n"
    exit_multiple = valuation['dcf_exit']['exit_multiple']
    exit_multiple_str = f"{exit_multiple:.1f}x" if exit_multiple else "N/A"
    dcf_exit_table += f"| Exit Multiple (EV/EBITDA) | {exit_multiple_str} |\n"
    dcf_exit_table += f"| Terminal Enterprise Value | {format_number(valuation['dcf_exit']['terminal_ev'])} |\n"
    dcf_exit_table += f"| Enterprise Value | {format_number(valuation['dcf_exit']['enterprise_value'])} |\n"
    dcf_exit_table += f"| Equity Value | {format_number(valuation['dcf_exit']['equity_value'])} |\n"
    dcf_exit_table += f"| Intrinsic Value per Share | {format_number(valuation['dcf_exit']['intrinsic_value_per_share'], 2)} |\n"
    
    # Summary
    summary_table = "| Metric | Value |\n"
    summary_table += "|--------|-------|\n"
    summary_table += f"| DCF Perpetual Intrinsic Value | {format_number(valuation['dcf_perpetual']['intrinsic_value_per_share'], 2)} |\n"
    summary_table += f"| DCF Exit Multiple Intrinsic Value | {format_number(valuation['dcf_exit']['intrinsic_value_per_share'], 2)} |\n"
    # The workbook's average blends a third, market-comps leg. It was omitted
    # here, so the two rows above visibly failed to average to the row below.
    bank = valuation.get('bank')
    if bank:
        # A balance-sheet financial: the FCF DCF is not meaningful for a bank,
        # and the model valued it on justified P/B x ROE instead. Say so, and
        # print that number where the DCF rows would otherwise read 0.00.
        summary_table = "| Metric | Value |\n|--------|-------|\n"
        summary_table += f"| Justified P/B x ROE Intrinsic Value | {format_number(bank['fair_value'], 2)} |\n"
        summary_table += "| FCF DCF | _not applied — balance-sheet financial_ |\n"
    comps = valuation['summary'].get('comps_intrinsic')
    if isinstance(comps, (int, float)) and comps > 0 and not bank:
        summary_table += f"| Market Comps Intrinsic Value | {format_number(comps, 2)} |\n"
    # The workbook averages only the legs that came out POSITIVE — a negative
    # per-share value is a method that does not fit the company, not a low
    # estimate. Say how many actually entered, so "3 methods" is never printed
    # over an average of two (PC Jeweller: perpetual -2.03, dropped).
    legs = [valuation['dcf_perpetual']['intrinsic_value_per_share'],
            valuation['dcf_exit']['intrinsic_value_per_share'], comps]
    n_in = sum(1 for v in legs if isinstance(v, (int, float)) and v > 0)
    n_all = sum(1 for v in legs if isinstance(v, (int, float)))
    if bank:
        label = "**Intrinsic Value (justified P/B x ROE)**"
    elif n_in < n_all:
        label = f"**Average Intrinsic Value ({n_in} of {n_all} methods — negative results excluded)**"
    elif n_in > 2:
        label = f"**Average Intrinsic Value ({n_in} methods)**"
    else:
        label = "**Average Intrinsic Value**"
    summary_table += f"| {label} | **{format_number(valuation['summary']['average_intrinsic'], 2)}** |\n"
    summary_table += f"| Current Market Price | {format_number(company['current_price'], 2)} |\n"
    # A listing that trades in another currency: show the quote a holder sees
    # and the rate behind the converted figure above (Shell: 3,437p / £34.37
    # in London, $46.43 against USD statements).
    _lc, _rc = company.get('listing_currency'), company.get('currency')
    _pl, _fx = company.get('current_price_listing'), company.get('fx_listing_to_financial')
    if _lc and _rc and _lc != _rc and isinstance(_pl, (int, float)):
        _rate = f", converted at {_fx:.4f} {_rc}/{_lc}" if isinstance(_fx, (int, float)) else ""
        summary_table += f"| Price on the listing exchange | {currency_symbol(_lc)}{_pl:,.2f} ({_lc}{_rate}) |\n"
    summary_table += f"| **Implied Upside** | **{format_percent(valuation['summary']['upside'])}** |\n"
    
    # Cost of capital — the derivation, not just the rate. A DCF is mostly an
    # argument about the discount rate: on these projections the value moves far
    # more per 50bp of WACC than per point of growth, so a reader given only a
    # fair value has been given the least informative number in the model.
    coc = data.get('cost_of_capital') or {}
    coc_table = ""
    if coc.get('wacc'):
        coc_table = "| Input | Value |\n|-------|-------|\n"
        for label, key, fmt in (
            ("Risk-free rate", 'risk_free_rate', 'pct'),
            ("Equity risk premium (incl. country premium)", 'equity_risk_premium', 'pct'),
            ("Levered beta", 'beta', 'num'),
            ("Cost of equity", 'cost_of_equity', 'pct'),
            ("Pre-tax cost of debt", 'pre_tax_cost_of_debt', 'pct'),
            ("Tax rate", 'tax_rate', 'pct'),
            ("After-tax cost of debt", 'after_tax_cost_of_debt', 'pct'),
            ("Equity weight (E/V)", 'equity_weight', 'pct'),
            ("Debt weight (D/V)", 'debt_weight', 'pct'),
            ("**WACC**", 'wacc', 'pct'),
        ):
            value = coc.get(key)
            if value is None:
                continue
            rendered = format_percent(value) if fmt == 'pct' else f"{value:.2f}"
            coc_table += f"| {label} | {rendered} |\n"
        # Provenance beneath the numbers. A reader is entitled to know whether
        # the risk-free rate was a live yield, a dated figure, or — for a
        # currency we have no sovereign feed for — a US proxy.
        if coc.get('risk_free_source'):
            coc_table += f"| Risk-free source | {coc['risk_free_source']} |\n"
        if coc.get('beta_source'):
            coc_table += f"| Beta source | {coc['beta_source']} |\n"
        if coc.get('erp_source'):
            coc_table += f"| Premium build | {coc['erp_source']} |\n"
        if coc.get('kd_source'):
            coc_table += f"| Cost of debt build | {coc['kd_source']} |\n"
        if valuation.get('bank'):
            coc_table += ("\n_The justified P/B x ROE valuation uses the cost of equity from this build "
                          "(risk-free rate + beta x equity risk premium, held within 8-14%); the WACC "
                          "and cost of debt describe the cash-flow DCF that was not applied._\n")

    # A WACC x growth grid describes an FCF DCF. For a bank the DCF was not
    # applied, and recomputing it prints a grid of zeros under a P/B x ROE
    # headline (Capital One, JPMorgan). Say so instead.
    if valuation.get('bank'):
        sensitivity_table = "_Not applicable — valued on justified P/B x ROE, not a cash-flow DCF._"
    else:
        sensitivity_table = build_sensitivity_grid(
            projections, assumptions.get('terminal_growth') or 0.025,
            valuation, coc.get('wacc') or assumptions.get('wacc') or 0,
        )

    # The tables are assembled HERE and returned verbatim. They used to travel
    # inside the prompt with an instruction to reproduce them exactly, which
    # left the section's numbers at the model's discretion: PC Jeweller's
    # report shipped with zero tables — assumptions, cost of capital,
    # sensitivity, projections, both DCFs and the summary all replaced by three
    # paragraphs of prose that quoted figures from the grid it had just
    # declined to print. Numbers = code; the model writes only the commentary.
    tables_md = (
        f"### Model Assumptions\n\n{assumptions_table}\n"
        f"### Cost of Capital\n\n{coc_table or '_Cost-of-capital build unavailable for this model._'}\n\n"
        f"### Sensitivity: Value per Share by WACC and Terminal Growth\n\n"
        f"{sensitivity_table or '_Sensitivity grid unavailable for this model._'}\n\n"
        f"### 5-Year Projections\n\n{projections_table}\n"
        f"### DCF Valuation — Perpetual Growth Method\n\n{dcf_perp_table}\n"
        f"### DCF Valuation — Exit Multiple Method\n\n{dcf_exit_table}\n"
        f"### Valuation Summary\n\n{summary_table}\n"
    )

    prompt_template = load_prompt("report_valuation")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        tables=tables_md,
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)

    # Belt and braces: if the model echoed the tables anyway, do not print them
    # twice. Any commentary that begins by restating a table heading is cut
    # back to its prose.
    commentary = response.strip()
    for heading in ("### Model Assumptions", "## Model Assumptions", "### Cost of Capital"):
        if commentary.startswith(heading):
            commentary = commentary.split("### Commentary", 1)[-1].strip()
            break

    return f"{tables_md}\n### Commentary\n\n{commentary}", cost


def generate_section_news_analysis(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate News & Market Analysis section with pre-built tables."""
    news = data['news']
    company = data['company_overview']
    
    # Build catalysts table from actual JSON data (no LLM hallucination)
    catalysts_table = "| Type | Description | Confidence | Timeline | Supporting Evidence |\n"
    catalysts_table += "|------|-------------|------------|----------|---------------------|\n"
    for c in news['catalysts']:
        evidence = "; ".join(c.get('supporting_evidence', [])[:2])  # First 2 pieces
        catalysts_table += f"| {c.get('type', 'N/A').title()} | {c.get('description', 'N/A')} | {c.get('confidence', 0):.0%} | {c.get('timeline', 'N/A').title()} | {evidence[:100]}... |\n"
    
    # Build risks table from actual JSON data
    risks_table = "| Type | Description | Severity | Likelihood | Confidence | Potential Impact |\n"
    risks_table += "|------|-------------|----------|------------|------------|------------------|\n"
    for r in news['risks']:
        impact = r.get('potential_impact', 'N/A')[:80]
        risks_table += f"| {r.get('type', 'N/A').title()} | {r.get('description', 'N/A')} | {r.get('severity', 'N/A').title()} | {r.get('likelihood', 'N/A').title()} | {r.get('confidence', 0):.0%} | {impact}... |\n"
    
    # Build mitigations table from actual JSON data
    mitigations_table = "| Risk Addressed | Mitigation Strategy | Effectiveness | Confidence | Company Action |\n"
    mitigations_table += "|----------------|---------------------|---------------|------------|----------------|\n"
    for m in news['mitigations']:
        risk = m.get('risk_addressed', 'N/A')[:50]
        strategy = m.get('strategy', 'N/A')[:60]
        action = m.get('company_action', 'N/A')[:60]
        mitigations_table += f"| {risk}... | {strategy}... | {m.get('effectiveness', 'N/A').title()} | {m.get('confidence', 0):.0%} | {action}... |\n"
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_news_analysis")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        articles_analyzed=news['summary'].get('articles_analyzed', 0),
        overall_sentiment=news['summary'].get('overall_sentiment', 'neutral').upper(),
        confidence_score=f"{news['summary'].get('confidence_score', 0):.0%}",
        key_themes=', '.join(news['summary'].get('key_themes', [])),
        num_catalysts=len(news['catalysts']),
        catalysts_table=catalysts_table,
        num_risks=len(news['risks']),
        risks_table=risks_table,
        num_mitigations=len(news['mitigations']),
        mitigations_table=mitigations_table
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def generate_section_investment_thesis(data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Investment Thesis section."""
    company = data['company_overview']
    valuation = data['valuation']
    news = data['news']
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_investment_thesis")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        current_price=format_number(company['current_price'], 2),
        intrinsic_value=format_number(valuation['summary']['average_intrinsic'], 2),
        upside=format_percent(valuation['summary']['upside']),
        sentiment=news['summary'].get('overall_sentiment', 'neutral').upper(),
        num_catalysts=len(news['catalysts']),
        num_risks=len(news['risks'])
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.6)
    return response, cost


def generate_section_recommendation(data: Dict[str, Any], llm, logger: Optional[StockAnalystLogger] = None) -> Tuple[str, float, Dict[str, Any]]:
    """
    Generate Recommendation & Price Target section using evidence-based approach.
    
    V3 Architecture:
    1. Calculator (deterministic): All numbers computed in code
    2. Evidence Pack: Structured evidence with IDs for citations  
    3. Explainer LLM: Writes comprehensive narrative (NO number invention)
    4. Validator: Ensures numbers unchanged & citations present
    
    Key improvements over V2:
    - Numbers are 100% deterministic (computed in Python, not LLM)
    - LLM focuses on narrative explanation with evidence citations
    - Every claim must cite evidence [E#] for transparency
    - Comprehensive scenario analysis and monitoring plan
    - Full calculation methodology shown for auditability
    
    Design Philosophy: Numbers = Code, Narrative = LLM, Validation = Code
    
    Returns:
        Tuple[str, float, Dict[str, Any]]: (recommendation_text, cost, evidence_pack)
    """
    company = data['company_overview']
    valuation = data['valuation']
    news = data['news']
    
    # Initialize V3 evidence-based recommendation engine
    sector = company.get('sector', 'default')
    engine = RecommendationEngineV3(sector=sector, logger=logger)
    
    # Generate recommendation with deterministic calculations and evidence-based narrative
    recommendation_text, cost, evidence_pack = engine.generate_recommendation(
        company_data=company,
        valuation_data=valuation,
        screening_data=news,
        llm=llm
    )
    
    return recommendation_text, cost, evidence_pack


def generate_executive_summary(sections: Dict[str, str], data: Dict[str, Any], llm) -> Tuple[str, float]:
    """Generate Executive Summary based on all other sections."""
    company = data['company_overview']
    valuation = data['valuation']
    
    # Extract key points from recommendation section
    recommendation_preview = sections['recommendation'][:1000]
    
    # Load prompt template and fill in variables
    prompt_template = load_prompt("report_executive_summary")
    prompt = prompt_template.format(
        company_name=company['company_name'],
        intrinsic_value=format_number(valuation['summary']['average_intrinsic'], 2),
        current_price=format_number(company['current_price'], 2),
        upside=format_percent(valuation['summary']['upside']),
        recommendation_preview=recommendation_preview
    )

    messages = [{"role": "user", "content": prompt}]
    response, cost = llm(messages, temperature=0.5)
    return response, cost


def integrate_report_sections(sections: Dict[str, str], data: Dict[str, Any]) -> str:
    """Integrate all sections into final report with header/footer.
    
    This is a simple assembly function - no LLM call needed since sections
    are already comprehensive and well-formatted.
    """
    company = data['company_overview']
    # The rate the DCF actually discounted with. The appendix used to print
    # assumptions['wacc'], which is read from a different tab: on one shipped
    # AAPL report that was 8.5% while the model discounted at 11.15%.
    _coc = data.get('cost_of_capital') or {}
    # Read from `data`, not the local `assumptions`, which is not bound until
    # later in this function.
    _wacc_used = _coc.get('wacc') or (data.get('assumptions') or {}).get('wacc')
    report_date = datetime.now().strftime('%B %d, %Y')
    
    # Build complete report
    report_parts = []
    
    # Header
    # Use the title the user asked for when they gave one; otherwise the
    # company header. Either way the company and ticker stay on the line below,
    # so the document is still identifiable at a glance.
    _title = _requested_title()
    _heading = _title or f"{company['company_name']} ({company['ticker']})"
    _subheading = (
        f"## {company['company_name']} ({company['ticker']}) — Investment Analysis Report"
        if _title else "## Investment Analysis Report"
    )
    report_parts.append(f"""# {_heading}
{_subheading}

**Report Date**: {report_date}  
**Sector**: {company['sector']} | **Industry**: {company['industry']}  
**Exchange**: {company['exchange']}

---
""")
    
    # Table of Contents
    report_parts.append("""## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Company Overview](#company-overview)
3. [Financial Performance Analysis](#financial-performance-analysis)
4. [Financial Model & Valuation](#financial-model--valuation)
5. [News & Market Analysis](#news--market-analysis)
6. [Investment Thesis](#investment-thesis)
7. [Recommendation & Price Target](#recommendation--price-target)
8. [Appendix](#appendix)

---
""")
    
    # Executive Summary
    report_parts.append(f"""## Executive Summary

{_strip_echoed_heading(sections['executive_summary'], "Executive Summary")}

---
""")
    
    # Company Overview
    report_parts.append(f"""## Company Overview

{_strip_echoed_heading(sections['company_overview'], "Company Overview")}

---
""")
    
    # Financial Performance
    report_parts.append(f"""## Financial Performance Analysis

{_strip_echoed_heading(sections['financial_performance'], "Financial Performance Analysis")}

---
""")
    
    # Valuation
    report_parts.append(f"""## Financial Model & Valuation

{_strip_echoed_heading(sections['valuation'], "Financial Model & Valuation")}

---
""")
    
    # News Analysis
    report_parts.append(f"""## News & Market Analysis

{_strip_echoed_heading(sections['news_analysis'], "News & Market Analysis")}

---
""")
    
    # Investment Thesis
    report_parts.append(f"""## Investment Thesis

{_strip_echoed_heading(sections['investment_thesis'], "Investment Thesis")}

---
""")
    
    # Recommendation
    report_parts.append(f"""## Recommendation & Price Target

{_strip_echoed_heading(sections['recommendation'], "Recommendation & Price Target")}

---
""")
    
    # Appendix
    assumptions = data['assumptions']
    news = data['news']
    
    # Build detailed news appendix
    news_appendix = []
    
    # Catalysts with evidence
    news_appendix.append("### A. Detailed News Analysis\n")
    news_appendix.append(f"**Analysis Method**: {data.get('screening_method', 'LLM-based screening')}")
    news_appendix.append(f"**Articles Analyzed**: {news['summary'].get('articles_analyzed', 0)}")
    news_appendix.append(f"**Overall Sentiment**: {news['summary'].get('overall_sentiment', 'neutral').upper()} (Confidence: {news['summary'].get('confidence_score', 0):.0%})\n")
    
    news_appendix.append("#### Catalysts - Detailed Evidence\n")
    for i, catalyst in enumerate(news['catalysts'], 1):
        news_appendix.append(f"**{i}. {catalyst.get('description', 'N/A')}**")
        news_appendix.append(f"- **Type**: {catalyst.get('type', 'N/A').title()}")
        news_appendix.append(f"- **Timeline**: {catalyst.get('timeline', 'N/A').title()}")
        news_appendix.append(f"- **Confidence**: {catalyst.get('confidence', 0):.0%}")
        news_appendix.append(f"- **LLM Reasoning**: {catalyst.get('llm_reasoning', 'N/A')}")
        news_appendix.append(f"- **Potential Impact**: {catalyst.get('potential_impact', 'N/A')}")
        
        news_appendix.append(f"- **Supporting Evidence**:")
        for evidence in catalyst.get('supporting_evidence', []):
            news_appendix.append(f"  - {evidence}")
        
        if catalyst.get('direct_quotes'):
            news_appendix.append(f"- **Direct Quotes**:")
            for quote_obj in catalyst.get('direct_quotes', [])[:2]:  # First 2 quotes
                news_appendix.append(f"  - \"{quote_obj.get('quote', '')}\"")
                news_appendix.append(f"    - Source: [{quote_obj.get('source_article', 'N/A')}]({quote_obj.get('source_url', '#')})")
        
        news_appendix.append("")
    
    # Risks with evidence
    news_appendix.append("#### Risks - Detailed Evidence\n")
    for i, risk in enumerate(news['risks'], 1):
        news_appendix.append(f"**{i}. {risk.get('description', 'N/A')}**")
        news_appendix.append(f"- **Type**: {risk.get('type', 'N/A').title()}")
        news_appendix.append(f"- **Severity**: {risk.get('severity', 'N/A').title()}")
        news_appendix.append(f"- **Likelihood**: {risk.get('likelihood', 'N/A').title()}")
        news_appendix.append(f"- **Confidence**: {risk.get('confidence', 0):.0%}")
        news_appendix.append(f"- **LLM Reasoning**: {risk.get('llm_reasoning', 'N/A')}")
        news_appendix.append(f"- **Potential Impact**: {risk.get('potential_impact', 'N/A')}")
        
        news_appendix.append(f"- **Supporting Evidence**:")
        for evidence in risk.get('supporting_evidence', []):
            news_appendix.append(f"  - {evidence}")
        
        if risk.get('direct_quotes'):
            news_appendix.append(f"- **Direct Quotes**:")
            for quote_obj in risk.get('direct_quotes', [])[:2]:
                news_appendix.append(f"  - \"{quote_obj.get('quote', '')}\"")
                news_appendix.append(f"    - Source: [{quote_obj.get('source_article', 'N/A')}]({quote_obj.get('source_url', '#')})")
        
        news_appendix.append("")
    
    # Mitigations with evidence
    news_appendix.append("#### Risk Mitigations - Detailed Evidence\n")
    for i, mitigation in enumerate(news['mitigations'], 1):
        news_appendix.append(f"**{i}. {mitigation.get('strategy', 'N/A')}**")
        news_appendix.append(f"- **Risk Addressed**: {mitigation.get('risk_addressed', 'N/A')}")
        news_appendix.append(f"- **Effectiveness**: {mitigation.get('effectiveness', 'N/A').title()}")
        news_appendix.append(f"- **Confidence**: {mitigation.get('confidence', 0):.0%}")
        news_appendix.append(f"- **Company Action**: {mitigation.get('company_action', 'N/A')}")
        news_appendix.append(f"- **LLM Reasoning**: {mitigation.get('llm_reasoning', 'N/A')}")
        news_appendix.append(f"- **Implementation Timeline**: {mitigation.get('implementation_timeline', 'N/A')}")
        
        news_appendix.append(f"- **Supporting Evidence**:")
        for evidence in mitigation.get('supporting_evidence', []):
            news_appendix.append(f"  - {evidence}")
        
        if mitigation.get('direct_quotes'):
            news_appendix.append(f"- **Direct Quotes**:")
            for quote_obj in mitigation.get('direct_quotes', [])[:2]:
                news_appendix.append(f"  - \"{quote_obj.get('quote', '')}\"")
                news_appendix.append(f"    - Source: [{quote_obj.get('source_article', 'N/A')}]({quote_obj.get('source_url', '#')})")
        
        news_appendix.append("")
    
    # Add Evidence References section (mapping [E1], [E2], etc. to actual sources)
    news_appendix.append("\n### B. Evidence References\n")
    news_appendix.append("The following table maps evidence citations [E#] used in the Recommendation section to their sources:\n")
    
    # Get evidence_pack from sections
    evidence_pack = sections.get('evidence_pack', {})
    evidence_list = evidence_pack.get('evidence', [])
    
    if evidence_list:
        news_appendix.append("| ID | Type | Date | Source Title | URL |")
        news_appendix.append("|----|------|------|--------------|-----|")
        
        for evidence in evidence_list:
            eid = evidence.get('id', 'N/A')
            etype = evidence.get('type', 'N/A').replace('_', ' ').title()
            date = evidence.get('date', 'N/A')
            
            # Get title and source
            title = evidence.get('title', 'N/A')
            source = evidence.get('source', 'N/A')
            
            # Truncate title if too long
            display_title = title[:80] + "..." if len(title) > 80 else title
            
            # Get URL
            url = evidence.get('url', '#')
            url_display = f"[Link]({url})" if url != '#' else 'N/A'
            
            news_appendix.append(f"| {eid} | {etype} | {date} | {display_title} | {url_display} |")
        
        news_appendix.append("")
        
        # Add detailed snippets for each evidence
        news_appendix.append("#### Evidence Details\n")
        for evidence in evidence_list:
            eid = evidence.get('id', 'N/A')
            title = evidence.get('title', 'N/A')
            snippet = evidence.get('snippet', 'N/A')
            source = evidence.get('source', 'N/A')
            
            news_appendix.append(f"**{eid}: {title}**")
            news_appendix.append(f"- **Source**: {source}")
            news_appendix.append(f"- **Excerpt**: {snippet}")
            news_appendix.append("")
    else:
        news_appendix.append("*No evidence citations found in this report.*\n")
    
    report_parts.append(f"""## Appendix

{chr(10).join(news_appendix)}

### C. Key Model Assumptions

| Assumption | Value |
|-----------|-------|
| WACC | {format_percent(_wacc_used)} |
| Terminal Growth Rate | {format_percent(assumptions['terminal_growth'])} |
| Revenue Growth (FY1) | {format_percent(assumptions['revenue_growth_rates'][0])} |
| Revenue Growth (FY2) | {format_percent(assumptions['revenue_growth_rates'][1])} |
| Revenue Growth (FY3) | {format_percent(assumptions['revenue_growth_rates'][2])} |
| Revenue Growth (FY4) | {format_percent(assumptions['revenue_growth_rates'][3])} |
| Revenue Growth (FY5) | {format_percent(assumptions['revenue_growth_rates'][4])} |
| EBITDA Margin (FY1) | {format_percent(assumptions['ebitda_margins'][0])} |
| EBITDA Margin (FY2) | {format_percent(assumptions['ebitda_margins'][1])} |
| EBITDA Margin (FY3) | {format_percent(assumptions['ebitda_margins'][2])} |
| EBITDA Margin (FY4) | {format_percent(assumptions['ebitda_margins'][3])} |
| EBITDA Margin (FY5) | {format_percent(assumptions['ebitda_margins'][4])} |

### D. Disclaimers

This report is for informational purposes only and should not be considered as investment advice. 
The analysis is based on publicly available information and proprietary financial modeling. Past 
performance does not guarantee future results. Investors should conduct their own due diligence 
and consult with financial advisors before making investment decisions.

**Data Sources**: Financial data from yfinance, news analysis from article screening ({news['summary'].get('articles_analyzed', 0)} articles), 
valuation based on DCF modeling with LLM-inferred assumptions.

---

*Report generated on {report_date}*
""")
    
    return "\n".join(report_parts)


def generate_professional_report(
    financial_json_path: Path,
    computed_values_json_path: Path,
    screening_json_path: Path,
    logger: Optional[StockAnalystLogger] = None,
    valuation_override: Optional[Dict[str, Any]] = None,
) -> str:
    """Generate comprehensive professional report using LLM.
    
    Args:
        financial_json_path: Path to financials_annual_modeling_latest.json
        computed_values_json_path: Path to *_computed_values.json
        screening_json_path: Path to screening_data.json
        logger: Optional logger instance
        
    Returns:
        Complete markdown report
    """
    if logger:
        logger.info("="*70)
        logger.info("Generating Financial Report")
        logger.info("="*70)
    
    # Step 1: Load all data
    if logger:
        logger.info("Loading data files...")
    
    financial_data = load_financial_json(financial_json_path)
    computed_values = load_computed_values_json(computed_values_json_path)
    screening_data = load_screening_json(screening_json_path)
    
    if logger:
        logger.info("✅ Loaded all data files")
    
    # Step 2: Extract structured data
    if logger:
        logger.info("Extracting structured data...")
    
    data = {
        'company_overview': extract_company_overview(financial_data),
        'historical': extract_historical_financials(financial_data),
        'assumptions': extract_model_assumptions(computed_values),
        # The WACC build the DCF actually discounted with, so the report can
        # show its derivation instead of asserting a rate.
        'cost_of_capital': extract_cost_of_capital(computed_values),
        'projections': extract_projections(computed_values),
        'valuation': extract_valuation(computed_values),
        'news': extract_news_analysis(screening_data),
    }
    data = apply_valuation_override(data, valuation_override)
    
    if logger:
        logger.info("✅ Extracted structured data")
    
    # Step 3: Get LLM instance
    llm = get_llm()
    total_cost = 0.0
    sections = {}
    
    # Step 4: Generate sections iteratively
    if logger:
        logger.info("Generating report sections...")
    
    # Section 1: Company Overview
    if logger:
        logger.info("  1/7 Generating Company Overview...")
    section, cost = generate_section_company_overview(data, llm)
    sections['company_overview'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 2: Financial Performance
    if logger:
        logger.info("  2/7 Generating Financial Performance Analysis...")
    section, cost = generate_section_financial_performance(data, llm)
    sections['financial_performance'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 3: Valuation
    if logger:
        logger.info("  3/7 Generating Financial Model & Valuation...")
    section, cost = generate_section_valuation(data, llm)
    sections['valuation'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 4: News Analysis
    if logger:
        logger.info("  4/7 Generating News & Market Analysis...")
    section, cost = generate_section_news_analysis(data, llm)
    sections['news_analysis'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 5: Investment Thesis
    if logger:
        logger.info("  5/7 Generating Investment Thesis...")
    section, cost = generate_section_investment_thesis(data, llm)
    sections['investment_thesis'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Section 6: Recommendation — degrade to a placeholder rather than sinking
    # the whole report (financials/model/valuation sections are already done).
    if logger:
        logger.info("  6/7 Generating Recommendation & Price Target...")
    try:
        section, cost, evidence_pack = generate_section_recommendation(data, llm, logger)
        sections['recommendation'] = section
        sections['evidence_pack'] = evidence_pack  # Store for appendix
        total_cost += cost
        if logger:
            logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    except Exception as e:
        if logger:
            logger.error(f"     ❌ Recommendation section failed: {e}")
        sections['recommendation'] = "_Section unavailable (recommendation)._"
        sections['evidence_pack'] = {'evidence': []}
    
    # Section 7: Executive Summary (generated last, needs other sections)
    if logger:
        logger.info("  7/7 Generating Executive Summary...")
    section, cost = generate_executive_summary(sections, data, llm)
    sections['executive_summary'] = section
    total_cost += cost
    if logger:
        logger.info(f"     ✅ Complete (cost: ${cost:.4f})")
    
    # Step 5: Integrate all sections
    if logger:
        logger.info("Integrating all sections into final report...")
    
    final_report = integrate_report_sections(sections, data)

    if logger:
        logger.info(f"✅ Report integrated (total cost: ${total_cost:.4f})")

    return final_report


async def generate_professional_report_async(
    financial_json_path: Path,
    computed_values_json_path: Path,
    screening_json_path: Path,
    logger: Optional[StockAnalystLogger] = None,
    valuation_override: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Parallel counterpart to generate_professional_report.

    Sections 1-6 (company overview, financial performance, valuation, news,
    investment thesis, recommendation) are INDEPENDENT — each is a self-contained
    LLM call over the same `data`. We run them concurrently (each sync section
    function offloaded to a worker thread via asyncio.to_thread), then generate
    section 7 (executive summary), which depends on the others, and integrate.

    Output is identical to the serial version; only wall-clock changes
    (~sum-of-sections down to ~slowest-section + executive summary).
    """
    if logger:
        logger.info("=" * 70)
        logger.info("Generating Financial Report (parallel sections)")
        logger.info("=" * 70)

    financial_data = load_financial_json(financial_json_path)
    computed_values = load_computed_values_json(computed_values_json_path)
    screening_data = load_screening_json(screening_json_path)

    data = {
        'company_overview': extract_company_overview(financial_data),
        'historical': extract_historical_financials(financial_data),
        'assumptions': extract_model_assumptions(computed_values),
        # The WACC build the DCF actually discounted with, so the report can
        # show its derivation instead of asserting a rate.
        'cost_of_capital': extract_cost_of_capital(computed_values),
        'projections': extract_projections(computed_values),
        'valuation': extract_valuation(computed_values),
        'news': extract_news_analysis(screening_data),
    }
    data = apply_valuation_override(data, valuation_override)

    llm = get_llm()
    sections: Dict[str, Any] = {}
    total_cost = 0.0

    if logger:
        logger.info("Generating sections 1-6 concurrently...")

    # Fan out the six independent sections. Each returns (section_text, cost),
    # except recommendation which returns (text, cost, evidence_pack).
    results = await asyncio.gather(
        asyncio.to_thread(generate_section_company_overview, data, llm),
        asyncio.to_thread(generate_section_financial_performance, data, llm),
        asyncio.to_thread(generate_section_valuation, data, llm),
        asyncio.to_thread(generate_section_news_analysis, data, llm),
        asyncio.to_thread(generate_section_investment_thesis, data, llm),
        asyncio.to_thread(generate_section_recommendation, data, llm, logger),
        return_exceptions=True,
    )

    keys = [
        "company_overview", "financial_performance", "valuation",
        "news_analysis", "investment_thesis", "recommendation",
    ]
    for key, res in zip(keys, results):
        if isinstance(res, Exception):
            # A failed section degrades gracefully to a short placeholder rather
            # than sinking the whole report (mirrors the sync path's resilience).
            if logger:
                logger.error(f"     ❌ Section '{key}' failed: {res}")
            sections[key] = f"_Section unavailable ({key})._"
            if key == "recommendation":
                # Keep downstream consumers (appendix) uniform.
                sections["evidence_pack"] = {'evidence': []}
            continue
        if key == "recommendation":
            section, cost, evidence_pack = res
            sections["recommendation"] = section
            sections["evidence_pack"] = evidence_pack
        else:
            section, cost = res
            sections[key] = section
        total_cost += cost
        if logger:
            logger.info(f"     ✅ {key} complete (cost: ${cost:.4f})")

    # Section 7: Executive Summary — depends on the others, so run it after.
    if logger:
        logger.info("  Generating Executive Summary (depends on 1-6)...")
    section, cost = await asyncio.to_thread(generate_executive_summary, sections, data, llm)
    sections["executive_summary"] = section
    total_cost += cost

    final_report = integrate_report_sections(sections, data)
    if logger:
        logger.info(f"✅ Report integrated (total cost: ${total_cost:.4f})")
    return final_report


async def generate_and_save_professional_report_async(
    analysis_path: Path,
    ticker: str,
    logger: Optional[StockAnalystLogger] = None,
    output_language: Optional[str] = None,
    brief: Optional[str] = None,
    valuation_override: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Path]:
    """Async entry point: generate (parallel sections) + save the report."""
    set_report_language(output_language)
    set_report_brief(brief)
    financials_path = analysis_path / "financials" / "financials_annual_modeling_latest.json"

    # Pin the listing currency for this run before any section prompt loads.
    # Read from the financials the scraper already captured, so a foreign
    # listing is reported in its own currency instead of defaulting to dollars.
    try:
        import json as _json
        with open(financials_path) as _f:
            _basic = (_json.load(_f).get("company_data", {}) or {}).get("basic_info", {}) or {}
        set_report_currency(_basic.get("currency"))
    except Exception:
        # Never block a report on this; USD stays the prompts' default.
        set_report_currency(None)

    computed_values_path = analysis_path / "models" / f"{ticker}_financial_model_computed_values.json"
    screening_path = analysis_path / "screened" / "screening_data.json"
    report_output_dir = analysis_path / "reports"

    if not financials_path.exists():
        raise FileNotFoundError(f"Financial data not found: {financials_path}")
    if not computed_values_path.exists():
        raise FileNotFoundError(f"Computed values not found: {computed_values_path}")
    if not screening_path.exists():
        raise FileNotFoundError(f"Screening data not found: {screening_path}")

    report = await generate_professional_report_async(
        financial_json_path=financials_path,
        computed_values_json_path=computed_values_path,
        screening_json_path=screening_path,
        logger=logger,
        valuation_override=valuation_override,
    )
    report_path = save_professional_report(
        report=report, output_dir=report_output_dir, ticker=ticker, logger=logger
    )
    if logger:
        logger.info("=" * 70)
        logger.info("✅ PROFESSIONAL REPORT GENERATION COMPLETE")
        logger.info("=" * 70)
    return report, report_path


def save_professional_report(
    report: str,
    output_dir: Path,
    ticker: str,
    logger: Optional[StockAnalystLogger] = None
) -> Path:
    """Save report to markdown file.
    
    Args:
        report: Generated report content
        output_dir: Directory to save report
        ticker: Stock ticker
        logger: Optional logger
        
    Returns:
        Path to saved report
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{ticker}_Professional_Analysis_Report.md"
    report_path = output_dir / filename
    
    with open(report_path, 'w') as f:
        f.write(report)
    
    if logger:
        logger.info(f"✅ Report saved to: {report_path}")
        logger.info(f"   • File size: {report_path.stat().st_size:,} bytes")
    
    return report_path


def generate_and_save_professional_report(
    analysis_path: Path,
    ticker: str,
    logger: Optional[StockAnalystLogger] = None
) -> Tuple[str, Path]:
    """Main entry point: Generate and save professional report.
    
    Args:
        analysis_path: Path to analysis folder (e.g., data/email/ticker/timestamp/)
        ticker: Stock ticker
        logger: Optional logger
        
    Returns:
        Tuple of (report_content, report_file_path)
    """
    # Define paths
    financials_path = analysis_path / "financials" / "financials_annual_modeling_latest.json"
    computed_values_path = analysis_path / "models" / f"{ticker}_financial_model_computed_values.json"
    screening_path = analysis_path / "screened" / "screening_data.json"
    report_output_dir = analysis_path / "reports"
    
    # Validate paths
    if not financials_path.exists():
        raise FileNotFoundError(f"Financial data not found: {financials_path}")
    if not computed_values_path.exists():
        raise FileNotFoundError(f"Computed values not found: {computed_values_path}")
    if not screening_path.exists():
        raise FileNotFoundError(f"Screening data not found: {screening_path}")
    
    # Generate report
    report = generate_professional_report(
        financial_json_path=financials_path,
        computed_values_json_path=computed_values_path,
        screening_json_path=screening_path,
        logger=logger
    )
    
    # Save report
    report_path = save_professional_report(
        report=report,
        output_dir=report_output_dir,
        ticker=ticker,
        logger=logger
    )
    
    if logger:
        logger.info("="*70)
        logger.info("✅ PROFESSIONAL REPORT GENERATION COMPLETE")
        logger.info("="*70)
    
    return report, report_path


def main():
    """Main function for standalone execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate Professional Financial Report")
    parser.add_argument("--path", type=str, required=True, help="Path to analysis folder")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker symbol")
    args = parser.parse_args()

    # logger = StockAnalystLogger()
    generate_and_save_professional_report(
        analysis_path=Path(args.path),
        ticker=args.ticker,
    )

if __name__ == "__main__":
    main()
