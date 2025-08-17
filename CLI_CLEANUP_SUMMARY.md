# CLI Argument Cleanup Summary

## 🧹 Completed Cleanup for Main.py Integration

This document summarizes the CLI arguments that were cleaned up across the codebase in preparation for main.py integration following the core 6-step program flow:

**Program Flow**: Financial Scraping → Model Generation → News Scraping → Filtering → Screening → Price Adjustment

## ✅ Arguments Removed/Made Default

### 1. **LLM Control Flags (Removed)**
- `financial_model_generator.py`: `--no-llm` ❌ (LLM always enabled)
- `price_adjustor.py`: `--no-llm` ❌ (LLM always enabled)

**Rationale**: User expects LLM to be available in production, eliminating need for disable flags.

### 2. **Save/Output Flags (Made Default Behavior)**
- `financial_scraper.py`: `--save` ❌ → Always save JSON files
- `financial_model_generator.py`: `--save-excel` ❌ → Always save Excel output
- `article_filter.py`: `--save-filtered` ❌ → Always save filtered articles
- `article_filter.py`: `--output-report` ❌ → Always generate reports
- `article_screener.py`: `--output-report` ❌ → Always generate reports

**Rationale**: Data persistence and report generation should be default behavior in production.

### 3. **Debug Flags (Removed)**
- `price_adjustor.py`: `--json` ❌ → Always provide human-readable output

**Rationale**: JSON-only output is primarily for debugging; production use needs readable output.

## 📋 Arguments Retained

### Core Functionality
- All ticker/company identification arguments
- Model type selections (`--model`, `--strategy`)
- Parameter overrides (WACC, growth rates, etc.)
- Confidence/scoring thresholds

### Advanced Features
- `financial_model_generator.py`: `--save-csv` ✅ (Optional additional output)
- LLM enhancement flags (temperature, scenarios, etc.) ✅
- Sensitivity analysis flags ✅

### Stats/Debugging (Kept but non-essential)
- `--stats` flags across modules ✅ (Useful for debugging)

## 🔄 Behavioral Changes

### Before Cleanup
```bash
# Required explicit save flags
python financial_model_generator.py --ticker NVDA --save-excel --no-llm
python article_filter.py --ticker NVDA --save-filtered --output-report
```

### After Cleanup  
```bash
# Saves and LLM enabled by default
python financial_model_generator.py --ticker NVDA
python article_filter.py --ticker NVDA
```

## 🎯 Main.py Integration Ready

The cleaned CLI interfaces are now optimized for:
1. **Streamlined Arguments**: Fewer required flags for basic operation
2. **Production Defaults**: LLM and saving enabled by default
3. **Pipeline Integration**: Consistent argument patterns across modules
4. **User Experience**: Sensible defaults reduce cognitive load

## 📊 Impact Summary

- **Removed**: 8 unnecessary CLI flags
- **Made Default**: 5 save/output behaviors  
- **Files Modified**: 5 core modules
- **Compilation**: ✅ All files compile cleanly
- **Backward Compatibility**: ⚠️ Some flags removed (documented above)

The codebase is now prepared for main.py integration with the expected 6-step program flow, focusing on essential parameters while making common operations (saving, LLM usage, report generation) the default behavior.
