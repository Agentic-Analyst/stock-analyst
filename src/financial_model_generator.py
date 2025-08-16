
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

▶ Usage examples:
    python financial_model_generator.py --ticker NVDA --model dcf --data-file /path/to/financials_annual_modeling_latest.json --save-excel
    python financial_model_generator.py --ticker AAPL --model comparable --years 5 --save-csv
    python financial_model_generator.py --ticker TSLA --model comprehensive --save-excel --no-llm --wacc 0.095 --term-growth 0.025
"""

from __future__ import annotations
import os, json, argparse, pathlib, math
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd

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
        # Core paths
        self.ticker = ticker.upper()
        self.company_dir = DATA_ROOT / self.ticker
        self.financials_dir = self.company_dir / "financials"
        self.models_dir = self.company_dir / "models"

        # Logger placeholder
        self.logger = None

        # Optional LLM client (now narrative-only)
        self.llm_function = None if no_llm else _try_load_llm()

        # Stats
        self.models_generated = 0
        self.analysis_sections = 0
        self.data_points_processed = 0

        # Cached data
        self._financial_data = None
        self._company_info = None

        # Explicit data file (if provided)
        self._explicit_data_file = pathlib.Path(data_file) if data_file else None

        # User overrides dictionary
        self.overrides = {}

        # Diagnostics (warnings about missing or defaulted fields)
        self.diagnostics = []

        # Forecast cache {(strategy, years, term_growth, wacc_override, overrides_hash): result_dict}
        self._forecast_cache = {}

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
        if tr and 0 < tr < 0.6:
            return tr
        prov = self._num(base_is.get("Tax Provision"), 0.0)
        pretax = self._num(base_is.get("Pretax Income"))
        if pretax and pretax != 0:
            cand = prov / pretax
            if 0 < cand < 0.6:
                return float(cand)
        return 0.25

    def _compute_nwc(self, bs_row: Dict[str, Any]) -> float:
        ar = self._num(bs_row.get("Accounts Receivable"), 0.0)
        inv = 0.0
        for k in ["Inventory", "Finished Goods", "Work In Process", "Raw Materials"]:
            inv += self._num(bs_row.get(k), 0.0) or 0.0
        ap = self._num(bs_row.get("Accounts Payable"), 0.0)
        return float(ar + inv - ap)

    def _get_wacc(self, company_data: Dict[str, Any], override_wacc: Optional[float]) -> float:
        if isinstance(override_wacc, (int, float)) and 0.0 < override_wacc < 0.5:
            return float(override_wacc)

        cs = (company_data or {}).get("capital_structure", {}) or {}
        md = (company_data or {}).get("market_data", {}) or {}

        beta = self._num(cs.get("beta"), 1.2) or 1.2
        rf = self._num(cs.get("risk_free_rate"), 0.045) or 0.045
        erp = self._num(cs.get("equity_risk_premium"), 0.05) or 0.05
        ke = rf + beta * erp

        debt = self._num(cs.get("total_debt"), 0.0) or 0.0
        cash = self._num(cs.get("total_cash"), 0.0) or 0.0
        net_debt = debt - cash

        E = self._num(md.get("market_cap"), 0.0) or 0.0
        D = max(net_debt, 0.0) if net_debt is not None else 0.0  # if net cash, treat D~0 for weights
        V = max(E + D, 1.0)
        kd = max(rf, 0.03)  # conservative floor
        tax = 0.21
        wacc = (E / V) * ke + (D / V) * kd * (1 - tax)
        self._log("info", f"Computed WACC: {wacc:.4f} (Ke={ke:.4f}, Kd={kd:.4f}, E={E:.2f}, D={D:.2f})")
        return float(max(0.04, min(wacc, 0.15)))

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
            prompt = f"""
