# Financial Model Generator - Usage Guide

## Overview

The Financial Model Generator creates banker-grade DCF valuation models in Excel format from JSON financial data.

**Input:** JSON file from `financial_scraper.py`  
**Output:** Complete Excel model with 9 tabs and formulas  
**LLM:** Automatically infers forward-looking assumptions

## Quick Start

### Simplest Way (One Line)

```python
from src.agents.fm import create_financial_model

create_financial_model("NVDA", "data/NVDA/financials/financials_annual_modeling_latest.json")
```

This creates `NVDA_financial_model.xlsx` in the current directory.

### With Custom Output Path

```python
from src.agents.fm import create_financial_model

create_financial_model(
    ticker="NVDA",
    json_path="data/NVDA/financials/financials_annual_modeling_latest.json",
    output_path="reports/NVDA_DCF_Model.xlsx"
)
```

## Advanced Usage

### Using the Builder Class

```python
from src.agents.fm import FinancialModelBuilder

# Step 1: Create builder
builder = FinancialModelBuilder(ticker="NVDA")

# Step 2: Load JSON data
builder.load_json_file("data/NVDA/financials/financials_annual_modeling_latest.json")

# Step 3: Build model (calls LLM to infer assumptions)
builder.build_model()

# Step 4: Save to file
builder.save("NVDA_model.xlsx")
```

### Accessing the Workbook Directly

```python
from src.agents.fm import FinancialModelBuilder
import openpyxl

builder = FinancialModelBuilder(ticker="NVDA")
builder.load_json_file("data.json")
builder.build_model()

# Access workbook before saving
workbook = builder.workbook
summary_sheet = workbook["Summary"]

# Read values
ticker = summary_sheet["B3"].value
dcf_value = summary_sheet["B26"].value

# Save
builder.save("output.xlsx")
```

## Output Structure

The generated Excel file contains **10 tabs**:

1. **Raw** - Flat database of (Key, Year, Value) tuples
2. **Keys_Map** - Lookup helper with SUMIFS formulas
3. **Assumptions** - Forward-looking assumptions (LLM-inferred)
4. **LLM_Inferred** - Hidden tab with LLM values
5. **Historical** - Last 5 years of actuals
6. **Projections** - FY1-FY5 forecasts
7. **Valuation (DCF)** - Perpetual Growth DCF method
8. **Valuation (Exit Multiple)** - Exit Multiple DCF method
9. **Sensitivity** - 2-way sensitivity analysis
10. **Summary** - Executive dashboard (34 metrics, 6 sections)

**Key Features:**
- ✅ All cells use Excel formulas (no hardcoded values)
- ✅ Professional formatting and layout
- ✅ Summary tab opens by default
- ✅ QA flags for data quality checks
- ✅ Banker-grade quality

## LLM Integration

The builder automatically:

1. Extracts historical metrics from JSON
2. Calls OpenAI/Claude to infer forward assumptions:
   - WACC (Weighted Average Cost of Capital)
   - Terminal Growth Rate
   - Revenue Growth Rates (FY1-FY5)
   - Operating Margins (FY1-FY5)
   - Working Capital Days (FY1-FY5)
3. Creates hidden `LLM_Inferred` tab with values
4. Assumptions tab formulas reference the hidden tab

**Example LLM Output:**
```
🤖 Calling LLM to infer assumptions...
   💰 LLM cost: $0.0002
   ✅ LLM inference successful
✅ Assumptions inferred:
   • WACC: 9.00%
   • Terminal Growth: 2.50%
   • Revenue Growth FY1-FY5: ['80.0%', '60.0%', '40.0%', '30.0%', '25.0%']
```

## Input Requirements

### JSON File Format

The JSON file should come from `financial_scraper.py` and contain:

```json
{
  "financial_statements": {
    "income_statement": {
      "2024-01-31": {
        "Total Revenue": 60922000000,
        "Cost Of Revenue": 16936000000,
        ...
      }
    },
    "balance_sheet": { ... },
    "cash_flow_statement": { ... }
  },
  "company_data": {
    "basic_info": {
      "symbol": "NVDA",
      "long_name": "NVIDIA Corporation",
      "sector": "Technology"
    }
  }
}
```

### Typical File Paths

```python
# Latest financials
"data/{ticker}/financials/financials_annual_modeling_latest.json"

# Specific date
"data/{ticker}/financials/financials_annual_modeling_20250815_192729.json"
```

## Environment Setup

### Prerequisites

