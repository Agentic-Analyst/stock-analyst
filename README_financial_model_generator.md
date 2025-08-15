# Financial Model Generator (Advanced DCF & Strategy Framework)

This document explains how the enhanced `financial_model_generator.py` works, the strategy architecture, available CLI options, overrides, outputs, and how to extend it.

---
## 1. Purpose
A deterministic, auditable valuation engine that:
- Builds forward financial projections and discounted cash flow (DCF) models.
- Supports sector / business-model specific forecasting via pluggable strategies.
- Generates comparable tables, optional peer comps, sensitivity matrices, REIT / bank / energy variants, and validation data.
- Optionally adds a narrative analysis with an LLM (if enabled). (Sector/industry classification removed for determinism.)

No LLM is required for core valuation math. Outputs can be saved to CSV and/or Excel.

---
## 2. Core Architecture
Component | Description
--------- | -----------
`financial_model_generator.py` | Orchestrates data loading, strategy selection, projection, valuation, peers, sensitivities, export.
`forecast_strategies.py` | Strategy pattern: each class encapsulates sector‑specific forecasting & valuation tweaks.
Strategies Registry | Ordered list: most specific first, `generic_dcf` last as fallback.
Overrides Dict | User-supplied assumption overrides injected before forecast run.
Sensitivity Engine | Re-runs strategy across grids (WACC vs Terminal Growth, Growth vs Margin).
Validation Summary | Captures strategy, overrides, missing valuation fields, diagnostics, cache stats.

---
## 3. Supported Strategies
Name | Class | Focus | Key Extras
---- | ----- | ----- | ----------
`generic_dcf` | `GenericDCFStrategy` | Broad fallback FCFF | Margin ramp/target, NWC methods
`saas_dcf` | `SaaSStrategy` | High-growth software | Rule of 40 metrics
`reit_dcf` | `REITStrategy` | Real estate / REIT | FFO & AFFO, NAV (cap rate) blend
`bank_excess_returns` | `BankStrategy` | Banks / depository | Residual (excess) returns on tangible book
`utility_dcf` | `UtilityStrategy` | Regulated utilities | Lower growth curve
`energy_nav_dcf` | `EnergyStrategy` | Energy / E&P | Blended DCF + forward EV/EBITDA NAV

Auto-selection uses (sector, industry) heuristics unless `--strategy` is supplied.

---
## 4. Data Requirements
Location: `data/<TICKER>/financials/financials_annual_modeling_latest.json` (or pass `--data-file`).
Minimal fields per strategy:
- Generic / SaaS / Utility / Energy: Income Statement + Balance Sheet (latest year) for Revenue, EBITDA/EBIT, D&A, WC items.
- REIT: Above + optional Cash Flow (for CapEx; graceful if absent).
- Bank: Income Statement + Balance Sheet (Assets, Liabilities, Goodwill, Intangibles, Net Income).

If fields are missing the engine attempts conservative defaults; some strategies may raise if core data absent.

---
## 5. CLI Usage
```
python src/financial_model_generator.py --ticker NVDA --model comprehensive --save-excel
python src/financial_model_generator.py --ticker AAPL --model dcf --strategy saas_dcf --years 6 --term-growth 0.025 --wacc 0.09 --save-csv
python src/financial_model_generator.py --ticker O --model dcf --strategy reit_dcf --cap-rate 0.065 --maint-capex-pct-da 0.45 --save-excel
python src/financial_model_generator.py --ticker JPM --strategy bank_excess_returns --payout-ratio 0.35 --roe-target 0.14 --save-csv
python src/financial_model_generator.py --ticker XOM --strategy energy_nav_dcf --energy-ebitda-multiple 5.5 --sensitivities --save-excel
python src/financial_model_generator.py --ticker NVDA --model comprehensive --peers AAPL,MSFT,AMD --sensitivities --save-excel --no-llm
```

Key flags:
Flag | Purpose
---- | -------
`--model` | `dcf`, `comparable`, or `comprehensive`
`--strategy` | Force a strategy (see list above)
`--years` | Projection horizon (default 5)
`--term-growth` | Terminal FCFF growth (g)
`--wacc` | Override WACC (else auto-inferred)
`--data-file` | Explicit JSON path override
`--no-llm` | Disable LLM narrative
`--save-excel` / `--save-csv` | Persist outputs
`--peers` | Comma list of peer tickers for multi-row comps
`--sensitivities` | Generate 2 sensitivity matrices

---
## 6. Override Parameters (Assumption Tweaks)
Flag | Stored Key | Meaning
---- | ---------- | -------
`--capex-rate` | `capex_rate` | CapEx % of revenue (generic + variants)
`--margin-target` | `margin_target` | Final-year EBITDA margin target
`--margin-ramp` | `margin_ramp` | Annual multiplicative ramp to margin
`--da-rate` | `da_rate` | D&A % of revenue
`--nwc-method` | `nwc_method` | `ratio` (default) or `delta2pct` (ΔNWC = 2% of ΔRevenue)
`--payout-ratio` | `payout_ratio` | Bank dividend payout
`--cap-rate` | `cap_rate` | REIT NOI capitalization rate for NAV
`--roe-target` | `roe_target` | Target ROE for bank model convergence
`--maint-capex-pct-da` | `maint_capex_pct_da` | REIT maintenance CapEx as % of D&A
`--energy-ebitda-multiple` | `energy_ebitda_multiple` | Forward EBITDA multiple for Energy NAV blend
`--first-year-growth` | `first_year_growth` | Override first projection year revenue growth
`--margin-uplift` | `margin_uplift` | Uniform additive EBITDA margin uplift (applied multiplicatively as (1+uplift))
`--nwc-ratio` | `nwc_ratio` | Explicit Working Capital / Revenue ratio (overrides inferred baseline)
`--margin-curve` | `margin_curve` | Comma list of EBITDA margin percentages (e.g., 30,32,34) overriding ramp/target

