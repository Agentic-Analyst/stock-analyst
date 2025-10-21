# Financial Model Agent (`src/agents/fm`)

A comprehensive, object-oriented infrastructure for building Excel-based DCF (Discounted Cash Flow) financial models from Yahoo Finance JSON data.

## Overview

This module implements a **7-tab Excel financial model** with complete formula infrastructure for valuation analysis. It transforms raw financial data into a professional DCF model with automatic calculations for:

- Income statement projections
- Balance sheet forecasting
- Free cash flow calculations
- Discounted cash flow valuation
- Sensitivity analysis
- Executive summary dashboard

## Architecture

### Design Principles

1. **Separation of Concerns**: Each tab has its own builder class
2. **Formula-Driven**: All calculations use Excel formulas (no hardcoded values)
3. **Data Lookup**: Single source of truth in the `Raw` tab
4. **LLM-Ready**: Placeholders for LLM-inferred parameters
5. **Extensible**: Easy to add new metrics or modify formulas

### Module Structure

```
src/agents/fm/
├── __init__.py                    # Package exports
├── constants.py                   # Configuration, field mappings, defaults
├── financial_model_builder.py    # Main orchestrator class
├── tab_raw.py                     # Tab 0: Raw data (Key, Year, Value)
├── tab_keys_map.py               # Tab 1: Lookup helper
├── tab_assumptions.py            # Tab 2: Modeling parameters
├── tab_historical.py             # Tab 3: Historical financials
├── tab_projections.py            # Tab 4: Forward projections
├── tab_dcf.py                    # Tab 5: DCF valuation
├── tab_sensitivity.py            # Tab 6: Sensitivity analysis
├── tab_summary.py                # Tab 7: Executive summary
├── demo_builder.py               # Demo script
└── README.md                     # This file
```

## Tab Structure

### Tab 0: Raw
- **Purpose**: Flat database of all financial data
- **Format**: (Key, Year, Value) tuples
- **Data Source**: Parsed from Yahoo Finance JSON
- **Access**: Used by all other tabs via SUMIFS formulas

### Tab 1: Keys_Map
- **Purpose**: Helper lookup table
- **Format**: Keys in rows, years in columns
- **Formulas**: `=SUMIFS(Raw!$C:$C,Raw!$A:$A,$A2,Raw!$B:$B,C$1)`
- **Use Case**: Quick reference for formula building

### Tab 2: Assumptions
- **Purpose**: Modeling drivers and parameters
- **Contains**:
  - WACC (Weighted Average Cost of Capital)
  - Terminal growth rate
  - Tax rate
  - Revenue growth rates (FY1-FY5)
  - Operating margin assumptions
  - Working capital days (DSO, DIO, DPO)
  - Current shares outstanding and net debt
- **LLM Integration**: Parameters marked `[LLM to infer]`

### Tab 3: Historical
- **Purpose**: Last 5 years of actual financials
- **Sections**:
  - Income Statement (rows 5-17)
  - Balance Sheet (rows 21-43)
  - Cash Flow Statement (rows 47-55)
  - Working Capital Days (rows 60-64)
- **Formulas**: SUMIFS to pull from Raw, calculated totals

### Tab 4: Projections
- **Purpose**: 5-year forward projections
- **Sections**:
  - Revenue & COGS (rows 5-7)
  - Operating Expenses (rows 8-12)
  - D&A, Capex, NWC (rows 13-19)
  - Free Cash Flow (row 21)
- **Logic**: Growth rates and margins from Assumptions

### Tab 5: DCF
- **Purpose**: Discounted cash flow valuation
- **Calculations**:
  - Present value of projected FCFs
  - Terminal value (Gordon Growth model)
  - Enterprise value
  - Equity value
  - Value per share
- **Output**: Intrinsic value estimate

### Tab 6: Sensitivity
- **Purpose**: Sensitivity analysis
- **Format**: 2-way data table
- **Variables**: WACC (rows) vs Terminal Growth (columns)
- **Output**: Value per share matrix

### Tab 7: Summary
- **Purpose**: Executive dashboard
- **Displays**:
  - Intrinsic value per share
  - Current market price
  - Implied upside/downside
  - Key valuation metrics
  - Core assumptions

## Usage

### Basic Usage

```python
from src.agents.fm import FinancialModelBuilder

# Create builder
builder = FinancialModelBuilder(ticker="NVDA")

# Load financial data
builder.load_json_file("path/to/financials_annual_modeling_latest.json")

# Build the model
builder.build_model()

# Save to Excel
builder.save("NVDA_financial_model.xlsx")
```

### Convenience Function

```python
from src.agents.fm import create_financial_model

# One-line model creation
create_financial_model(
    ticker="AAPL",
    json_path="data/AAPL/financials/financials_annual_modeling_latest.json",
    output_path="AAPL_model.xlsx"
)
```

