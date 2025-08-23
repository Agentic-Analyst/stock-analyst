
#!/usr/bin/env python3
"""
financial_model_generator.py - Enhanced LLM-optional financial model generator.

This module creates comprehensive financial models (Excel/CSV) using structured
financial JSON (e.g., financials_annual_modeling_latest.json). It includes:
- Deterministic, auditable DCF to implied price (no LLM required)
- Comparable analysis (company-level with EV/EBITDA)
- Optional LLM narrative sections (safe fallback)
- Configurable WACC, terminal growth, projection years
- Robust handling of missing fields and clearer logging
- Optional explicit --data-file path (instead of directory probing)
- Clean OOP design preserved; logger supported if provided
- Auto-saves both timestamped and "latest" versions of Excel/CSV files

File Outputs:
- Timestamped: financial_model_comprehensive_TICKER_20250823_153045.xlsx
- Latest: financial_model_comprehensive_latest.xlsx (overwrites previous)
- CSV components: dcf_model_latest.csv, comparable_analysis_latest.csv, etc.

▶ Usage examples:
    python financial_model_generator.py --ticker NVDA --model dcf --data-file /path/to/financials_annual_modeling_latest.json
    python financial_model_generator.py --ticker AAPL --model comparable --years 5 --save-csv
    python financial_model_generator.py --ticker TSLA --model comprehensive --wacc 0.095 --term-growth 0.025
"""

from __future__ import annotations
import os, json, argparse, pathlib, math, re
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd

# Import configuration
from model_config import DEFAULTS, BOUNDS, EXCEL_CONFIG, PROMPTS

# Excel manipulation libraries
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils.dataframe import dataframe_to_rows
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False

# Optional LLM integration (guarded import)
def _try_load_llm():
    try:
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).parent))
        from llms import gpt_4o_mini
        return gpt_4o_mini
    except Exception:
        return None


DATA_ROOT = pathlib.Path(os.getenv('DATA_PATH', 'data'))


