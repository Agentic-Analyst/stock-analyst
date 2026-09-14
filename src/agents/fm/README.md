# Financial Model Engine (`src/agents/fm`)

This package builds auditable Excel valuation artifacts from the normalized
financial-data JSON saved by `FinancialScraper`.

## Current contract

- Numerical assumptions are deterministic and source-grounded. An LLM may
  explain a model, but it cannot choose WACC, growth, margins, multiples, or
  the published fair value.
- An operating-company workbook has 10 visible sheets: `Raw`, `Keys_Map`,
  `Assumptions`, `Model_Inputs`, `Historical`, `Projections`, both DCF methods,
  `Sensitivity`, and `Summary`.
- A balance-sheet financial uses a separate justified-P/B/normalized-ROE
  workbook. It never builds or hides an inapplicable industrial DCF.
- Funds, crypto, REITs, insurers, commodity-cycle issuers without normalized
  inputs, and other unsupported instruments fail closed into their specialized
  service contract.
- Every build evaluates formulas, stores formula-integrity and publication
  metadata in the computed-values sidecar, and relabels a withheld workbook
  midpoint as an audit scenario rather than a fair value.
- Analyst targets and peer multiples are independent benchmarks. They can
  corroborate or block a directional publication, but are never silently
  averaged into intrinsic value unless a peer-comps leg passes the explicit
  comparability policy.

## Main components

- `financial_model_builder.py`: method routing, workbook construction, formula
  evaluation, and publication metadata.
- `assumption_grounding.py`: CAPM, terminal growth, margins, growth paths, and
  exit-multiple grounding.
- `bank_valuation.py`: justified-P/B/ROE and ROE-adjusted bank peer method.
- `formula_evaluator.py`: deterministic evaluation plus integrity checks.
- `tabs/`: one builder per visible workbook surface.

## Usage

Use the convenience function in production paths; it evaluates the workbook
before saving and refuses an artifact whose formulas do not pass integrity.

```python
from pathlib import Path
from src.agents.fm import create_financial_model


class Logger:
    def info(self, message):
        print(message)


create_financial_model(
    ticker="AAPL",
    json_path=Path("data/AAPL/financials/financials_annual_modeling_latest.json"),
    logger=Logger(),
    output_path=Path("AAPL_financial_model.xlsx"),
)
```

The adjacent `AAPL_financial_model_computed_values.json` is part of the
artifact contract. Do not publish an XLSX without its successful sidecar.

## Data Format

### Input: Yahoo Finance JSON

Expected JSON structure (from `financial_scraper.py`):

```json
{
  "ticker": "NVDA",
  "scraped_at": "2025-08-15T19:04:27",
  "data_type": "annual",
  "financial_statements": {
    "income_statement": {
      "2024-01-31": {
        "Total Revenue": 60922000000.0,
        "Cost Of Revenue": 16621000000.0,
        "Gross Profit": 44301000000.0,
        ...
      },
      "2023-01-31": { ... }
    },
    "balance_sheet": { ... },
    "cash_flow": { ... }
  }
}
```

### Standard Field Mappings

The module handles multiple naming conventions automatically:

| Standard Name | Aliases |
|--------------|---------|
| Total Revenue | TotalRevenue, totalRevenue, Revenue |
| Cost Of Revenue | CostOfRevenue, Cost of Sales |
| Research And Development | R&D, ResearchAndDevelopment |
| Operating Cash Flow | OperatingCashFlow, Cash Flow From Operating Activities |

See `constants.py` for complete mappings.

## Formulas Reference

### Key Formula Patterns

**1. Data Lookup (from Raw tab)**
```excel
=SUMIFS(Raw!$C:$C, Raw!$A:$A, "Total Revenue", Raw!$B:$B, B$1)
```

**2. Dynamic Index (for projections)**
```excel
=B5*INDEX(Assumptions!$C$13:$G$13, 1, COLUMNS($B:B))
```

**3. Free Cash Flow**
```excel
=NOPAT + D&A + Capex - ΔNWC
```

**4. Discount Factor**
```excel
=1/(1+$B$3)^year
```

**5. Terminal Value**
```excel
=Terminal_FCF/(WACC - g)
```

**6. Net Debt**
```excel
=Total_Debt - Cash_And_Cash_Equivalents
```

## Configuration and assumptions

Do not mutate module-level “default” assumptions to tune an answer. The engine
derives each input from the saved source artifact and records the derivation in
`Model_Inputs`. Important policy settings are environment variables with hard
bounds, including statement freshness, peer comparability, and analyst-evidence
age. They are copied into the analysis manifest for reproducibility.

If a result looks wrong, inspect the observable inputs, normalized TTM bridge,
formula-integrity manifest, valuation-method selection, reverse DCF, and Street
reconciliation. Changing a growth rate until the model resembles the market is
not a valid fix.

## Dependencies

Required packages (already in project):
- `openpyxl` - Excel file creation and manipulation
- `pathlib` - Path handling
- `json` - JSON parsing
- `datetime` - Timestamps

## Known method boundaries

- A corporate FCFF DCF is not the primary method for funds, crypto, banks,
  REITs, insurers, or commodity-cycle businesses without normalized cycle
  inputs. Those routes must use or await their specialized engine.
- Two DCF terminal methods share one operating forecast and are one valuation
  lens. A directional DCF-only conclusion needs qualified numeric independent
  corroboration.
- Provider price targets without a provider as-of date may challenge a model
  but cannot validate a directional point target.
- Missing, misaligned, or stale statements withhold publication. A recent
  scrape timestamp never makes an old financial period current.

## Testing

```bash
PYTHONPATH=.:src conda run -n stock-analyst python -m pytest -q

# Read-only audit of an existing complete run directory
PYTHONPATH=.:src conda run -n stock-analyst \
  python -m src.valuation_artifact_audit data/<email>/<ticker>/<timestamp>
```

## Troubleshooting

### Common Issues

**Issue**: "No data loaded" error
- **Solution**: load the normalized financial JSON before `build_model()`.

**Issue**: point estimate is withheld
- **Solution**: read `withheld_reason`; do not bypass it. Typical causes are a
  stale period, an unsuitable method, a failed valuation leg, method
  dispersion, or unreconciled independent evidence.

**Issue**: field name mismatch
- **Solution**: add and test an alias at the normalization boundary; never
  inject a made-up zero or generic assumption downstream.

**Issue**: Excel file size too large
- **Solution**: Limit historical years, reduce raw data rows

## Contributing

To extend the model:

1. **Add new tab**: Create `tab_newname.py` following existing pattern
2. **Add formulas**: Use helper methods in `FormulaTemplates`
3. **Update builder**: Add to `FinancialModelBuilder.build_model()`
4. **Test**: add formula, publication-boundary, and representative-artifact
   regressions.

## License

Part of the stock-analyst project.

## Contact

For questions or issues, refer to the main project repository.