### Infrastructure Testing (Placeholder Data)

```python
# Test infrastructure without real data
builder = FinancialModelBuilder(ticker="TEST")
builder.create_placeholder_model(years=[2020, 2021, 2022, 2023, 2024])
builder.build_model()
builder.save("test_infrastructure.xlsx")
```

### With Validation

```python
builder = FinancialModelBuilder(ticker="NVDA")
builder.load_json_file("financials.json")
builder.build_model()

# Validate model structure
validation = builder.validate_model()
if validation["valid"]:
    print("✓ Model is valid")
    builder.save("NVDA_model.xlsx")
else:
    print("✗ Validation errors:", validation["errors"])
```

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

## Configuration

### Model Parameters (in `constants.py`)

```python
class ModelParameters:
    WACC_PLACEHOLDER = 0.09                    # 9% default
    TERMINAL_GROWTH_PLACEHOLDER = 0.025        # 2.5% default
    TAX_RATE_PLACEHOLDER = 0.15                # 15% default
    
    REVENUE_GROWTH_PLACEHOLDER = [0.06, 0.05, 0.05, 0.04, 0.03]
    GROSS_MARGIN_PLACEHOLDER = [0.65] * 5
    RD_PERCENT_PLACEHOLDER = [0.15] * 5
    # ... etc
```

### Customization

To modify default assumptions:

```python
from src.agents.fm.constants import ModelParameters

# Override before building
ModelParameters.WACC_PLACEHOLDER = 0.10
ModelParameters.TERMINAL_GROWTH_PLACEHOLDER = 0.03

builder = FinancialModelBuilder(ticker="CUSTOM")
# ... build model
```

## LLM Integration (Future)

The infrastructure is designed for LLM integration:

1. **Inference Points**: All placeholders marked `[LLM to infer]`
2. **Historical Analysis**: LLM can analyze historical patterns
3. **Parameter Selection**: LLM determines appropriate assumptions
4. **Industry Context**: LLM applies industry-specific adjustments

### Future LLM Methods (Planned)

```python
# Planned API (not yet implemented)
builder.infer_assumptions_with_llm(model="gpt-4")
builder.adjust_projections_with_llm(context="AI chip demand growth")
builder.generate_narrative_with_llm()
```

## Running the Demo

```bash
# Run infrastructure demo with placeholder data
python src/agents/fm/demo_builder.py

# Output:
# - Creates DEMO_financial_model_infrastructure.xlsx
# - Tests with real data if available
# - Shows validation results
```

## Dependencies

Required packages (already in project):
- `openpyxl` - Excel file creation and manipulation
- `pathlib` - Path handling
- `json` - JSON parsing
- `datetime` - Timestamps

## Limitations & Future Work

### Current Limitations

1. **Data Table Formula**: Sensitivity tab requires manual Excel Data Table setup
2. **No VBA**: Pure Python, no macro support
3. **Static Formulas**: Formulas don't adapt to varying historical periods
4. **No Charts**: Infrastructure only, visualizations planned

### Planned Enhancements

1. ✅ **Phase 1**: Formula infrastructure (COMPLETE)
2. 🔄 **Phase 2**: LLM inference integration (IN PROGRESS)
3. ⏳ **Phase 3**: Chart generation
4. ⏳ **Phase 4**: Multi-scenario analysis
5. ⏳ **Phase 5**: Quarterly model support
6. ⏳ **Phase 6**: Industry comparables

## Testing

```bash
# Run demo (includes basic tests)
python src/agents/fm/demo_builder.py

# Test with specific ticker
python -c "
from src.agents.fm import create_financial_model
create_financial_model('NVDA', 'data/NVDA/financials/financials_annual_modeling_latest.json')
"
```

## Troubleshooting

### Common Issues

**Issue**: "No data loaded" error
- **Solution**: Call `load_json_file()` or `create_placeholder_model()` before `build_model()`

**Issue**: Missing years in JSON
- **Solution**: Module handles missing years gracefully, uses available years

**Issue**: Field name mismatches
- **Solution**: Add aliases to `constants.py` field mappings

**Issue**: Excel file size too large
- **Solution**: Limit historical years, reduce raw data rows

## Contributing

To extend the model:

1. **Add new tab**: Create `tab_newname.py` following existing pattern
2. **Add formulas**: Use helper methods in `FormulaTemplates`
3. **Update builder**: Add to `FinancialModelBuilder.build_model()`
4. **Test**: Use `demo_builder.py` to verify

## License

Part of the stock-analyst project.

## Contact

For questions or issues, refer to the main project repository.

---

**Last Updated**: 2025-01-17
**Version**: 1.0.0
**Status**: Infrastructure Complete ✅
