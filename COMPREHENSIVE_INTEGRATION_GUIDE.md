# Comprehensive Stock Analysis Pipeline Integration

## 🎯 Overview

The `main.py` file has been completely redesigned to serve as the single entry point for a comprehensive 6-step stock analysis workflow, integrating all enhanced components with their tight interconnections.

## 📊 6-Step Pipeline Architecture

### Step 1: Financial Scraping
- **Component**: `FinancialScraper`
- **Purpose**: Collect financial statements and company data from yfinance
- **Output**: Comprehensive financial dataset (income statement, balance sheet, cash flow, company info)
- **Connection**: Provides foundation data for Step 2 (Financial Model Generation)

### Step 2: Financial Model Generation  
- **Component**: `FinancialModelGenerator`
- **Purpose**: Build DCF and comparable models with LLM-enhanced insights
- **Enhanced Features**:
  - Configuration-driven defaults via `model_config.py`
  - Sector-specific forecast strategies via `forecast_strategies.py` 
  - Override application audit logging with JSON serialization
  - LLM narrative generation (always enabled)
  - Automatic Excel export (production default)
- **Output**: Comprehensive financial model with implied price, sensitivities, LLM analysis
- **Connection**: Base implied price feeds into Step 6 (Price Adjustment)

### Step 3: News Scraping
- **Component**: `ArticleScraper`  
- **Purpose**: Collect recent news articles from Google News
- **Output**: Raw news articles with metadata
- **Connection**: Provides raw content for Step 4 (Article Filtering)

### Step 4: Article Filtering
- **Component**: `ArticleFilter`
- **Purpose**: Filter articles for relevance and quality using scoring algorithms
- **Enhanced Features**: 
  - Always generate reports (production default)
  - Always save filtered articles (production default)
- **Output**: High-quality filtered articles with relevance scores
- **Connection**: Filtered articles feed into Step 5 (Article Screening)

### Step 5: Article Screening
- **Component**: `ArticleScreener`
- **Purpose**: Extract investment insights using LLM analysis
- **Enhanced Features**:
  - Always generate screening reports (production default)
  - Always save structured data (production default)
- **Output**: Catalysts, risks, and mitigation strategies with confidence scores
- **Connection**: Qualitative insights feed into Step 6 (Price Adjustment)

### Step 6: Price Adjustment
- **Component**: `price_adjustor.py` functions + `event_param_mapping.py`
- **Purpose**: Combine quantitative model with qualitative factors for final price synthesis
- **Enhanced Features**:
  - **Deterministic Event→Parameter Mapping**: Uses `event_param_mapping.py` for transparent catalyst/risk→parameter delta conversion
  - **Unit Conversion Audit**: Tracks pp/bps→decimal conversions with full audit trail  
  - **Scenario Synthesis**: LLM-enhanced scenario analysis with guardrails
  - **Configuration-Driven**: Uses `price_adjustor_config.py` for defaults and prompts
- **Output**: Comprehensive price analysis with base/adjusted/bull/bear prices and audit trail
- **Connection**: Final synthesis combining Steps 2 and 5

## 🔄 Component Interconnections

### Data Flow
```
Financial Scraping → Financial Model → Base Implied Price
                                           ↓
News Scraping → Filtering → Screening → Qualitative Factors
                                           ↓
                              Price Adjustment (Synthesis)
                                           ↓
                          Final Price Analysis with Audit Trail
```

### Configuration Integration
- **`model_config.py`**: Provides financial modeling constants and sector-specific parameters
- **`price_adjustor_config.py`**: Defines adjustment scaling factors, caps, and LLM prompts
- **`forecast_strategies.py`**: Implements sector-specific DCF strategies with override consumption audit

### Enhanced Audit & Logging
- **Unit Conversion Logging**: `event_param_mapping.py` tracks pp/bps→decimal conversions
- **Override Application Audit**: `forecast_strategies.py` logs applied parameter overrides with JSON serialization
- **Comprehensive Transparency**: Full audit trail from event classification through final price adjustment