All keys are now CLI-exposed. `margin_curve` supersedes `margin_target` / `margin_ramp` when provided. Sensitivity engine uses transient injected values for growth/margin grid without mutating persistent overrides.

---
## 7. Sensitivity Matrices
Enabled via `--sensitivities`:
1. WACC vs Terminal Growth: Grid of implied prices varying WACC ±1–2% and g ±1%.
2. Growth vs Margin: Adjusts first-year revenue growth (−2%, 0, +2%) vs EBITDA margin uplift (−5%, 0, +5%).

Files (CSV / Excel sheets):
- `sensitivity_wacc_term`
- `sensitivity_growth_margin`

---
## 8. Peer Comparables
Supply `--peers T1,T2,...` to include peers. For each peer the same JSON structure is loaded (from its `data/<PEER>/financials/...` path) and a comparable row (EV/EBITDA, P/E, etc.) is assembled. Output sheet: `Peer Comps` (Excel) or `peer_comparables_<TICKER>_TIMESTAMP.csv` (CSV mode).

---
## 9. Excel Output Structure
Sheet | Contents
----- | --------
Executive Summary | Header info + valuation highlights
DCF Model | Projection table (or bank residual table)
Comparable Analysis | Base company valuation multiples
Peer Comps | Multi-row comparables (if peers provided)
FFO_AFFO | REIT FFO / AFFO projection (REIT only)
Sens WACC-TG | WACC vs Terminal growth grid
Sens Growth-Margin | Growth vs Margin uplift grid
LLM Analysis | Optional narrative sections (if LLM enabled)
Validation | Strategy, overrides, missing valuation fields, diagnostics (defaults/overrides), cache stats

CSV mode writes each DataFrame separately using a consistent naming pattern.

---
## 10. Validation Summary
Captures:
- Applied strategy name
- Overrides dict used
- Missing valuation fields (None values from `valuation_summary`)
- Generation counters

Useful for health monitoring / CI checks.

---
## 11. Extending with a New Strategy
1. Open `src/forecast_strategies.py`.
2. Subclass `ForecastStrategy` (or `GenericDCFStrategy` if similar base FCFF logic).
3. Implement `name`, `description`, `applies_to()`, and `forecast()` returning the contract dict.
4. Append an instance to `STRATEGIES` before the generic fallback.
5. (Optional) Add any special DataFrame(s) into `extra_components` to have them exported as sheets.

Keep math deterministic; avoid network / LLM calls inside strategies.

---
## 12. LLM Integration (Optional)
If an LLM function (`llms.gpt_4o_mini`) is importable and `--no-llm` is **not** passed a concise research-style narrative is produced (Executive Summary, Projections, Valuation, Sensitivities, Recommendation) and written to the `LLM Analysis` sheet. Classification has been removed; all valuation math & assumptions remain deterministic. Failures are non-fatal and logged as warnings.

---
## 13. Troubleshooting
Issue | Likely Cause | Fix
----- | ------------ | ---
"No financial modeling data found" | Missing JSON path | Place file under `data/<TICKER>/financials/` or use `--data-file`.
All implied prices None | Missing shares outstanding | Ensure `company_data.market_data.shares_outstanding_basic` present.
Negative or extreme WACC | Bad beta / structure inputs | Override with `--wacc`.
Bank strategy low equity value | High payout & low ROE target | Adjust `--payout-ratio` / `--roe-target`.
REIT NAV not blended | Missing EBITDA or cap rate zero | Provide cap rate (`--cap-rate`).
Energy blended price missing | Missing EBITDA or multiple | Add `--energy-ebitda-multiple`.

---
## 14. Example End-to-End (Comprehensive with Peers & Sensitivities)
```
python src/financial_model_generator.py \
  --ticker NVDA \
  --model comprehensive \
  --years 5 \
  --term-growth 0.03 \
  --sensitivities \
  --peers AAPL,MSFT,AMD \
  --save-excel --save-csv --no-llm
```

---
## 15. Roadmap Ideas (Optional Enhancements)
- (Done) CLI exposure for `first_year_growth` & `margin_uplift`.
- (Done) Explicit `nwc_ratio`, `margin_curve` overrides.
- (Done) Forecast result caching & diagnostics sheet enhancements.
- Monte Carlo (guarded) wrapper producing percentile valuation bands.
- Unit tests for each strategy’s implied price under controlled fixtures.
- Inline cash flow statement reconstruction to enrich FCFF where missing.
- Automatic peer set suggestion via sector clustering.

---
## 16. License / Attribution
This generator is deterministic and designed for transparent analytical workflows. Ensure any LLM outputs are reviewed before publication.

---
## 17. Quick Reference (Cheat Sheet)
Action | Command
------ | -------
Generic DCF CSV | `python src/financial_model_generator.py --ticker NVDA --model dcf --no-llm --save-csv`
SaaS Strategy | `python src/financial_model_generator.py --ticker CRM --strategy saas_dcf --save-excel`
REIT with NAV | `python src/financial_model_generator.py --ticker O --strategy reit_dcf --cap-rate 0.065 --save-excel`
Bank Residual | `python src/financial_model_generator.py --ticker JPM --strategy bank_excess_returns --payout-ratio 0.35 --roe-target 0.14`
Energy Blend | `python src/financial_model_generator.py --ticker XOM --strategy energy_nav_dcf --energy-ebitda-multiple 5.5`
Peers + Sensitivities | `python src/financial_model_generator.py --ticker NVDA --model comprehensive --peers AAPL,MSFT --sensitivities --save-excel`

---
**Done.**