You are a senior equity analyst. Create bullet-point sections for {self.ticker}:
1) Executive Summary  2) Financial Projections (5y)  3) Valuation (DCF + multiples)
4) Sensitivities (drivers, bull/base/bear)  5) Investment Recommendation.
Be specific and quantitative when possible; keep each section under ~120 words.
"""
            msgs = [
                {"role": "system", "content": "You are a senior financial analyst producing concise research-ready notes."},
                {"role": "user", "content": prompt},
            ]
            resp = self.llm_function(msgs, temperature=0.2)
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
                                 term_growth: float = 0.03, override_wacc: Optional[float] = None,
                                 strategy: Optional[str] = None, peers: Optional[List[str]] = None,
                                 generate_sensitivities: bool = False) -> Dict[str, Any]:
        wacc_str = 'auto' if override_wacc is None else f"{override_wacc:.3f}"
        self._log("info", f"Generating {model_type} model for {self.ticker} "
                          f"({projection_years}y, g={term_growth:.3f}, wacc={wacc_str})")
        data = self._load_financial_data()
        metrics = self._extract_key_financial_metrics(data)

        components: Dict[str, Any] = {}
        valuation_summary: Dict[str, Any] = {}

        chosen_strategy_name = None
        strat = None
        if model_type in ("dcf", "comprehensive"):
            strat = self._select_strategy(strategy, metrics)
            chosen_strategy_name = strat.name
            # Caching key
            # Convert lists to strings for hashing
            hashable_overrides = {}
            for k, v in self.overrides.items():
                if isinstance(v, list):
                    hashable_overrides[k] = str(v)
                else:
                    hashable_overrides[k] = v
            ov_hash = hash(tuple(sorted(hashable_overrides.items())))
            cache_key = (strat.name, projection_years, round(term_growth,6), override_wacc if override_wacc is None else round(override_wacc,6), ov_hash)
            if cache_key in self._forecast_cache:
                strat_outputs = self._forecast_cache[cache_key]
                self._log("info", f"Cache hit for strategy {strat.name}")
            else:
                strat_outputs = strat.forecast(self, metrics, projection_years, term_growth, override_wacc)
                self._forecast_cache[cache_key] = strat_outputs
            dcf_df = strat_outputs.get("dcf_model")
            valuation_summary = strat_outputs.get("valuation_summary", {})
            valuation_summary["Strategy"] = strat_outputs.get("strategy_name")
            components["dcf_model"] = dcf_df
            components["valuation_summary"] = valuation_summary
            # Extra components (e.g., FFO/AFFO) from strategy
            extra = strat_outputs.get("extra_components") or {}
            for k,v in extra.items():
                components[k] = v
            # Sensitivities
            if generate_sensitivities and strat and valuation_summary.get("WACC"):
                sens = self._generate_sensitivities(strat, metrics, projection_years,
                                                    valuation_summary.get("WACC"), term_growth, term_growth, override_wacc)
                for k,v in sens.items():
                    components[k] = v

        if model_type in ("comparable", "comprehensive"):
            comps_df = self._create_comparable_analysis_dataframe(metrics)
            components["comparable_analysis"] = comps_df
            if peers:
                peer_list = [p.strip().upper() for p in peers if p.strip().upper() not in (self.ticker, "")]
                if peer_list:
                    peer_df = self._create_peer_comps(metrics, peer_list)
                    if peer_df is not None:
                        components["peer_comparables"] = peer_df
        # LLM used only for narrative if enabled
        llm_analysis = self._generate_llm_financial_analysis(metrics, model_type)

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
            },
            "validation": self._validation_summary(chosen_strategy_name or "n/a", valuation_summary),
        }
        self.models_generated += 1
        return model

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
                sheet_name = {
                    "dcf_model": "DCF Model",
                    "comparable_analysis": "Comparable Analysis",
                    "peer_comparables": "Peer Comps",
                    "reit_ffo_affo": "FFO_AFFO",
                    "sensitivity_wacc_term": "Sens WACC-TG",
                    "sensitivity_growth_margin": "Sens Growth-Margin",
                }.get(key, key[:31])
                wsdf = wb.create_sheet(sheet_name)
                for ridx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
                    for cidx, value in enumerate(row, 1):
                        cell = wsdf.cell(row=ridx, column=cidx, value=value)
                        if ridx == 1:
                            cell.font = Font(bold=True)
                            cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")

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
            val_ws[f"B{row}"] = overrides[k]
            row += 1
        # Missing valuation fields
        row += 1
        val_ws[f"A{row}"] = "Missing Valuation Fields"; val_ws[f"A{row}"].font = Font(bold=True)
        mvf = vdata.get("missing_valuation_fields") or []
        row += 1
        if mvf:
            fill_warn = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
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
        return out

    def save_model_to_csv(self, model: Dict[str, Any]) -> List[pathlib.Path]:
        self._ensure_dirs()
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        saved: List[pathlib.Path] = []
        for name, data in model.get("model_components", {}).items():
            if isinstance(data, pd.DataFrame):
                p = self.models_dir / f"{name}_{model['ticker']}_{ts}.csv"
                data.to_csv(p, index=False)
                saved.append(p)
                self._log("info", f"CSV saved: {p}")
        return saved


def _parse_args():
    p = argparse.ArgumentParser(description="Generate comprehensive financial models (deterministic DCF + optional LLM notes)")
    p.add_argument("--ticker", required=True, help="Stock ticker, e.g., NVDA")
    p.add_argument("--model", choices=["dcf","comparable","comprehensive"], default="comprehensive")
    p.add_argument("--years", type=int, default=5, help="Projection years (default: 5)")
    p.add_argument("--term-growth", type=float, default=0.03, help="Terminal growth rate (e.g., 0.025)")
    p.add_argument("--wacc", type=float, default=None, help="Override WACC (e.g., 0.095). If omitted, auto-infer.")
    p.add_argument("--data-file", type=str, default=None, help="Path to financials_annual_modeling_latest.json")
    p.add_argument("--no-llm", action="store_true", help="Disable LLM narrative generation")
    p.add_argument("--save-excel", action="store_true", help="Save outputs to Excel")
    p.add_argument("--save-csv", action="store_true", help="Save model components to CSVs")
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
    return p.parse_args()


def main():
    args = _parse_args()
    gen = FinancialModelGenerator(args.ticker, data_file=args.data_file, no_llm=args.no_llm)

    if args.stats:
        gen._log("info", f"Models generated: {gen.models_generated}")
        gen._log("info", f"Analysis sections: {gen.analysis_sections}")
        gen._log("info", f"Data processed: {gen.data_points_processed}")
        return 0

    try:
        # Populate overrides
        gen.overrides = {k: v for k,v in {
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
        peers = [p.strip().upper() for p in args.peers.split(',')] if args.peers else None
        model = gen.generate_financial_model(
            model_type=args.model,
            projection_years=args.years,
            term_growth=args.term_growth,
            override_wacc=args.wacc,
            strategy=args.strategy,
            peers=peers,
            generate_sensitivities=args.sensitivities,
        )
        saved = []
        if args.save_excel:
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