## 🚀 Pipeline Execution Modes

### 1. Comprehensive (Default)
```bash
python main.py --ticker NVDA --company "NVIDIA" --pipeline comprehensive
```
Executes all 6 steps with full integration and cross-component data flow.

### 2. Financial Only
```bash
python main.py --ticker AAPL --company "Apple Inc" --pipeline financial-only --model dcf --years 5
```
Steps 1-2: Financial scraping and model generation only.

### 3. Model to Price  
```bash
python main.py --ticker TSLA --company "Tesla" --pipeline model-to-price --wacc 0.095
```
Steps 2 + 6: Generate financial model and apply price adjustment (uses existing news analysis if available).

### 4. News to Price
```bash
python main.py --ticker NVDA --company "NVIDIA" --pipeline news-to-price --min-score 4.0
```
Steps 3-6: News analysis through price adjustment (uses existing financial model if available).

### 5. News Only
```bash 
python main.py --ticker AAPL --company "Apple Inc" --pipeline news-only --max-articles 30
```
Steps 3-5: News scraping, filtering, and screening only.

### 6. Model Only
```bash
python main.py --ticker TSLA --company "Tesla" --pipeline model-only --model comprehensive
```
Step 2: Financial model generation only (requires existing financial data).

## ⚙️ Key Integration Features

### 1. **Tight Component Coupling**
- Financial model results directly feed price adjustment base price
- Screening results provide qualitative factors for event→parameter mapping
- Configuration shared across components for consistency

### 2. **Enhanced Audit Trail**  
- Unit conversion logging: pp/bps→decimal with formulas and dimensions
- Override application tracking: JSON audit of applied parameter overrides
- Event mapping transparency: Full catalyst/risk→parameter delta audit

### 3. **Production-Ready Defaults**
- Reports always generated (no optional flags)
- Data always saved (Excel/CSV/JSON outputs automatic)
- Sensible defaults for all parameters

### 4. **Configuration Externalization**
- Model parameters: `model_config.py` with sector-specific constants
- Adjustment parameters: `price_adjustor_config.py` with scaling factors and caps
- Forecast strategies: `forecast_strategies.py` with deterministic sector selection

### 5. **Comprehensive Logging**
- Centralized logging via `setup_logger()` 
- Stage-specific progress tracking
- Performance metrics and statistics
- Error handling with graceful degradation

## 📈 Enhanced Capabilities vs. Original

### Original (3-step):
News Scraping → Filtering → Screening

### Enhanced (6-step):
Financial Scraping → Model Generation → News Scraping → Filtering → Screening → Price Adjustment

### Key Enhancements:
1. **Quantitative Foundation**: Real financial model with DCF valuation
2. **Qualitative Integration**: Systematic event→parameter mapping with audit trails
3. **Configuration Management**: Externalized constants and sector-specific strategies  
4. **Audit Transparency**: Comprehensive logging of conversions and overrides
5. **Production Readiness**: Sensible defaults and automatic saving/reporting
6. **Scenario Analysis**: LLM-enhanced scenario synthesis with guardrails

## 🎛️ Command Line Interface

### Core Arguments
- `--ticker` (required): Stock symbol
- `--company` (required): Company name
- `--pipeline`: Execution mode selection

### Financial Modeling
- `--model`: DCF/comparable/comprehensive
- `--years`: Projection period
- `--wacc`: Override WACC
- `--term-growth`: Override terminal growth
- `--strategy`: Force specific forecast strategy

### News Analysis  
- `--max-articles`: Scraping limit
- `--min-score`: Filtering threshold
- `--min-confidence`: Screening confidence threshold

### Price Adjustment
- `--scaling`: Qualitative adjustment scaling factor
- `--adjustment-cap`: Maximum adjustment percentage
- `--no-mapped-deltas`: Disable event→parameter mapping

The comprehensive integration provides a production-ready, auditable, and highly configurable stock analysis pipeline that systematically combines quantitative financial modeling with qualitative news analysis to produce well-supported investment recommendations.