```bash
# Activate conda environment
conda activate stock-analyst

# Set OpenAI API key (if not already set)
export OPENAI_API_KEY="sk-..."
```

### Python Requirements

```python
openpyxl>=3.0.0      # Excel file generation
openai>=1.0.0        # LLM inference
anthropic>=0.8.0     # Alternative LLM provider
```

## Error Handling

### Common Issues

**1. "JSON file not found"**
```python
# Solution: Check file path
from pathlib import Path
json_path = Path("data/NVDA/financials/financials_annual_modeling_latest.json")
assert json_path.exists(), f"File not found: {json_path}"
```

**2. "No data loaded"**
```python
# Solution: Call load_json_file() first
builder = FinancialModelBuilder("NVDA")
builder.load_json_file("data.json")  # Must call this
builder.build_model()
```

**3. LLM API Error**
```python
# Solution: Check API key and internet connection
import os
assert "OPENAI_API_KEY" in os.environ, "Set OPENAI_API_KEY"
```

**4. "No workbook to save"**
```python
# Solution: Call build_model() before save()
builder.load_json_file("data.json")
builder.build_model()  # Must call this
builder.save("output.xlsx")
```

## Performance

**Typical Execution Time:**
- Load JSON: ~0.1 seconds
- LLM Inference: ~2-5 seconds (depends on API latency)
- Build Excel: ~1-2 seconds
- Save File: ~0.1 seconds
- **Total: ~3-8 seconds**

**File Size:**
- Typical: 40-45 KB
- With large datasets: 50-100 KB

**API Costs:**
- LLM inference: ~$0.0002 per model (very cheap)
- Uses OpenAI GPT-4 or Claude Sonnet

## Testing

### Run Test Suite

```bash
python test_entry_point_final.py
```

This tests:
1. Builder class workflow
2. Convenience function workflow
3. LLM inference
4. Excel structure validation

### Manual Verification

```python
import openpyxl

# Open generated file
wb = openpyxl.load_workbook("NVDA_model.xlsx")

# Check tabs exist
print(wb.sheetnames)  # Should show all 10 tabs

# Check Summary values
summary = wb["Summary"]
print(f"Ticker: {summary['B3'].value}")
print(f"DCF Value: {summary['B26'].value}")

# Check formulas
print(f"Formula: {summary['B26'].value}")  # Should start with '='
```

## Examples

### Example 1: Generate Model for Multiple Tickers

```python
from src.agents.fm import create_financial_model

tickers = ["NVDA", "AAPL", "MSFT", "TSLA"]

for ticker in tickers:
    json_file = f"data/{ticker}/financials/financials_annual_modeling_latest.json"
    output_file = f"models/{ticker}_model.xlsx"
    
    print(f"Building model for {ticker}...")
    create_financial_model(ticker, json_file, output_file)
    print(f"✅ {ticker} complete\n")
```

### Example 2: Build and Email

```python
from src.agents.fm import FinancialModelBuilder
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# Build model
builder = FinancialModelBuilder("NVDA")
builder.load_json_file("data.json")
builder.build_model()
builder.save("NVDA_model.xlsx")

# Email it
msg = MIMEMultipart()
msg['From'] = "analyst@company.com"
msg['To'] = "team@company.com"
msg['Subject'] = "NVDA DCF Model"

with open("NVDA_model.xlsx", "rb") as f:
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename=NVDA_model.xlsx')
    msg.attach(part)

# Send (configure your SMTP server)
# server = smtplib.SMTP('smtp.gmail.com', 587)
# server.send_message(msg)
```

### Example 3: Compare Multiple Valuations

```python
from src.agents.fm import FinancialModelBuilder
import openpyxl

def get_dcf_value(ticker):
    builder = FinancialModelBuilder(ticker)
    builder.load_json_file(f"data/{ticker}/financials/financials_annual_modeling_latest.json")
    builder.build_model()
    
    # Extract DCF value from Summary tab
    wb = builder.workbook
    summary = wb["Summary"]
    dcf_value = summary["B26"].value
    
    return dcf_value

# Compare valuations
tickers = ["NVDA", "AMD", "INTC"]
for ticker in tickers:
    value = get_dcf_value(ticker)
    print(f"{ticker}: ${value:.2f} per share")
```

## Support

For issues or questions:
1. Check `PHASE_13_COMPLETE.md` for technical details
2. Review `test_entry_point_final.py` for working examples
3. Inspect generated Excel files to understand structure

## Version

**Current Version:** 1.0.0  
**Last Updated:** Phase 13 (October 2025)  
**Status:** Production-ready ✅