class FinancialModelGenerator:
    """Enhanced, auditable financial model generator for valuation analysis."""

    def __init__(self, ticker: str, data_file: Optional[str] = None, no_llm: bool = False):
        """Constructor sets up path references, caches, and optional LLM client.

        Parameters
        ----------
        ticker : str
            Company ticker.
        data_file : Optional[str]
            Explicit path to modeling JSON (bypasses probing) if provided.
        no_llm : bool
            If True, disables optional LLM features (narrative + param assist).
        """
        # --- Core paths ---
        self.ticker = ticker.upper()
        self.company_dir = DATA_ROOT / self.ticker
        self.financials_dir = self.company_dir / "financials"
        self.models_dir = self.company_dir / "models"

        # --- Logging ---
        self.logger = None

        # --- Optional LLM client (narrative + parameter assist) ---
        self.llm_function = None if no_llm else _try_load_llm()

        # --- Stats ---
        self.models_generated = 0
        self.analysis_sections = 0
        self.data_points_processed = 0

        # --- Cached data ---
        self._financial_data: Optional[Dict[str, Any]] = None
        self._company_info: Optional[Dict[str, Any]] = None

        # --- Explicit data file (if provided) ---
        self._explicit_data_file = pathlib.Path(data_file) if data_file else None

        # --- User overrides dictionary (will be merged with LLM proposals) ---
        self.overrides: Dict[str, Any] = {}

        # --- Diagnostics (warnings about missing or defaulted fields) ---
        self.diagnostics: List[str] = []

        # --- Forecast result cache ---
        self._forecast_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}

        # --- Audit log container for LLM parameter assist ---
        self.llm_param_audit: Dict[str, Any] = {}

    # ---------- Logging helpers ----------
    def set_logger(self, logger):
        self.logger = logger

    def _log(self, level: str, message: str):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message)
        else:
            print(f"[{level.upper()}] {message}")

    # ---------- Data loading ----------
    def _load_financial_data(self) -> Dict[str, Any]:
        if self._financial_data is not None:
            return self._financial_data

        if self._explicit_data_file and self._explicit_data_file.exists():
            path = self._explicit_data_file
        else:
            # default probing
            modeling_file = self.financials_dir / "financials_annual_modeling_latest.json"
            if not modeling_file.exists():
                candidates = sorted(self.financials_dir.glob("*modeling*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
                if not candidates:
                    raise FileNotFoundError(
                        f"No financial modeling data found for {self.ticker}. "
                        f"Provide --data-file or place the JSON under {self.financials_dir}."
                    )
                modeling_file = candidates[0]
            path = modeling_file

        with open(path, "r", encoding="utf-8") as f:
            self._financial_data = json.load(f)
        self._log("info", f"Loaded financial data for {self.ticker} from {path}")
        return self._financial_data

    # ---------- Safe numeric helpers ----------
    @staticmethod
    def _num(v: Any, default: Optional[float] = None) -> Optional[float]:
        try:
            if v is None: return default
            return float(v)
        except Exception:
            return default

    def _latest_from_map(self, m: Dict[str, Dict[str, Any]], keys: List[str]) -> Optional[float]:
        if not m: return None
        latest = max(m.keys())
        row = m.get(latest, {})
        for k in keys:
            if k in row and row[k] is not None:
                return self._num(row[k])
        return None

    # ---------- Metric extraction ----------
    def _extract_key_financial_metrics(self, data: Dict[str, Any]) -> Dict[str, Any]:
        metrics = {
            "company_info": {},
            "historical_financials": {},
            "valuation_inputs": {},
            "market_data": {},
            "company_data": data.get("company_data", {}),  # keep full block for WACC
        }

        cd = data.get("company_data", {})
        md = cd.get("market_data", {})
        basic = cd.get("basic_info", {})

        # Company info (no LLM classification – narrative only elsewhere)
        metrics["company_info"] = {
            "name": basic.get("long_name", self.ticker),
            "sector": basic.get("sector"),
            "industry": basic.get("industry"),
            "market_cap": md.get("market_cap"),
            "enterprise_value": md.get("enterprise_value"),
            "current_price": md.get("current_price"),
            "shares_outstanding": md.get("shares_outstanding_basic"),
        }

        fs = data.get("financial_statements", {})
        metrics["historical_financials"] = {
            "income_statement": fs.get("income_statement", {}),
            "balance_sheet": fs.get("balance_sheet", {}),
            "cash_flow": fs.get("cash_flow", {}),
        }

        vm = cd.get("valuation_metrics", {})
        cs = cd.get("capital_structure", {})
        metrics["valuation_inputs"] = {
            "beta": cs.get("beta"),
            "debt_to_equity": cs.get("debt_to_equity"),
            "current_ratio": cs.get("current_ratio"),
            "pe_ratio": vm.get("pe_ratio_trailing"),
            "price_to_book": vm.get("price_to_book"),
            "price_to_sales": vm.get("price_to_sales"),
        }

        # Market data (close-only volatility omitted here to keep core clean)
        hd = data.get("market_data", {}).get("historical_prices", {})
        metrics["market_data"] = {
            "period": hd.get("period"),
            "data_points": hd.get("data_points"),
        }

        # Count stats
        # Collect basic diagnostics for key nulls
        for field in ["market_cap","enterprise_value","current_price","shares_outstanding"]:
            if metrics["company_info"].get(field) is None:
                self.diagnostics.append(f"missing_company_info:{field}")
        self.data_points_processed = len(json.dumps(metrics))
        return metrics

    # ---------- WACC & working capital ----------
    def _infer_tax_rate(self, base_is: Dict[str, Any]) -> float:
        tr = self._num(base_is.get("Tax Rate For Calcs"))
        if tr and DEFAULTS.TAX_RATE_BOUNDS[0] < tr < DEFAULTS.TAX_RATE_BOUNDS[1]:
            return tr
        prov = self._num(base_is.get("Tax Provision"), DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE)
        pretax = self._num(base_is.get("Pretax Income"))
        if pretax and pretax != 0:
            cand = prov / pretax
            if DEFAULTS.TAX_RATE_BOUNDS[0] < cand < DEFAULTS.TAX_RATE_BOUNDS[1]:
                return float(cand)
        return DEFAULTS.DEFAULT_TAX_RATE

    def _compute_nwc(self, bs_row: Dict[str, Any]) -> float:
        ar = self._num(bs_row.get("Accounts Receivable"), DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE)
        inv = DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE
        for k in ["Inventory", "Finished Goods", "Work In Process", "Raw Materials"]:
            inv += self._num(bs_row.get(k), DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE) or DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE
        ap = self._num(bs_row.get("Accounts Payable"), DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE)
        return float(ar + inv - ap)

    def _get_wacc(self, company_data: Dict[str, Any], override_wacc: Optional[float]) -> float:
        if isinstance(override_wacc, (int, float)) and DEFAULTS.WACC_OVERRIDE_BOUNDS[0] < override_wacc < DEFAULTS.WACC_OVERRIDE_BOUNDS[1]:
            return float(override_wacc)

        cs = (company_data or {}).get("capital_structure", {}) or {}
        md = (company_data or {}).get("market_data", {}) or {}

        beta = self._num(cs.get("beta"), DEFAULTS.DEFAULT_BETA) or DEFAULTS.DEFAULT_BETA
        rf = self._num(cs.get("risk_free_rate"), DEFAULTS.DEFAULT_RISK_FREE_RATE) or DEFAULTS.DEFAULT_RISK_FREE_RATE
        erp = self._num(cs.get("equity_risk_premium"), DEFAULTS.DEFAULT_EQUITY_RISK_PREMIUM) or DEFAULTS.DEFAULT_EQUITY_RISK_PREMIUM
        ke = rf + beta * erp

        debt = self._num(cs.get("total_debt"), DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE) or DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE
        cash = self._num(cs.get("total_cash"), DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE) or DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE
        net_debt = debt - cash

        E = self._num(md.get("market_cap"), DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE) or DEFAULTS.DEFAULT_WORKING_CAPITAL_VALUE
        D = max(net_debt, 0.0) if net_debt is not None else 0.0  # if net cash, treat D~0 for weights
        V = max(E + D, 1.0)
        kd = max(rf, DEFAULTS.COST_OF_DEBT_FLOOR)  # conservative floor
        tax = DEFAULTS.DEFAULT_CORPORATE_TAX_RATE
        wacc = (E / V) * ke + (D / V) * kd * (1 - tax)
        self._log("info", f"Computed WACC: {wacc:.4f} (Ke={ke:.4f}, Kd={kd:.4f}, E={E:.2f}, D={D:.2f})")
        return float(max(DEFAULTS.WACC_MIN_FLOOR, min(wacc, DEFAULTS.WACC_MAX_CEILING)))

    # ---------- Strategy selection helpers ----------
    def _select_strategy(self, requested: Optional[str], metrics: Dict[str, Any]):
        from forecast_strategies import STRATEGIES, get_strategy_by_name
        if requested:
            strat = get_strategy_by_name(requested)
            if strat:
                self._log("info", f"Using requested strategy: {requested}")
                return strat
            self._log("warning", f"Requested strategy '{requested}' not found. Falling back to auto selection.")
        sector = metrics.get("company_info", {}).get("sector")
        industry = metrics.get("company_info", {}).get("industry")
        for strat in STRATEGIES:
            if strat.name != "generic_dcf" and strat.applies_to(sector, industry):
                self._log("info", f"Auto-selected strategy '{strat.name}' for sector='{sector}' industry='{industry}'")
                return strat
        # fallback (last one is generic in registry)
        generic = [s for s in STRATEGIES if s.name == "generic_dcf"]
        chosen = generic[0] if generic else STRATEGIES[-1]
        self._log("info", f"Fallback strategy '{chosen.name}' selected.")
        return chosen

    # ---------- Comparable analysis ----------
    def _create_comparable_analysis_dataframe(self, metrics: Dict[str, Any]) -> pd.DataFrame:
        cd = metrics.get("company_data", {}) or {}
        basic = (cd.get("basic_info") or {})
        md = (cd.get("market_data") or {})
        vm = (cd.get("valuation_metrics") or {})
        cs = (cd.get("capital_structure") or {})

        cap = self._num(md.get("market_cap"))
        enterprise_val = self._num(md.get("enterprise_value"))
        if enterprise_val is None:
            debt = self._num(cs.get("total_debt"), 0.0) or 0.0
            cash = self._num(cs.get("total_cash"), 0.0) or 0.0
            enterprise_val = (cap or 0.0) + debt - cash

        is_map = metrics["historical_financials"].get("income_statement", {})
        latest = max(is_map.keys()) if is_map else None
        ebitda = self._num(is_map.get(latest, {}).get("EBITDA") if latest else None) or \
                 self._num(is_map.get(latest, {}).get("Normalized EBITDA") if latest else None) or 0.0
        ev_ebitda = (enterprise_val / ebitda) if (enterprise_val and ebitda) else None

        df = pd.DataFrame([{
            "Company": basic.get("long_name") or metrics.get("company_info", {}).get("name", self.ticker),
            "Ticker": self.ticker,
            "Market Cap ($M)": (cap / 1e6) if cap else None,
            "Enterprise Value ($M)": (enterprise_val / 1e6) if enterprise_val else None,
            "P/E (trailing)": self._num(vm.get("pe_ratio_trailing")),
            "EV/EBITDA": ev_ebitda,
            "P/S": self._num(vm.get("price_to_sales")),
            "P/B": self._num(vm.get("price_to_book")),
            "Debt/Equity": self._num(cs.get("debt_to_equity")),
        }])
        return df

    # Peer comparables (multi-row) if peer tickers supplied
    def _create_peer_comps(self, base_metrics: Dict[str, Any], peers: List[str]) -> Optional[pd.DataFrame]:
        rows = []
        # include base first
        rows.append(self._create_comparable_analysis_dataframe(base_metrics).iloc[0].to_dict())
        for pt in peers:
            try:
                peer_dir = DATA_ROOT / pt.upper() / "financials"
                pf = peer_dir / "financials_annual_modeling_latest.json"
                if not pf.exists():
                    self._log("warning", f"Peer data missing for {pt}; skipping")
                    continue
                with open(pf, "r", encoding="utf-8") as f:
                    pdata = json.load(f)
                pmetrics = self._extract_key_financial_metrics(pdata)
                # Adjust ticker context temporarily
                orig = self.ticker
                self.ticker = pt.upper()
                prow = self._create_comparable_analysis_dataframe(pmetrics).iloc[0].to_dict()
                self.ticker = orig
                rows.append(prow)
            except Exception as e:
                self._log("warning", f"Peer {pt} failed: {e}")
        if len(rows) < 2:
            return None
        return pd.DataFrame(rows)

    # Sensitivities
    def _generate_sensitivities(self, strategy, metrics: Dict[str, Any], projection_years: int,
                                base_wacc: float, base_term_growth: float, term_growth: float,
                                override_wacc: Optional[float]) -> Dict[str, pd.DataFrame]:
        sens: Dict[str, pd.DataFrame] = {}
        try:
            # WACC vs Terminal Growth grid
            wacc_points = sorted(set([max(0.04, round(base_wacc - 0.02,4)), max(0.04, round(base_wacc - 0.01,4)), round(base_wacc,4), min(0.15, round(base_wacc + 0.01,4)), min(0.15, round(base_wacc + 0.02,4))]))
            tg_points = sorted(set([max(0.0, round(base_term_growth - 0.01,4)), round(base_term_growth,4), min(0.05, round(base_term_growth + 0.01,4))]))
            grid = []
            for w in wacc_points:
                row = {"WACC": w}
                for g in tg_points:
                    out = strategy.forecast(self, metrics, projection_years, g, w)
                    price = out.get("valuation_summary", {}).get("Implied Price") or out.get("valuation_summary", {}).get("Implied Price (blended)")
                    row[f"g={g:.2%}"] = price
                grid.append(row)
            sens["sensitivity_wacc_term"] = pd.DataFrame(grid)

            # Growth vs Margin (vary first-year growth delta & margin uplift)
            first_year_growth = 0.0
            # attempt to infer from strategy default by running once (base already ran)
            first_run = strategy.forecast(self, metrics, projection_years, term_growth, override_wacc)
            # not storing growth sequence; we'll assume ~ first revenue growth from DCF model
            df = first_run.get("dcf_model")
            if df is not None and len(df) > 1:
                r0, r1 = df.loc[0, "Revenue"], df.loc[1, "Revenue"] if 1 in df.index else (None, None)
                if r0 and r1:
                    first_year_growth = (r1 / r0) - 1
            growth_deltas = [-0.02, 0.0, 0.02]
            margin_uplifts = [-0.05, 0.0, 0.05]
            mgrid = []
            for gd in growth_deltas:
                row = {"ΔGrowth": gd}
                for mu in margin_uplifts:
                    # Build a transient override set (no mutation of self.overrides)
                    temp_overrides = dict(self.overrides)
                    temp_overrides["first_year_growth"] = max(0.0, first_year_growth + gd)
                    temp_overrides["margin_uplift"] = mu
                    # Monkey-pass via attribute (strategy reads generator.overrides); swap briefly
                    original = self.overrides
                    self.overrides = temp_overrides
                    out = strategy.forecast(self, metrics, projection_years, term_growth, override_wacc)
                    price = out.get("valuation_summary", {}).get("Implied Price") or out.get("valuation_summary", {}).get("Implied Price (blended)")
                    row[f"MarginΔ={mu:.0%}"] = price
                    self.overrides = original
                mgrid.append(row)
            sens["sensitivity_growth_margin"] = pd.DataFrame(mgrid)
        except Exception as e:
            self._log("warning", f"Sensitivity generation failed: {e}")
        return sens

    def _validation_summary(self, strategy_name: str, valuation_summary: Dict[str, Any]) -> Dict[str, Any]:
        missing = [k for k,v in valuation_summary.items() if v is None]
        return {
            "strategy": strategy_name,
            "overrides": self.overrides,
            "missing_valuation_fields": missing,
            "diagnostics": self.diagnostics,
            "models_generated": self.models_generated + 1,
        }

    # ---------- LLM narrative (optional) ----------
    def _generate_llm_financial_analysis(self, metrics: Dict[str, Any], model_type: str) -> Dict[str, str]:
        if not self.llm_function:
            self._log("info", "LLM disabled or unavailable; skipping narrative analysis.")
            self.analysis_sections = 0  # Set explicitly when LLM disabled
            return {}
        try:
            # Load financial narrative prompt from file
            prompt_path = pathlib.Path(PROMPTS.FINANCIAL_NARRATIVE)
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            # Format the prompt with ticker
            prompt = prompt_template.format(ticker=self.ticker)
            
            msgs = [
                {"role": "system", "content": "You are a senior financial analyst producing concise research-ready notes."},
                {"role": "user", "content": prompt},
            ]
            resp = self.llm_function(msgs, temperature=DEFAULTS.TEMP_NARRATIVE_ANALYSIS)
            # Support either string or (string, cost)
            if isinstance(resp, tuple):
                content, _ = resp
            else:
                content = resp
            # Simple section split
            sections = {}
            current = "executive_summary"
            buf = []
            for line in str(content).splitlines():
                up = line.upper()
                if "EXECUTIVE" in up: 
                    if buf: sections[current] = "\n".join(buf).strip(); buf=[]
                    current="executive_summary"
                elif "FINANCIAL PROJECTIONS" in up:
                    if buf: sections[current] = "\n".join(buf).strip(); buf=[]
                    current="financial_projections"
                elif "VALUATION" in up:
                    if buf: sections[current] = "\n".join(buf).strip(); buf=[]
                    current="valuation_analysis"
                elif "SENSITIVIT" in up:
                    if buf: sections[current] = "\n".join(buf).strip(); buf=[]
                    current="sensitivity_analysis"
                elif "INVESTMENT" in up:
                    if buf: sections[current] = "\n".join(buf).strip(); buf=[]
                    current="investment_recommendation"
                else:
                    buf.append(line)
            if buf:
                sections[current] = "\n".join(buf).strip()
            self.analysis_sections = len(sections)
            return sections
        except Exception as e:
            self._log("warning", f"LLM analysis failed: {e}")
            return {}

    # ---------- Public API ----------
    def generate_financial_model(self, model_type: str = "comprehensive", projection_years: int = 5,
                                 term_growth: Optional[float] = None, override_wacc: Optional[float] = None,
                                 strategy: Optional[str] = None, peers: Optional[List[str]] = None,
                                 generate_sensitivities: bool = False, lean: bool = False) -> Dict[str, Any]:
        data = self._load_financial_data()
        metrics = self._extract_key_financial_metrics(data)
        # --- Terminal growth auto-inference (no silent default) ---
        if term_growth is None:
            inferred_tg = None; tg_conf = None; tg_reason = None
            if self.llm_function:
                try:
                    prompt_path = pathlib.Path(PROMPTS.PARAMETER_INFERENCE)
                    with open(prompt_path,'r',encoding='utf-8') as f:
                        param_prompt = f.read()
                    fin = metrics.get('historical_financials', {})
                    def tail_map(m: Dict[str, Any]):
                        if not isinstance(m, dict): return m
                        keys = sorted(m.keys())[-3:]
                        return {k:m[k] for k in keys}
                    ctx_payload = {
                        'ticker': self.ticker,
                        'projection_years': projection_years,
                        'available_missing_params': ['terminal_growth'],
                        'income_statement_tail': tail_map(fin.get('income_statement', {})),
                        'balance_sheet_tail': tail_map(fin.get('balance_sheet', {})),
                        'cash_flow_tail': tail_map(fin.get('cash_flow', {})),
                        'company_info': metrics.get('company_info'),
                    }
                    llm_resp = self.llm_function([
                        {"role": "system", "content": param_prompt},
                        {"role": "user", "content": json.dumps(ctx_payload)}
                    ], temperature=DEFAULTS.TEMP_TERMINAL_GROWTH)
                    if isinstance(llm_resp, tuple): llm_resp = llm_resp[0]
                    txt = str(llm_resp).strip()
                    mm = re.search(r"\{[\s\S]+\}", txt)
                    if mm:
                        inferred_json = json.loads(mm.group(0))
                        inferred_block = inferred_json.get('inferred', {}) or {}
                        conf_block = inferred_json.get('confidence', {}) or {}
                        rationale_block = inferred_json.get('rationale', {}) or {}
                        if 'terminal_growth' in inferred_block and isinstance(inferred_block['terminal_growth'], (int,float)):
                            inferred_tg = float(inferred_block['terminal_growth'])
                            tg_conf = conf_block.get('terminal_growth', 1.0)
                            tg_reason = rationale_block.get('terminal_growth','')
                except Exception as e:
                    self._log('warning', f"LLM terminal growth inference failed: {e}")
            if inferred_tg is not None and (tg_conf is None or tg_conf >= DEFAULTS.LLM_CONFIDENCE_THRESHOLD):
                term_growth = max(0.0, min(DEFAULTS.MAX_TERMINAL_GROWTH_LLM, inferred_tg))
                self.llm_param_audit.setdefault('parameter_inference', {}).setdefault('applied', {})['terminal_growth'] = {
                    'value': term_growth,
                    'reason': tg_reason or 'llm_inferred',
                    'confidence': tg_conf
                }
                self.llm_param_audit.setdefault('parameter_inference_meta', {})['confidence_threshold'] = DEFAULTS.LLM_CONFIDENCE_THRESHOLD
            else:
                # Deterministic fallback using recent revenue CAGR * 0.3, clipped 0–0.03
                try:
                    is_map = metrics.get('historical_financials', {}).get('income_statement', {}) or {}
                    years_sorted = sorted(is_map.keys())
                    rev_vals = []
                    for y in years_sorted[-3:]:
                        row = is_map.get(y, {}) or {}
                        rv = row.get('Total Revenue') or row.get('Operating Revenue')
                        if rv is not None:
                            rev_vals.append(float(rv))
                    fallback = 0.02
                    if len(rev_vals) >= 2 and rev_vals[0] > 0 and rev_vals[-1] > 0:
                        cagr = (rev_vals[-1]/rev_vals[0]) ** (1/max(len(rev_vals)-1,1)) - 1
                        fallback = max(0.0, min(DEFAULTS.MAX_TERMINAL_GROWTH_DETERMINISTIC, cagr * DEFAULTS.TERMINAL_GROWTH_CAGR_SCALE))
                    term_growth = fallback
                except Exception:
                    term_growth = DEFAULTS.DEFAULT_TERMINAL_GROWTH_FALLBACK
                self.llm_param_audit.setdefault('parameter_inference', {}).setdefault('applied', {})['terminal_growth'] = {
                    'value': term_growth,
                    'reason': 'deterministic_fallback',
                    'confidence': 0.0
                }
        wacc_str = 'auto' if override_wacc is None else f"{override_wacc:.3f}"
        tg_str = 'n/a' if term_growth is None else f"{term_growth:.3f}"
        self._log("info", f"Generating {model_type} model for {self.ticker} ("\
                          f"{projection_years}y, g={tg_str}, wacc={wacc_str})")

        components: Dict[str, Any] = {}
        valuation_summary: Dict[str, Any] = {}

        chosen_strategy_name = None
        strat = None
        if model_type in ("dcf", "comprehensive"):
            # LLM assisted strategy selection if no explicit strategy passed and LLM available
            chosen_strategy_text = None
            if strategy is None and self.llm_function:
                try:
                    prompt_path = pathlib.Path(PROMPTS.STRATEGY_SELECTION)
                    context = {
                        "company_info": metrics.get('company_info'),
                        "quick_hist": {
                            "rev_years": len(metrics.get('historical_financials', {}).get('income_statement', {}) or {}),
                        },
                        "available_strategies": []
                    }
                    # import strategies list names
                    from forecast_strategies import STRATEGIES
                    context['available_strategies'] = [s.name for s in STRATEGIES]
                    with open(prompt_path, 'r', encoding='utf-8') as f:
                        base_prompt = f.read()
                    llm_resp = self.llm_function([
                        {"role": "system", "content": base_prompt},
                        {"role": "user", "content": json.dumps(context)}
                    ], temperature=DEFAULTS.TEMP_STRATEGY_SELECTION)
                    if isinstance(llm_resp, tuple): llm_resp = llm_resp[0]
                    txt = str(llm_resp).strip()
                    m = re.search(r"\{[\s\S]+\}", txt)
                    if m:
                        parsed = json.loads(m.group(0))
                        chosen_strategy_text = parsed.get('strategy')
                        self.llm_param_audit.setdefault('strategy_selection', parsed)
                except Exception as e:
                    self._log('warning', f"LLM strategy selection failed: {e}; falling back to rule-based")
            strat = self._select_strategy(chosen_strategy_text or strategy, metrics)
            chosen_strategy_name = strat.name
            # Caching key
            hashable_overrides = {}
            for k, v in self.overrides.items():
                hashable_overrides[k] = str(v) if isinstance(v, list) else v
            ov_hash = hash(tuple(sorted(hashable_overrides.items())))
            cache_key = (strat.name, projection_years, round(term_growth,6), override_wacc if override_wacc is None else round(override_wacc,6), ov_hash)
            if cache_key in self._forecast_cache:
                strat_outputs = self._forecast_cache[cache_key]
                self._log("info", f"Cache hit for strategy {strat.name}")
            else:
                # Before first forecast, perform LLM parameter inference for any unset override fields
                if self.llm_function:
                    try:
                        # Determine which parameters are unset (not provided by user or prior LLM override)
                        candidate_params = [
                            'first_year_growth','margin_target','margin_ramp','capex_rate','da_rate',
                            'nwc_method','nwc_ratio','margin_curve','growth_sequence'
                        ]  # terminal_growth handled earlier to ensure caching key stability
                        missing = [p for p in candidate_params if p not in self.overrides]
                        if missing:
                            prompt_path = pathlib.Path(PROMPTS.PARAMETER_INFERENCE)
                            with open(prompt_path,'r',encoding='utf-8') as f:
                                param_prompt = f.read()
                            # Build compact context for inference (recent IS/BS rows)
                            fin = metrics.get('historical_financials', {})
                            # Limit to last 3 periods per statement to keep prompt size manageable
                            def tail_map(m: Dict[str, Any]):
                                if not isinstance(m, dict): return m
                                keys = sorted(m.keys())[-3:]
                                return {k:m[k] for k in keys}
                            ctx_payload = {
                                'ticker': self.ticker,
                                'projection_years': projection_years,
                                'term_growth': term_growth,
                                'available_missing_params': missing,
                                'income_statement_tail': tail_map(fin.get('income_statement', {})),
                                'balance_sheet_tail': tail_map(fin.get('balance_sheet', {})),
                                'cash_flow_tail': tail_map(fin.get('cash_flow', {})),
                                'company_info': metrics.get('company_info'),
                            }
                            llm_resp = self.llm_function([
                                {"role": "system", "content": param_prompt},
                                {"role": "user", "content": json.dumps(ctx_payload)}
                            ], temperature=DEFAULTS.TEMP_PARAMETER_INFERENCE)
                            if isinstance(llm_resp, tuple): llm_resp = llm_resp[0]
                            txt = str(llm_resp).strip()
                            mm = re.search(r"\{[\s\S]+\}", txt)
                            if mm:
                                inferred_json = json.loads(mm.group(0))
                                inferred = inferred_json.get('inferred', {}) or {}
                                rationale = inferred_json.get('rationale', {}) or {}
                                conf = inferred_json.get('confidence', {}) or {}
                                applied = {}
                                skipped_low_conf = []
                                confidence_threshold = DEFAULTS.LLM_CONFIDENCE_THRESHOLD
                                self.llm_param_audit.setdefault('parameter_inference_meta', {})['confidence_threshold'] = confidence_threshold
                                bounds = BOUNDS.get_bounds_dict()
                                for k,v in inferred.items():
                                    cval = conf.get(k, 1.0)
                                    if cval < confidence_threshold:
                                        skipped_low_conf.append({'param': k, 'reason': 'low_confidence', 'confidence': cval})
                                        continue
                                    if k == 'growth_sequence' and isinstance(v, list) and k not in self.overrides:
                                        seq = [float(x) for x in v if isinstance(x,(int,float))]
                                        if seq:
                                            # Enforce length; if shorter, extend with last value; if longer, truncate
                                            if len(seq) < projection_years:
                                                seq += [seq[-1]] * (projection_years - len(seq))
                                            if len(seq) > projection_years:
                                                seq = seq[:projection_years]
                                            # Clip bounds per element
                                            seq = [max(0.0, min(0.60, x)) for x in seq]
                                            self.overrides[k] = seq
                                            applied[k] = {'value': seq, 'reason': rationale.get(k,''), 'confidence': cval}
                                    elif k == 'margin_curve' and isinstance(v, list) and k not in self.overrides:
                                        curve = [float(x) for x in v if isinstance(x,(int,float))]
                                        if curve:
                                            if len(curve) < projection_years:
                                                curve += [curve[-1]] * (projection_years - len(curve))
                                            if len(curve) > projection_years:
                                                curve = curve[:projection_years]
                                            curve = [max(0.0, min(0.90, x)) for x in curve]
                                            self.overrides[k] = curve
                                            applied[k] = {'value': curve, 'reason': rationale.get(k,''), 'confidence': cval}
                                    elif k in candidate_params and k not in self.overrides and isinstance(v,(int,float)):
                                        lo,hi = bounds.get(k,(None,None))
                                        fv = float(v)
                                        if lo is not None:
                                            fv = max(lo, min(hi, fv))
                                        self.overrides[k] = fv
                                        applied[k] = {'value': fv, 'reason': rationale.get(k,''), 'confidence': cval}
                                    elif k=='nwc_method' and k not in self.overrides and v in ('ratio','delta2pct'):
                                        if cval >= confidence_threshold:
                                            self.overrides[k] = v
                                            applied[k] = {'value': v, 'reason': rationale.get(k,''), 'confidence': cval}
                                        else:
                                            skipped_low_conf.append({'param': k, 'reason': 'low_confidence', 'confidence': cval})
                                if applied:
                                    self.llm_param_audit.setdefault('parameter_inference', {})['applied'] = applied
                                    self.llm_param_audit.setdefault('parameter_inference', {})['raw'] = txt[:1500]
                                if skipped_low_conf:
                                    self.llm_param_audit.setdefault('parameter_inference', {})['skipped_low_confidence'] = skipped_low_conf
                    except Exception as e:
                        self._log('warning', f"LLM parameter inference failed: {e}")
                strat_outputs = strat.forecast(self, metrics, projection_years, term_growth, override_wacc)
                self._forecast_cache[cache_key] = strat_outputs
            dcf_df = strat_outputs.get("dcf_model")
            valuation_summary = strat_outputs.get("valuation_summary", {})
            valuation_summary["Strategy"] = strat_outputs.get("strategy_name")
            components["dcf_model"] = dcf_df
            components["valuation_summary"] = valuation_summary
            # Extra components (e.g., FFO/AFFO)
            for k,v in (strat_outputs.get("extra_components") or {}).items():
                components[k] = v
            if (not lean) and generate_sensitivities and strat and valuation_summary.get("WACC"):
                sens = self._generate_sensitivities(strat, metrics, projection_years,
                                                    valuation_summary.get("WACC"), term_growth, term_growth, override_wacc)
                for k,v in sens.items():
                    components[k] = v

        if (not lean) and model_type in ("comparable", "comprehensive"):
            comps_df = self._create_comparable_analysis_dataframe(metrics)
            components["comparable_analysis"] = comps_df
            if peers:
                peer_list = [p.strip().upper() for p in peers if p.strip().upper() not in (self.ticker, "")]
                if peer_list:
                    peer_df = self._create_peer_comps(metrics, peer_list)
                    if peer_df is not None:
                        components["peer_comparables"] = peer_df

        llm_analysis = {} if lean else self._generate_llm_financial_analysis(metrics, model_type)

        model = {
            "ticker": self.ticker,
            "company_name": metrics["company_info"].get("name", self.ticker),
            "model_type": model_type,
            "generated_at": datetime.utcnow().isoformat(),
            "projection_years": projection_years,
            "llm_analysis": llm_analysis,
            "financial_metrics": metrics,
            "model_components": components,
            "valuation_summary": valuation_summary,
            "generation_stats": {
                "models_generated": 1,
                "analysis_sections": self.analysis_sections,
                "data_points_processed": self.data_points_processed,
                "forecast_cache_entries": len(self._forecast_cache),
            },
            "parameters": {
                "term_growth": term_growth,
                "wacc": valuation_summary.get("WACC"),
                "strategy": valuation_summary.get("Strategy"),
                "peers": peers,
                "lean": lean,
            },
            "validation": self._validation_summary(chosen_strategy_name or "n/a", valuation_summary),
        }
        if self.llm_param_audit:
            model["llm_parameter_overrides"] = self.llm_param_audit
            # Persist audit to JSON for reproducibility
            try:
                self._ensure_dirs()
                audit_path = self.models_dir / f"llm_audit_{self.ticker}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
                with open(audit_path,'w',encoding='utf-8') as f:
                    json.dump(self.llm_param_audit, f, indent=2)
                model['llm_audit_file'] = str(audit_path)
                self._log('info', f"LLM audit saved: {audit_path}")
            except Exception as e:
                self._log('warning', f"Failed to persist LLM audit: {e}")
        self.models_generated += 1
        return model

    # ---------- LLM Assisted Parameter Overrides (bounded & auditable) ----------
    def propose_llm_parameter_overrides(self, baseline_model: Dict[str, Any], projection_years: int,
                                        term_growth: float, strategy: Optional[str],
                                        caps: Optional[Dict[str, Any]] = None, temperature: float = 0.1) -> Dict[str, Any]:
        """Ask LLM for refined parameter overrides (growth, margin_target, margin_ramp, capex_rate, nwc_ratio, wacc_delta).

        Returns dict of validated overrides (keys match self.overrides / wacc override) without mutating state.
        Safe if LLM unavailable (returns empty dict).
        """
        if not self.llm_function:
            return {}
        caps = caps or {
            "first_year_growth": {"min": 0.0, "max": 0.60},  # absolute value
            "margin_target": {"min": 0.05, "max": 0.60},
            "margin_ramp": {"min": 0.0, "max": 0.05},
            "capex_rate": {"min": 0.0, "max": 0.18},
            "nwc_ratio": {"min": -0.05, "max": 0.40},
            "wacc_delta": {"min": -0.01, "max": 0.01},
        }
        # Extract baseline metrics from dcf_model
        dcf_df = (baseline_model.get("model_components") or {}).get("dcf_model")
        base_growth = None
        base_margin_first = None
        base_margin_last = None
        base_capex_rate = None
        base_wacc = (baseline_model.get("valuation_summary") or {}).get("WACC")
        try:
            if dcf_df is not None and hasattr(dcf_df, 'iloc') and len(dcf_df) >= 2:
                r0 = float(dcf_df.iloc[0].get("Revenue") or 0)
                r1 = float(dcf_df.iloc[1].get("Revenue") or 0)
                if r0 > 0 and r1 > 0:
                    base_growth = (r1 / r0) - 1
                e0 = float(dcf_df.iloc[0].get("EBITDA") or 0)
                e_last = float(dcf_df.iloc[len(dcf_df)-1].get("EBITDA") or 0)
                r_last = float(dcf_df.iloc[len(dcf_df)-1].get("Revenue") or 0)
                if r0 > 0 and e0 > 0:
                    base_margin_first = e0 / r0
                if r_last > 0 and e_last > 0:
                    base_margin_last = e_last / r_last
                capex1 = float(dcf_df.iloc[1].get("CapEx") or 0)
                if r1 > 0 and capex1 >= 0:
                    base_capex_rate = capex1 / r1
        except Exception:
            pass
        ctx_lines = []
        if base_growth is not None: ctx_lines.append(f"base_first_year_growth={base_growth:.4f}")
        if base_margin_first is not None: ctx_lines.append(f"margin_first={base_margin_first:.4f}")
        if base_margin_last is not None: ctx_lines.append(f"margin_last={base_margin_last:.4f}")
        if base_capex_rate is not None: ctx_lines.append(f"capex_rate_first={base_capex_rate:.4f}")
        if base_wacc is not None: ctx_lines.append(f"wacc={base_wacc:.4f}")
        ctx_lines.append(f"term_growth={term_growth:.4f}")
        ctx = ", ".join(ctx_lines)
        schema = {
            "overrides": [
                {"param": "first_year_growth|margin_target|margin_ramp|capex_rate|nwc_ratio|wacc_delta", "value": "numeric", "reason": "short justification"}
            ]
        }
        caps_txt = "; ".join(f"{k}:[{v['min']},{v['max']}]" for k,v in caps.items())
        # Load parameter overrides prompt from file
        prompt_path = pathlib.Path(PROMPTS.PARAMETER_OVERRIDES)
        with open(prompt_path, 'r', encoding='utf-8') as f:
            prompt_template = f.read()
        
        prompt = (
            prompt_template + f"\n\nContext: {ctx}\nCaps: {caps_txt}\nJSON Schema Example: {json.dumps(schema)}"
        )
        try:
            raw = self.llm_function([
                {"role": "system", "content": "You return compact JSON with financially realistic parameter overrides."},
                {"role": "user", "content": prompt}
            ], temperature=temperature or DEFAULTS.TEMP_PARAMETER_OVERRIDES)
            if isinstance(raw, tuple): raw = raw[0]
            text = str(raw).strip()
        except Exception as e:  # pragma: no cover
            self.llm_param_audit = {"error": f"LLM call failed: {e}"}
            return {}
        json_str = None
        if text.startswith('{') and text.endswith('}'): json_str = text
        else:
            m = re.search(r"\{[\s\S]+\}", text)
            if m: json_str = m.group(0)
        overrides: Dict[str, Any] = {}
        audit = {"raw": text, "parsed": None, "applied": {}, "skipped": []}
        try:
            if json_str:
                parsed = json.loads(json_str)
                audit["parsed"] = parsed
                for o in parsed.get("overrides", [])[:12]:
                    param = str(o.get("param",""))
                    val = o.get("value")
                    reason = str(o.get("reason",""))[:300]
                    if param not in caps:
                        audit["skipped"].append({"param": param, "reason": "not_allowed"}); continue
                    try:
                        fval = float(val)
                    except Exception:
                        audit["skipped"].append({"param": param, "reason": "non_numeric"}); continue
                    bounds = caps[param]
                    if fval < bounds['min'] or fval > bounds['max']:
                        fval = min(bounds['max'], max(bounds['min'], fval))  # clip
                    # basic sanity: margin_target >= margin_first (if known)
                    if param == 'margin_target' and base_margin_first is not None and fval < base_margin_first:
                        audit["skipped"].append({"param": param, "reason": "below_base_margin_first"}); continue
                    overrides[param] = fval
                    audit["applied"][param] = {"value": fval, "reason": reason}
            else:
                audit["error"] = "no_json_detected"
        except Exception as e:  # pragma: no cover
            audit["error"] = f"parse_error:{e}"
        # Translate wacc_delta to direct override if baseline wacc present
        if 'wacc_delta' in overrides and base_wacc is not None:
            new_wacc = max(0.04, min(0.20, base_wacc + overrides['wacc_delta']))
            audit['applied']['override_wacc'] = new_wacc
            overrides['override_wacc'] = new_wacc
            del overrides['wacc_delta']
        self.llm_param_audit = audit
        # Map parameter names to generator overrides keys
        mapped = {}
        for k,v in overrides.items():
            if k == 'override_wacc':
                mapped['__override_wacc__'] = v
            else:
                mapped[k] = v
        return mapped

    # ---------- Excel / CSV writers ----------
    def _ensure_dirs(self):
        self.company_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def save_model_to_excel(self, model: Dict[str, Any]) -> pathlib.Path:
        if not EXCEL_AVAILABLE:
            raise ImportError("openpyxl required. Install with: pip install openpyxl")

        self._ensure_dirs()
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"financial_model_{model['model_type']}_{model['ticker']}_{ts}.xlsx"
        out = self.models_dir / filename

        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        # Summary
        ws = wb.create_sheet("Executive Summary")
        ws["A1"] = f"{model['company_name']} ({model['ticker']}) — Financial Model"
        ws["A1"].font = Font(size=16, bold=True)

        ws["A3"] = "Model Type:"; ws["B3"] = model["model_type"].title()
        ws["A4"] = "Generated:" ; ws["B4"] = model["generated_at"][:19].replace("T"," ")
        ws["A5"] = "Projection Years:"; ws["B5"] = model["projection_years"]

        # Company info
        ws["A7"] = "Company Information:"; ws["A7"].font = Font(bold=True)
        r = 8
        for k, v in model.get("financial_metrics", {}).get("company_info", {}).items():
            if v is not None:
                ws[f"A{r}"] = k.replace("_", " ").title() + ":"
                ws[f"B{r}"] = v
                r += 1

        # Valuation block if available
        val = model.get("valuation_summary") or {}
        if val:
            r += 1
            ws[f"A{r}"] = "Valuation"; ws[f"A{r}"].font = Font(bold=True); r += 1
            for k in ["WACC","Terminal Growth","PV of FCFF","PV of TV","Enterprise Value","Net Debt","Equity Value","Shares (basic)","Implied Price"]:
                ws[f"A{r}"] = k + ":"
                ws[f"B{r}"] = val.get(k)
                r += 1

        # Dynamic DataFrame tabs
        for key, df in model["model_components"].items():
            if isinstance(df, pd.DataFrame):
                sheet_name = EXCEL_CONFIG.SHEET_NAMES.get(key, key[:EXCEL_CONFIG.MAX_SHEET_NAME_LENGTH])
                wsdf = wb.create_sheet(sheet_name)
                for ridx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
                    for cidx, value in enumerate(row, 1):
                        cell = wsdf.cell(row=ridx, column=cidx, value=value)
                        if ridx == 1:
                            cell.font = Font(bold=True)
                            cell.fill = PatternFill(start_color=EXCEL_CONFIG.HEADER_FILL_COLOR, end_color=EXCEL_CONFIG.HEADER_FILL_COLOR, fill_type="solid")

        # Narrative
        if model.get("llm_analysis"):
            na_ws = wb.create_sheet("LLM Analysis")
            rr = 1
            for sec, txt in model["llm_analysis"].items():
                na_ws[f"A{rr}"] = sec.replace("_"," ").title()
                na_ws[f"A{rr}"].font = Font(bold=True)
                rr += 1
                for line in str(txt).splitlines():
                    na_ws[f"A{rr}"] = line
                    rr += 1
                rr += 1

        # Validation sheet (structured formatting)
        val_ws = wb.create_sheet("Validation")
        vdata = model.get("validation", {}) or {}
        # Strategy
        val_ws["A1"] = "Strategy"; val_ws["A1"].font = Font(bold=True)
        val_ws["B1"] = vdata.get("strategy")
        # Overrides
        val_ws["A3"] = "Overrides"; val_ws["A3"].font = Font(bold=True)
        overrides = vdata.get("overrides") or {}
        row = 4
        for k in sorted(overrides.keys()):
            val_ws[f"A{row}"] = k
            # Handle arrays and other non-Excel-compatible types
            value = overrides[k]
            if isinstance(value, (list, tuple)):
                # Convert arrays to comma-separated strings
                val_ws[f"B{row}"] = ", ".join(str(x) for x in value)
            elif isinstance(value, dict):
                # Convert dicts to string representation
                val_ws[f"B{row}"] = str(value)
            else:
                val_ws[f"B{row}"] = value
            row += 1
        # Missing valuation fields
        row += 1
        val_ws[f"A{row}"] = "Missing Valuation Fields"; val_ws[f"A{row}"].font = Font(bold=True)
        mvf = vdata.get("missing_valuation_fields") or []
        row += 1
        if mvf:
            fill_warn = PatternFill(start_color=EXCEL_CONFIG.WARNING_FILL_COLOR, end_color=EXCEL_CONFIG.WARNING_FILL_COLOR, fill_type="solid")
            for fld in mvf:
                val_ws[f"A{row}"] = fld
                val_ws[f"A{row}"].fill = fill_warn
                row += 1
        else:
            val_ws[f"A{row}"] = "(none)"; row += 1
        # Diagnostics
        row += 1
        val_ws[f"A{row}"] = "Diagnostics"; val_ws[f"A{row}"].font = Font(bold=True)
        row += 1
        diags = vdata.get("diagnostics") or []
        if diags:
            fill_info = PatternFill(start_color="D1ECF1", end_color="D1ECF1", fill_type="solid")
            for d in diags:
                val_ws[f"A{row}"] = d
                val_ws[f"A{row}"].fill = fill_info
                row += 1
        else:
            val_ws[f"A{row}"] = "(none)"; row += 1
        # Meta stats
        row += 1
        val_ws[f"A{row}"] = "Models Generated"; val_ws[f"B{row}"] = vdata.get("models_generated")
        row += 1
        val_ws[f"A{row}"] = "Cache Entries"; val_ws[f"B{row}"] = model.get("generation_stats", {}).get("forecast_cache_entries")

        wb.save(out)
        self._log("info", f"Excel saved: {out}")
        
        # Also save a "latest" version for easy access (similar to financials_annual_modeling_latest.json)
        latest_filename = f"financial_model_{model['model_type']}_latest.xlsx"
        latest_path = self.models_dir / latest_filename
        wb.save(latest_path)
        self._log("info", f"Latest Excel saved: {latest_path}")
        
        return out

    def save_model_to_csv(self, model: Dict[str, Any]) -> List[pathlib.Path]:
        self._ensure_dirs()
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        saved: List[pathlib.Path] = []
        for name, data in model.get("model_components", {}).items():
            if isinstance(data, pd.DataFrame):
                # Save timestamped version
                p = self.models_dir / f"{name}_{model['ticker']}_{ts}.csv"
                data.to_csv(p, index=False)
                saved.append(p)
                self._log("info", f"CSV saved: {p}")
                
                # Also save latest version
                latest_p = self.models_dir / f"{name}_latest.csv"
                data.to_csv(latest_p, index=False)
                self._log("info", f"Latest CSV saved: {latest_p}")
        return saved


def _parse_args():
    p = argparse.ArgumentParser(description="Generate comprehensive financial models (deterministic DCF + optional LLM notes)")
    p.add_argument("--ticker", required=True, help="Stock ticker, e.g., NVDA")
    p.add_argument("--model", choices=["dcf","comparable","comprehensive"], default="comprehensive")
    p.add_argument("--years", type=int, default=5, help="Projection years (default: 5)")
    p.add_argument("--term-growth", type=float, default=None, help="Terminal growth rate (omit to auto-infer)")
    p.add_argument("--wacc", type=float, default=None, help="Override WACC (e.g., 0.095). If omitted, auto-infer.")
    p.add_argument("--data-file", type=str, default=None, help="Path to financials_annual_modeling_latest.json")
    # LLM narrative generation is now always enabled for production use
    # Output saving is now always enabled - Excel is default, CSV optional  
    p.add_argument("--save-csv", action="store_true", help="Additionally save model components to CSVs")
    p.add_argument("--strategy", type=str, default=None, help="Force a specific forecast strategy (e.g., saas_dcf, generic_dcf)")
    p.add_argument("--peers", type=str, default=None, help="Comma separated peer tickers for comps")
    p.add_argument("--sensitivities", action="store_true", help="Generate sensitivity matrices (WACC vs TG & Growth vs Margin)")
    p.add_argument("--first-year-growth", type=float, default=None, help="Override first projection year revenue growth (e.g., 0.18)")
    p.add_argument("--margin-uplift", type=float, default=None, help="Apply a uniform margin uplift (additive) across projection years (e.g., 0.02)")
    # Override params
    p.add_argument("--capex-rate", type=float, default=None, help="Override CapEx as % revenue (e.g., 0.05)")
    p.add_argument("--margin-target", type=float, default=None, help="Target EBITDA margin in final projection year (e.g., 0.35)")
    p.add_argument("--margin-ramp", type=float, default=None, help="Per-year EBITDA margin relative increase (e.g., 0.02)")
    p.add_argument("--da-rate", type=float, default=None, help="Depreciation & Amortization as % revenue (e.g., 0.04)")
    p.add_argument("--nwc-method", choices=["ratio","delta2pct"], default=None, help="Working capital change method")
    p.add_argument("--payout-ratio", type=float, default=None, help="Payout ratio for bank excess return model")
    p.add_argument("--cap-rate", type=float, default=None, help="Cap rate for REIT NAV")
    p.add_argument("--roe-target", type=float, default=None, help="Target ROE for bank model (e.g., 0.12)")
    p.add_argument("--maint-capex-pct-da", type=float, default=None, help="Maintenance CapEx as % of D&A for REIT (default 0.5)")
    p.add_argument("--energy-ebitda-multiple", type=float, default=None, help="Energy NAV forward EBITDA multiple override")
    p.add_argument("--nwc-ratio", type=float, default=None, help="Explicit NWC ratio (Working Capital / Revenue) override for ratio method")
    p.add_argument("--margin-curve", type=str, default=None, help="Comma list of EBITDA margin percentages (e.g., 30,32,34) overriding ramp/target")
    p.add_argument("--stats", action="store_true", help="Print generation stats and exit")
    # LLM parameter assist flags
    p.add_argument("--llm-params", action="store_true", help="Invoke LLM to propose refined parameter overrides (safe bounded)")
    p.add_argument("--llm-param-temp", type=float, default=0.1, help="LLM temperature for parameter assist")
    p.add_argument("--llm-skip-wacc", action="store_true", help="Disallow WACC delta proposal (ignore any wacc_delta)")
    return p.parse_args()


def main():
    args = _parse_args()
    gen = FinancialModelGenerator(args.ticker, data_file=args.data_file, no_llm=False)  # LLM always enabled

    if args.stats:
        gen._log("info", f"Models generated: {gen.models_generated}")
        gen._log("info", f"Analysis sections: {gen.analysis_sections}")
        gen._log("info", f"Data processed: {gen.data_points_processed}")
        return 0

    try:
        # Populate overrides (user-specified)
        user_overrides = {k: v for k,v in {
            "capex_rate": args.capex_rate,
            "margin_target": args.margin_target,
            "margin_ramp": args.margin_ramp,
            "da_rate": args.da_rate,
            "nwc_method": args.nwc_method,
            "payout_ratio": args.payout_ratio,
            "cap_rate": args.cap_rate,
            "roe_target": args.roe_target,
            "maint_capex_pct_da": args.maint_capex_pct_da,
            "energy_ebitda_multiple": args.energy_ebitda_multiple,
            "nwc_ratio": args.nwc_ratio,
            "margin_curve": [float(x)/100.0 for x in args.margin_curve.split(',')] if args.margin_curve else None,
            "first_year_growth": args.first_year_growth,
            "margin_uplift": args.margin_uplift,
        }.items() if v is not None}
        gen.overrides = dict(user_overrides)
        peers = [p.strip().upper() for p in args.peers.split(',')] if args.peers else None
        baseline_model = None
        override_wacc_final = args.wacc
        if args.llm_params:  # LLM always enabled
            # Lean baseline run first for context
            baseline_model = gen.generate_financial_model(
                model_type=args.model,
                projection_years=args.years,
                term_growth=args.term_growth,
                override_wacc=args.wacc,
                strategy=args.strategy,
                peers=peers,
                generate_sensitivities=False,
                lean=True,
            )
            llm_prop = gen.propose_llm_parameter_overrides(baseline_model, args.years, args.term_growth, args.strategy, temperature=args.llm_param_temp)
            if llm_prop:
                # Apply mapped overrides (excluding special __override_wacc__ key)
                for k,v in llm_prop.items():
                    if k == '__override_wacc__':
                        if not args.llm_skip_wacc:
                            override_wacc_final = v
                        continue
                    # Do not overwrite user explicit overrides unless absent
                    if k not in gen.overrides:
                        gen.overrides[k] = v
        # Final (full) model generation with merged overrides
        model = gen.generate_financial_model(
            model_type=args.model,
            projection_years=args.years,
            term_growth=args.term_growth,
            override_wacc=override_wacc_final,
            strategy=args.strategy,
            peers=peers,
            generate_sensitivities=args.sensitivities,
        )
        saved = []
        # Always save to Excel in production use
        saved.append(gen.save_model_to_excel(model))
        if args.save_csv:
            saved.extend(gen.save_model_to_csv(model))

        gen._log("info", f"Model type: {args.model}")
        gen._log("info", f"Analysis sections: {model['generation_stats']['analysis_sections']}")
        gen._log("info", f"Data points processed: {model['generation_stats']['data_points_processed']}")

        if saved:
            gen._log("info", "Saved files:")
            for p in saved:
                gen._log("info", f"  {p}")

        # Brief valuation echo
        val = model.get("valuation_summary") or {}
        if val:
            gen._log("info", f"Implied price: {val.get('Implied Price')} (EV: {val.get('Enterprise Value')})")

        return 0
    except Exception as e:
        import traceback
        tb = traceback.format_exc(limit=8)
        gen._log("error", f"Model generation failed: {e}\n{tb}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
