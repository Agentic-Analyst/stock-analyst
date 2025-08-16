"""forecast_strategies.py

Deterministic sector / business-model specific forecasting strategies used by
FinancialModelGenerator. Each strategy implements:

    forecast(generator, metrics, projection_years, term_growth, override_wacc) -> dict

Return payload must contain:
  - dcf_model : pd.DataFrame (core projection / model table)
  - valuation_summary : dict (contains at least Implied Price or blended variant)
  - strategy_name : str

Override parameters (generator.overrides) recognized across strategies:
  Generic / SaaS / Utility / Energy / REIT:
    first_year_growth, margin_target, margin_ramp, margin_uplift,
    capex_rate, da_rate, nwc_method (ratio|delta2pct), nwc_ratio, margin_curve
  REIT: cap_rate, maint_capex_pct_da
  Bank: payout_ratio, roe_target
  Energy: energy_ebitda_multiple

All math is purposefully straightforward & auditable (no stochastic / LLM).
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List
import pandas as pd

# Centralized default parameter sequences (easier to tweak / externalize later)
DEFAULTS = {
    "generic_growth_seq": [0.15, 0.12, 0.10, 0.08, 0.06],
    "saas_growth_seq":    [0.25, 0.20, 0.18, 0.15, 0.12],
    "utility_growth_seq": [0.05, 0.04, 0.035, 0.03, 0.025],
}


class ForecastStrategy:
    name: str = "base"
    description: str = "Base abstract strategy"

    def applies_to(self, sector: Optional[str], industry: Optional[str]) -> bool:  # pragma: no cover
        return False

    def forecast(self, generator, metrics: Dict[str, Any], projection_years: int,
                 term_growth: float, override_wacc: Optional[float]) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class GenericDCFStrategy(ForecastStrategy):
    name = "generic_dcf"
    description = "Generic FCFF DCF (broad fallback)"

    def applies_to(self, sector: Optional[str], industry: Optional[str]) -> bool:
        return True  # Always usable (fallback)

    # --- helpers ---
    def _default_growth_seq(self, projection_years: int) -> List[float]:
        seq = list(DEFAULTS["generic_growth_seq"])  # copy
        if projection_years < len(seq):
            return seq[:projection_years]
        if projection_years > len(seq):
            seq += [max(seq[-1] - 0.01, 0.03)] * (projection_years - len(seq))
        return seq

    def forecast(self, generator, metrics: Dict[str, Any], projection_years: int,
                 term_growth: float, override_wacc: Optional[float]) -> Dict[str, Any]:
        is_map = metrics["historical_financials"].get("income_statement", {})
        bs_map = metrics["historical_financials"].get("balance_sheet", {})
        if not is_map or not bs_map:
            raise ValueError("Income statement and balance sheet required for DCF.")
        latest = max(is_map.keys())
        base_is = is_map[latest]; base_bs = bs_map[latest]
        rev0 = generator._num(base_is.get("Total Revenue")) or generator._num(base_is.get("Operating Revenue")) or 0.0
        ebitda0 = generator._num(base_is.get("EBITDA")) or generator._num(base_is.get("Normalized EBITDA"))
        ebit0 = generator._num(base_is.get("EBIT")) or generator._num(base_is.get("Operating Income"))
        da0 = generator._num(base_is.get("Depreciation And Amortization")) or generator._num(base_is.get("Reconciled Depreciation"))
        if da0 is None and ebit0 is not None and ebitda0 is not None:
            da0 = max(0.0, ebitda0 - ebit0)
        tax_rate = generator._infer_tax_rate(base_is)

        ov = getattr(generator, 'overrides', {}) or {}
        growth_seq = self._default_growth_seq(projection_years)
        if 'first_year_growth' in ov and projection_years > 0:
            growth_seq[0] = float(ov['first_year_growth'])
        base_margin = (ebitda0 / rev0) if (rev0 and ebitda0) else 0.30
        if ov.get('margin_target') is not None:
            target = float(ov['margin_target'])
            step = (target - base_margin) / max(projection_years - 1, 1)
            margin_seq = [max(0.0, min(0.85, base_margin + step * i)) for i in range(projection_years)]
        else:
            ramp = float(ov.get('margin_ramp', 0.01))
            margin_seq = [min(0.85, base_margin * (1 + ramp * i)) for i in range(projection_years)]
        if 'margin_uplift' in ov:
            uplift = 1 + float(ov['margin_uplift'])
            margin_seq = [min(0.90, m * uplift) for m in margin_seq]
        # margin_curve explicit override (takes precedence)
        if 'margin_curve' in ov:
            try:
                curve = [float(x) for x in ov['margin_curve']]
                if curve:
                    if len(curve) < projection_years:
                        curve += [curve[-1]] * (projection_years - len(curve))
                    margin_seq = [min(0.90, max(0.0, v)) for v in curve[:projection_years]]
                    generator.diagnostics.append('override:margin_curve')
            except Exception:
                generator.diagnostics.append('invalid:margin_curve')

        nwc0 = generator._compute_nwc(base_bs)
        da_rate = float(ov.get('da_rate', (da0 / rev0) if (rev0 and da0) else 0.03))
        capex_rate = float(ov.get('capex_rate', 0.04))
        if 'da_rate' not in ov and (da0 is None or rev0 == 0):
            generator.diagnostics.append('default:da_rate')
        if 'capex_rate' not in ov:
            generator.diagnostics.append('default:capex_rate')
        # explicit nwc ratio override
        explicit_nwc_ratio = ov.get('nwc_ratio')
        if explicit_nwc_ratio is not None:
            try:
                explicit_nwc_ratio = float(explicit_nwc_ratio)
                generator.diagnostics.append('override:nwc_ratio')
            except Exception:
                explicit_nwc_ratio = None
                generator.diagnostics.append('invalid:nwc_ratio')

        years = list(range(1, projection_years + 1))
        rev=[]; ebitda=[]; da=[]; ebit=[]; nopat=[]; capex=[]; dNWC=[]; fcf=[]
        for i in range(projection_years):
            g = growth_seq[i]
            r = rev0 * (1 + g) if i == 0 else rev[-1] * (1 + g)
            m = margin_seq[i]
            ebd = r * m
            d_a = r * da_rate
            ebt = ebd - d_a
            npat = ebt * (1 - tax_rate)
            # NWC change
            nwc_method = ov.get('nwc_method')
            if nwc_method == 'delta2pct':
                prev_r = rev[i - 1] if i > 0 else rev0
                dnwc = 0.02 * (r - prev_r)
            else:  # ratio method
                if explicit_nwc_ratio is not None and rev0 > 0:
                    nwc_ratio = explicit_nwc_ratio
                    if i == 0:
                        generator.diagnostics.append('using_explicit_nwc_ratio')
                    prev_nwc = (rev[i - 1] * nwc_ratio) if i > 0 and rev[i - 1] else nwc0
                    prev_nwc = prev_nwc if prev_nwc is not None else 0.0
                    dnwc = r * nwc_ratio - prev_nwc
                elif rev0 > 0 and nwc0 is not None:
                    nwc_ratio = nwc0 / rev0
                    prev_nwc = (rev[i - 1] * nwc_ratio) if i > 0 else nwc0
                    prev_nwc = prev_nwc if prev_nwc is not None else 0.0
                    dnwc = r * nwc_ratio - prev_nwc
                else:
                    prev_r = rev[i - 1] if i > 0 else rev0
                    dnwc = 0.02 * (r - prev_r)
            cpx = r * capex_rate
            fc = npat + d_a - cpx - dnwc
            rev.append(r); ebitda.append(ebd); da.append(d_a); ebit.append(ebt)
            nopat.append(npat); capex.append(cpx); dNWC.append(dnwc); fcf.append(fc)
        if 'first_year_growth' in ov:
            generator.diagnostics.append('override:first_year_growth')
        if 'margin_target' in ov:
            generator.diagnostics.append('override:margin_target')
        if 'margin_ramp' in ov:
            generator.diagnostics.append('override:margin_ramp')
        if 'margin_uplift' in ov:
            generator.diagnostics.append('override:margin_uplift')

        wacc = generator._get_wacc(metrics.get("company_data", {}), override_wacc)
        self._log("info", f"Using WACC: {wacc:.4f} for DCF valuation")
        t_fcf = fcf[-1] * (1 + term_growth)
        denom = max(wacc - term_growth, 1e-6)
        tv = t_fcf / denom
        dfs = [(1 / ((1 + wacc) ** t)) for t in years]
        pv_fcfs = [fcf[t - 1] * dfs[t - 1] for t in years]
        pv_tv = tv * dfs[-1]
        ev = sum(pv_fcfs) + pv_tv
        cd = metrics.get("company_data", {})
        cs = (cd.get("capital_structure", {}) or {})
        md = (cd.get("market_data", {}) or {})
        net_debt = generator._num(cs.get("net_debt"))
        if net_debt is None:
            debt = generator._num(cs.get("total_debt"), 0.0) or 0.0
            cash = generator._num(cs.get("total_cash"), 0.0) or 0.0
            net_debt = debt - cash
        equity_value = ev - net_debt
        shares = generator._num(md.get("shares_outstanding_basic")) or 0.0
        implied_price = (equity_value / shares) if shares else None

        dcf_df = pd.DataFrame({
            "Year": years,
            "Revenue": rev,
            "EBITDA": ebitda,
            "D&A": da,
            "EBIT": ebit,
            "NOPAT": nopat,
            "CapEx": capex,
            "ΔNWC": dNWC,
            "FCFF": fcf,
            "Discount Factor": dfs,
            "PV FCFF": pv_fcfs,
        })
        valuation = {
            "Strategy": self.name,
            "WACC": wacc,
            "Terminal Growth": term_growth,
            "Terminal Value (undiscounted)": tv,
            "PV of FCFF": sum(pv_fcfs),
            "PV of TV": pv_tv,
            "Enterprise Value": ev,
            "Net Debt": net_debt,
            "Equity Value": equity_value,
            "Shares (basic)": shares,
            "Implied Price": implied_price,
        }
        return {"dcf_model": dcf_df, "valuation_summary": valuation, "strategy_name": self.name}


class SaaSStrategy(GenericDCFStrategy):
    name = "saas_dcf"
    description = "SaaS-tailored DCF with elevated early growth & Rule of 40"

    def applies_to(self, sector: Optional[str], industry: Optional[str]) -> bool:
        ind = (industry or "").lower(); sec = (sector or "").lower()
        return ("software" in ind) or ("application" in ind) or (sec == "technology" and "software" in ind)

    def _default_growth_seq(self, projection_years: int) -> List[float]:
        seq = list(DEFAULTS["saas_growth_seq"])  # copy
        if projection_years < len(seq):
            return seq[:projection_years]
        if projection_years > len(seq):
            seq += [max(seq[-1] - 0.02, 0.05)] * (projection_years - len(seq))
        return seq

    def forecast(self, generator, metrics: Dict[str, Any], projection_years: int,
                 term_growth: float, override_wacc: Optional[float]) -> Dict[str, Any]:
        result = super().forecast(generator, metrics, projection_years, term_growth, override_wacc)
        df = result["dcf_model"].copy()
        if "Revenue" in df.columns:
            df["Revenue Growth"] = df["Revenue"].pct_change().fillna(0.0)
            df["EBITDA Margin"] = df["EBITDA"] / df["Revenue"].replace({0: None})
            df["Rule of 40"] = (df["Revenue Growth"].fillna(0) + df["EBITDA Margin"].fillna(0)).round(4)
        result["dcf_model"] = df
        result["valuation_summary"]["Strategy"] = self.name
        return result


class REITStrategy(ForecastStrategy):
    name = "reit_dcf"
    description = "REIT FFO/AFFO & NAV blended with DCF"

    def applies_to(self, sector: Optional[str], industry: Optional[str]) -> bool:
        ind = (industry or "").lower()
        return "reit" in ind or "real estate" in ind

    def forecast(self, generator, metrics: Dict[str, Any], projection_years: int,
                 term_growth: float, override_wacc: Optional[float]) -> Dict[str, Any]:
        base = GenericDCFStrategy().forecast(generator, metrics, projection_years, term_growth, override_wacc)
        dcf_df = base["dcf_model"].copy()
        is_map = metrics["historical_financials"].get("income_statement", {})
        cf_map = metrics["historical_financials"].get("cash_flow", {})
        latest = max(is_map.keys()) if is_map else None
        base_is = is_map.get(latest, {}) if latest else {}
        base_cf = cf_map.get(latest, {}) if latest else {}
        net_income = generator._num(base_is.get("Net Income")) or generator._num(base_is.get("Net Income Common Stockholders")) or 0.0
        da = generator._num(base_is.get("Depreciation And Amortization")) or 0.0
        gains = generator._num(base_is.get("Gain On Sale Of Ppe")) or 0.0
        ov = getattr(generator, 'overrides', {}) or {}
        maint_capex_pct_da = float(ov.get('maint_capex_pct_da', 0.5))
        maint_capex = maint_capex_pct_da * da
        ffo = net_income + da - gains
        affo = ffo - maint_capex
        rev = dcf_df.get("Revenue", []).tolist() if "Revenue" in dcf_df.columns else []
        ffo_list=[]; affo_list=[]; curr_ffo=ffo; curr_affo=affo
        for i, r in enumerate(rev):
            if i == 0:
                ffo_list.append(curr_ffo); affo_list.append(curr_affo); continue
            g = (rev[i] / rev[i-1]) - 1 if rev[i-1] else 0.0
            curr_ffo *= (1+g); curr_affo *= (1+g)
            ffo_list.append(curr_ffo); affo_list.append(curr_affo)
        if rev:
            reit_df = pd.DataFrame({"Year": dcf_df["Year"], "FFO": ffo_list, "AFFO": affo_list})
            base.setdefault("extra_components", {})["reit_ffo_affo"] = reit_df
        cap_rate = float(ov.get('cap_rate', 0.06))
        noi_next = dcf_df["EBITDA"].iloc[0] if "EBITDA" in dcf_df.columns else None
        nav_gross = (noi_next / cap_rate) if (noi_next is not None and cap_rate > 0) else None
        cd = metrics.get("company_data", {})
        cs = (cd.get("capital_structure", {}) or {})
        md = (cd.get("market_data", {}) or {})
        net_debt = generator._num(cs.get("net_debt"))
        if net_debt is None:
            debt = generator._num(cs.get("total_debt"), 0.0) or 0.0
            cash = generator._num(cs.get("total_cash"), 0.0) or 0.0
            net_debt = debt - cash
        nav_equity = (nav_gross - net_debt) if (nav_gross is not None and net_debt is not None) else None
        shares = generator._num(md.get("shares_outstanding_basic")) or 0.0
        nav_price = (nav_equity / shares) if (shares and nav_equity is not None) else None
        dcf_price = base["valuation_summary"].get("Implied Price")
        if dcf_price and nav_price:
            base["valuation_summary"]["Implied Price (blended)"] = 0.5 * dcf_price + 0.5 * nav_price
        base["valuation_summary"]["NAV Price"] = nav_price
        base["valuation_summary"]["Cap Rate"] = cap_rate
        base["valuation_summary"]["Strategy"] = self.name
        return base


class BankStrategy(ForecastStrategy):
    name = "bank_excess_returns"
    description = "Bank residual income (excess returns) model"

    def applies_to(self, sector: Optional[str], industry: Optional[str]) -> bool:
        ind = (industry or "").lower()
        return any(k in ind for k in ["bank", "thrifts", "savings", "financial services"])

    def forecast(self, generator, metrics: Dict[str, Any], projection_years: int,
                 term_growth: float, override_wacc: Optional[float]) -> Dict[str, Any]:
        is_map = metrics["historical_financials"].get("income_statement", {})
        bs_map = metrics["historical_financials"].get("balance_sheet", {})
        if not is_map or not bs_map:
            raise ValueError("Statements required.")
        latest = max(is_map.keys())
        base_is = is_map[latest]; base_bs = bs_map[latest]
        net_income = generator._num(base_is.get("Net Income")) or generator._num(base_is.get("Net Income Common Stockholders")) or 0.0
        total_assets = generator._num(base_bs.get("Total Assets")) or 0.0
        total_liab = generator._num(base_bs.get("Total Liabilities Net Minority Interest")) or generator._num(base_bs.get("Total Liabilities")) or 0.0
        goodwill = generator._num(base_bs.get("Goodwill")) or 0.0
        intang = generator._num(base_bs.get("Intangible Assets")) or 0.0
        equity = total_assets - total_liab
        tangible_book = max(equity - goodwill - intang, 1.0)
        cs = (metrics.get("company_data", {}) or {}).get("capital_structure", {})
        beta = generator._num(cs.get("beta"), 1.1) or 1.1
        rf = 0.045; erp = 0.05
        ke = rf + beta * erp
        roe_curr = (net_income / tangible_book) if tangible_book else 0.10
        ov = getattr(generator, 'overrides', {}) or {}
        target_roe = float(ov.get('roe_target', 0.12))
        roe_seq=[]
        for i in range(projection_years):
            w = (i + 1) / projection_years
            roe_seq.append(roe_curr * (1 - w) + target_roe * w)
        payout = float(ov.get('payout_ratio', 0.30))
        years = list(range(1, projection_years + 1))
        tbv_begin=[]; net_inc=[]; dividends=[]; excess=[]; tbv_end=[]
        tbv = tangible_book
        for roe in roe_seq:
            tbv_begin.append(tbv)
            ni = tbv * roe
            net_inc.append(ni)
            div = ni * payout
            dividends.append(div)
            excess_ret = (roe - ke) * tbv
            excess.append(excess_ret)
            tbv = tbv + ni - div
            tbv_end.append(tbv)
        dfs = [(1 / ((1 + ke) ** t)) for t in years]
        pv_excess = [excess[t - 1] * dfs[t - 1] for t in years]
        terminal_excess = excess[-1] * (1 + term_growth) / (ke - term_growth) if ke > term_growth else excess[-1] * 20
        pv_terminal = terminal_excess * dfs[-1]
        equity_value = tangible_book + sum(pv_excess) + pv_terminal
        md = (metrics.get("company_data", {}) or {}).get("market_data", {})
        shares = generator._num(md.get("shares_outstanding_basic")) or 0.0
        implied_price = (equity_value / shares) if shares else None
        df = pd.DataFrame({
            "Year": years,
            "Beg TBV": tbv_begin,
            "ROE": roe_seq,
            "Net Income": net_inc,
            "Dividends": dividends,
            "End TBV": tbv_end,
            "Excess Return": excess,
            "Discount Factor": dfs,
            "PV Excess": pv_excess,
        })
        valuation = {
            "Strategy": self.name,
            "Cost of Equity": ke,
            "WACC": ke,  # unify key name for sensitivities
            "Terminal Growth": term_growth,
            "PV Excess Returns": sum(pv_excess),
            "PV Terminal Excess": pv_terminal,
            "Equity Value": equity_value,
            "Implied Price": implied_price,
            "Tangible Book": tangible_book,
        }
        return {"dcf_model": df, "valuation_summary": valuation, "strategy_name": self.name}


class UtilityStrategy(GenericDCFStrategy):
    name = "utility_dcf"
    description = "Utility low-growth FCFF DCF"

    def applies_to(self, sector: Optional[str], industry: Optional[str]) -> bool:
        ind = (industry or "").lower()
        return any(k in ind for k in ["utility", "utilities", "power", "electric"])

    def _default_growth_seq(self, projection_years: int) -> List[float]:
        seq = list(DEFAULTS["utility_growth_seq"])  # copy
        if projection_years < len(seq):
            return seq[:projection_years]
        if projection_years > len(seq):
            seq += [max(seq[-1] - 0.005, 0.015)] * (projection_years - len(seq))
        return seq


class EnergyStrategy(GenericDCFStrategy):
    name = "energy_nav_dcf"
    description = "Energy hybrid DCF + EBITDA multiple NAV"

    def applies_to(self, sector: Optional[str], industry: Optional[str]) -> bool:
        ind = (industry or "").lower()
        return any(k in ind for k in ["oil", "gas", "exploration", "production", "energy"])

    def forecast(self, generator, metrics: Dict[str, Any], projection_years: int,
                 term_growth: float, override_wacc: Optional[float]) -> Dict[str, Any]:
        base = super().forecast(generator, metrics, projection_years, term_growth, override_wacc)
        dcf_df = base["dcf_model"]
        cd = metrics.get("company_data", {})
        md = (cd.get("market_data", {}) or {})
        current_ev = generator._num(md.get("enterprise_value"))
        latest_ebitda = dcf_df["EBITDA"].iloc[0] if "EBITDA" in dcf_df.columns else None
        current_ev_ebitda = (current_ev / latest_ebitda) if (current_ev and latest_ebitda) else None
        ov = getattr(generator, 'overrides', {}) or {}
        fwd_multiple = float(ov.get('energy_ebitda_multiple', current_ev_ebitda if current_ev_ebitda and 2 < current_ev_ebitda < 15 else 6.0))
        if latest_ebitda is not None:
            nav_ev = latest_ebitda * fwd_multiple
            base["valuation_summary"]["NAV EV (EBITDA multiple)"] = nav_ev
            if base["valuation_summary"].get("Enterprise Value"):
                base_ev = base["valuation_summary"]["Enterprise Value"]
                blended_ev = 0.6 * base_ev + 0.4 * nav_ev
                net_debt = base["valuation_summary"].get("Net Debt") or 0.0
                shares = base["valuation_summary"].get("Shares (basic)") or 0.0
                blended_equity = blended_ev - net_debt
                base["valuation_summary"]["Blended EV"] = blended_ev
                if shares:
                    base["valuation_summary"]["Implied Price (blended)"] = blended_equity / shares
        base["valuation_summary"]["Strategy"] = self.name
        return base


# Strategy registry in priority order (generic last as fallback)
STRATEGIES: List[ForecastStrategy] = [
    REITStrategy(),
    BankStrategy(),
    UtilityStrategy(),
    EnergyStrategy(),
    SaaSStrategy(),
    GenericDCFStrategy(),
]


def get_strategy_by_name(name: str) -> Optional[ForecastStrategy]:
    for s in STRATEGIES:
        if s.name == name:
            return s
    return None

