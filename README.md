<div align="center">

<img src="assets/vynnai-logo.jpg" alt="VYNN AI logo" width="200">

# Agentic Financial Analyst

**Give it a ticker and a prompt. Get back a 10-tab DCF model, structured catalyst/risk data, and a full analyst report.**

Multi-agent equity research system built on [LangGraph](https://github.com/langchain-ai/langgraph). Autonomous pipeline from financial data collection through DCF modeling, news intelligence, and report generation -- end-to-end in ~6 minutes.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_Workflow-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED.svg)](https://hub.docker.com/r/fuzanwenn/stock-analyst)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

### Demo

[![VYNN AI Agent Demo](https://img.youtube.com/vi/aXR1ZIEdezs/maxresdefault.jpg)](https://www.youtube.com/watch?v=aXR1ZIEdezs)

▶️ *Click to watch -- agentic chatbot and broker-style dashboard*

</div>

---

## Table of Contents

- [Sample Output](#sample-output)
- [Architecture](#architecture)
- [Core Design Patterns](#core-design-patterns)
- [System Components](#system-components)
  - [Supervisor Agent](#supervisor-agent)
  - [Financial Data Agent](#financial-data-agent)
  - [Financial Model Agent (DCF Builder)](#financial-model-agent--dcf-builder)
  - [News Intelligence Agent](#news-intelligence-agent)
  - [Report Generator Agent](#report-generator-agent)
  - [Recommendation Engine](#recommendation-engine)
  - [Daily Intelligence Reports](#daily-intelligence-reports)
- [LLM Abstraction Layer](#llm-abstraction-layer)
- [Prompt Engineering](#prompt-engineering)
- [Performance & Experiments](#performance--experiments)
- [Known Limitations](#known-limitations)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Design Decisions](#design-decisions)
- [Contributing](#contributing)

---

## Sample Output

Running a comprehensive analysis produces three artifacts:

**1. 10-tab Excel DCF Model** ([download AAPL sample](samples/AAPL_financial_model.xlsx) · [download META sample](samples/META_financial_model.xlsx))

All formulas are live -- not static values. The Assumptions tab pulls from LLM-inferred projections; Projections references Assumptions; Valuation references Projections; Summary cross-references everything with QA flags. Opening the workbook and changing a single assumption (e.g., FY3 revenue growth) cascades through projections, valuation, sensitivity, and summary automatically.

<details>
<summary>Workbook structure (10 tabs)</summary>

| Tab | Contents |
|---|---|
| Raw | Imported financials -- income statement, balance sheet, cash flow (677-738 rows depending on company) |
| Keys_Map | Cell reference mapping for cross-tab formula wiring |
| Assumptions | FY0 actuals + FY1-FY5 projected assumptions sourced from LLM_Inferred |
| LLM_Inferred | Raw LLM assumptions: WACC, revenue growth rates, gross/EBITDA/operating margins, DSO/DIO/DPO |
| Historical | Derived metrics across 4 fiscal years: revenue, margins, growth rates, working capital ratios |
| Projections | 5-year forward projections -- revenue, COGS, gross profit, EBIT, NOPAT, D&A, CapEx, NWC, FCF, EBITDA |
| Valuation (DCF) | Perpetual growth method: WACC build-up (Rf, ERP, beta, Ke, Kd), FCF discounting, terminal value, equity bridge |
| Valuation (Exit Multiple) | Exit multiple method: terminal EV/EBITDA (default 20x), enterprise value, equity bridge |
| Sensitivity | Two matrices: WACC vs. terminal growth rate + WACC vs. exit multiple |
| Summary | Blended valuation dashboard with 6 QA sanity checks (E/V+D/V=1, WACC>g, DF<=1, shares>0, mid-year toggle) |

</details>

**2. Professional Analyst Report** ([download NVDA sample](samples/NVDA_Professional_Analysis_Report.pdf) · [download ORCL sample](samples/ORCL_Professional_Analysis_Report.pdf))

Multi-section PDF (typically 35-40 pages depending on company complexity and article count) covering: Executive Summary, Company Overview, Financial Performance (4-year historicals + YoY growth + profitability metrics), DCF Valuation (dual method with 5-year projections), News & Market Analysis (up to 50 articles screened, structured catalysts/risks/mitigations with confidence scores, quotes, and source URLs), Investment Thesis (bull/bear/balanced), Recommendation with multi-horizon price targets, and Appendix with full evidence references.

<details>
<summary>NVDA report excerpt -- Recommendation & Price Target</summary>

```
Investment Rating: HOLD
12-Month Price Target: $199.31
Expected Return: +3.8%

Price Targets:
  3-Month:  $194.40 (Range: $176.90 - $211.90)
  6-Month:  $196.89 (Range: $171.83 - $221.95)
  12-Month: $199.31 (Range: $163.44 - $235.19)

Calculation Methodology:
  Raw Valuation Gap: 12.3%
  Sector Premium Adjustment: 50%
  Adjusted Valuation Gap: 6.2%
  Catalyst Score: +25.0%
  Risk Score: -25.0%
  Momentum Score: +6.8%

  Expected Return = 40% x Valuation (6.2%)
                  + 40% x Net Catalysts/Risks (0.0%)
                  + 20% x Momentum (6.8%)
                  = 3.8%
```

Every number in this output is computed deterministically by `RecommendationCalculator`. The LLM writes only the surrounding narrative. `RecommendationValidator` verifies every figure matches.

</details>

<details>
<summary>ORCL report excerpt -- a SELL recommendation (the system issues non-BUY ratings)</summary>

```
Investment Rating: SELL
12-Month Price Target: $187.72
Expected Return: -15.8%

DCF Perpetual Growth: -$19.27/share (negative equity value)
DCF Exit Multiple:    $117.34/share
Average Intrinsic:    $49.04
Current Price:        $222.85
Implied Downside:     -78.0%
```

Oracle's negative perpetual-growth valuation (driven by negative FCF and $100B+ long-term debt)
combined with the exit-multiple method's more favorable $117 figure demonstrates how the dual-DCF
approach surfaces valuation disagreement rather than hiding it behind a single number.

</details>

**3. Structured Screening Data** (JSON)

<details>
<summary>Sample catalyst from NVDA screening</summary>

```json
{
  "type": "Financial",
  "description": "Nvidia reported a significant revenue increase of 69% year-over-year",
  "confidence": 0.90,
  "timeline": "Immediate",
  "impact_assessment": "Strong demand for AI products driving investor confidence",
  "evidence": [
    "Revenue increased to $44.1 billion",
    "Year-over-year growth of 69%"
  ],
  "direct_quotes": [
    {
      "text": "NVIDIA reported revenue for the first quarter ended April 27, 2025, of $44.1 billion, up 12% from the previous quarter and up 69% from a year ago.",
      "source": "NVIDIA Announces Financial Results for First Quarter Fiscal 2026",
      "url": "https://..."
    }
  ]
}
```

</details>

---

## Architecture

Supervisor-worker architecture on LangGraph's cyclical state graph. An LLM-powered supervisor classifies user intent, extracts tickers from natural language, and routes to specialized agents with enforced dependency ordering. If LLM routing fails, a deterministic rule-based fallback takes over.

```
                            User Query (Natural Language)
                "Analyze NVDA comprehensively with focus on AI chips"
                                        |
                                        v
               +------------------------------------------------+
               |              SUPERVISOR AGENT                   |
               |                                                |
               |  - Ticker extraction from NL prompt (LLM)     |
               |  - Intent classification (COMPREHENSIVE /      |
               |    MODEL_ONLY / QUICK_NEWS / CUSTOM)           |
               |  - Dynamic routing with dependency resolution  |
               |  - Deterministic fallback when LLM fails       |
               +-----+------------------------------------------+
                     |
                     v
               +-----------+       +---------------+
               | Financial |------>|    Model      |
               |   Data    |       |  Generation   |
               |   Agent   |       |    Agent      |
               +-----------+       +-------+-------+
                                           |
                                           v
                                   +---------------+
                                   |     News      |
                                   | Intelligence  |
                                   |    Agent      |
                                   +-------+-------+
                                           |
                                           v
                                   +---------------+
                                   |    Report     |
                                   |   Generator   |
                                   |    Agent      |
                                   +-------+-------+
                                           |
                                           v
                                    Output Artifacts
                        Excel DCF  -  Screening Data  -  Analyst Report
```

**Dependency chain:** `financial_data -> model_generation -> news_analysis -> report_generator`

The supervisor enforces this sequential ordering regardless of what the LLM proposes. Agents share state through a `FinancialState` blackboard dataclass -- a single mutable state object passed through every node in the graph.

### Intent-Based Routing

| Intent | Agents Triggered | Use Case |
|---|---|---|
| `COMPREHENSIVE` | All 4 (sequential) | Full equity research pipeline |
| `MODEL_ONLY` | Financial Data -> Model -> Summary | DCF modeling without news |
| `QUICK_NEWS` | News -> Summary | Recent developments only |
| `CUSTOM` | Varies | Simple questions, single-agent routing |

Objective-driven early termination means `MODEL_ONLY` workflows stop after model + summary and `QUICK_NEWS` stops after news + summary -- avoiding unnecessary LLM calls.

---

## Core Design Patterns

| Pattern | Implementation | Rationale |
|---|---|---|
| Supervisor + Worker | LangGraph cyclical graph with conditional edges | LLM proposes routing; dependency resolver enforces valid sequencing |
| Blackboard State | Shared `FinancialState` dataclass across all agents | Avoids message-passing overhead; single source of truth |
| Builder Pattern | Each Excel tab has a dedicated builder class (11 modules) | Tabs can be tested and modified independently |
| Deterministic Math + LLM Narrative | `RecommendationCalculator` -> `EvidenceExtractor` -> LLM -> `RecommendationValidator` | Numbers are computed in code; LLM writes explanations; validator ensures integrity |
| Prompt Externalization | 33 markdown templates in `prompts/` | Version-controlled, editable without code changes |
| Strategy Pattern | Pluggable DCF strategies (SaaS, REIT, Bank, Utility, Energy) | Sector-aware modeling without code changes |

---

## System Components

### Supervisor Agent

LangGraph orchestrator managing the full workflow lifecycle: session management, ticker extraction, intent classification, and conditional routing with dependency resolution.

**Location:** `src/agents/supervisor/`

| Module | Responsibility |
|---|---|
| `supervisor_agent.py` | Entry point -- `SupervisorWorkflowRunner` handles session management, ticker extraction, and workflow execution |
| `supervisor.py` | Routing logic -- `route_workflow_with_llm()` with `_resolve_dependencies()` guardrails |
| `graph.py` | LangGraph graph construction (4 agent nodes + conditional edges) |
| `state.py` | `FinancialState` blackboard, `AgentStage` / `AnalysisObjective` enums |

**Routing flow:**
```
User Prompt -> Ticker Extraction (LLM) -> Intent Classification -> Objective Detection
                                                                        |
                                              +-------------------------+------------------+
                                              v                         v                  v
                                        COMPREHENSIVE            MODEL_ONLY          QUICK_NEWS
                                        (all 4 agents)      (fin data + model     (news + summary)
                                                               + summary)
```

The supervisor ensures no agent runs before its prerequisites are complete, even if the LLM suggests otherwise.

### Financial Data Agent

Collects comprehensive financial data from Yahoo Finance via `yfinance`.

**Location:** `src/financial_scraper.py`

- Scrapes income statements, balance sheets, and cash flow statements (annual + quarterly)
- Extracts company metadata (sector, industry, employees, market cap)
- Handles data normalization -- converts pandas DataFrames to clean JSON with proper type handling (NaN, numpy types, dates)
- Outputs structured JSON ready for the model generator

### Financial Model Agent -- DCF Builder

Generates a 10-tab Excel DCF workbook from scraped financial data with LLM-inferred assumptions.

**Location:** `src/agents/fm/`

The workbook is fully formula-driven. Every projected value traces back to an assumption cell, and every assumption traces back to either historical data or the `LLM_Inferred` tab. The Projections tab computes 20+ line items per year: revenue, COGS, gross profit, R&D, SG&A, EBIT, tax, NOPAT, D&A, CapEx, AR, inventory, AP, NWC, delta-NWC, FCF, and EBITDA with margin diagnostics.

**Formula Evaluator** (`formula_evaluator.py`): Interprets all Excel formulas programmatically -- resolves cell references, cross-tab references (`='Valuation (DCF)'!$B$12`), arithmetic, and common functions (`SUMIFS`, `IFERROR`, `INDEX/MATCH`). This ensures the Excel workbook and the JSON output consumed by downstream agents stay consistent without requiring an Excel installation.

**Sector strategies:** Generic DCF, SaaS (Rule of 40), REIT (FFO/AFFO), Bank (Excess Returns), Utility, Energy NAV. Selected automatically via LLM industry classification.

### News Intelligence Agent

Multi-stage pipeline for autonomous news collection, relevance filtering, and structured analysis.

**Location:** `src/article_scraper.py`, `src/article_filter.py`, `src/article_screener.py`

| Stage | Module | Description |
|---|---|---|
| Scraping | `article_scraper.py` | LLM-generated search queries across financial, management, industry, and competitive categories -> Google News via SerpAPI -> `newspaper3k` extraction |
| Filtering | `article_filter.py` | LLM batch relevance scoring (0-10) against investment thesis -> MongoDB persistence |
| Screening | `article_screener.py` | Deep analysis -> structured catalysts, risks, mitigations with confidence scores, direct quotes, and source URLs |

**Output data model** (dataclasses):
- `Catalyst` -- type, description, confidence (0-1), evidence, timeline, impact assessment, direct quotes with source URLs
- `Risk` -- type, description, severity, confidence, likelihood, impact, mitigation potential
- `Mitigation` -- strategy, effectiveness, timeline, evidence

If recent articles exist in MongoDB, scraping and filtering are skipped on subsequent runs.

### Report Generator Agent

Aggregates all pipeline outputs into a structured analyst report.

**Location:** `src/report_agent.py`

**Data sources aggregated:**
1. Financial data JSON (company info, historical metrics)
2. Computed DCF model JSON (fair value, WACC, projections)
3. Screening data JSON (catalysts, risks, mitigations with evidence)

**Report sections:** Executive Summary -> Investment Thesis -> Company Overview -> Financial Performance -> Valuation Analysis (dual DCF) -> News & Catalyst Analysis -> Risk Assessment -> Recommendation (multi-horizon price targets: 3-month, 6-month, 12-month with confidence ranges) -> Appendix (evidence references with source URLs).

### Recommendation Engine

3-layer architecture ensuring LLM-generated recommendations are grounded in verifiable math. This is the core integrity mechanism -- the LLM never invents a number.

**Location:** `src/recommendation_engine.py`, `src/recommendation_calculator.py`, `src/recommendation_validator.py`, `src/evidence_extractor.py`

```
+----------------------------------------------------------+
|  Layer 1: RecommendationCalculator (deterministic)       |
|  Pure Python -- expected return, price targets, bands    |
|  Sector-aware premiums, volatility caps, time decay      |
|  Output: FixedNumbers (immutable)                        |
+----------------------------------------------------------+
|  Layer 2: EvidenceExtractor -> LLM Narrative             |
|  Builds evidence pack (E1, E2, ...) with source scoring  |
|  (primary > tier-1 > syndication)                        |
|  LLM writes narrative constrained to provided data       |
+----------------------------------------------------------+
|  Layer 3: RecommendationValidator                        |
|  Regex verification against FixedNumbers                 |
|  >=95% citation coverage required                        |
|  Auto-correction of LLM number deviations                |
+----------------------------------------------------------+
```

**Rating bands:** STRONG BUY (>20%) - BUY (10-20%) - HOLD (-5% to +10%) - SELL (-20% to -5%) - STRONG SELL (<-20%)

### Daily Intelligence Reports

Standalone modules for recurring daily intelligence, running independently of the supervisor.

**Location:** `src/agents/news/daily/`

| Report | Description |
|---|---|
| Company Daily | Per-company 24h intelligence: headlines, impact analysis, financial materiality, peer context, risks & watch items |
| Sector Daily | Cross-company aggregation: rotation trends, thematic signals, company movers, sector catalysts |

Both follow a 3-step LLM workflow: batch catalyst/risk extraction -> peer identification (3-5 peers) -> report generation.

---

## LLM Abstraction Layer

Provider-agnostic interface with runtime model switching.

**Location:** `src/llms/`

```python
from llms.config import init_llm, get_llm

init_llm("claude-3.5-sonnet")
response, cost = get_llm()(messages)
```

**Supported models:**

| Model | Provider | Notes |
|---|---|---|
| `gpt-4o-mini` | OpenAI | Fastest, lowest cost |
| `claude-3.5-sonnet` | Anthropic | Recommended default |
| `claude-3.5-haiku` | Anthropic | Fast, low cost |
| `claude-3-opus` | Anthropic | Highest quality |

Features: exponential backoff retry (3 attempts), automatic message format conversion (OpenAI <-> Anthropic), per-call cost tracking with model-specific pricing tables.

---

## Prompt Engineering

33 externalized prompt templates in `prompts/` as versioned markdown files.

| Category | Count | Examples |
|---|---|---|
| Supervisor Routing | 3 | `ticker_extraction_and_routing.md`, `workflow_routing.md` |
| News Analysis | 5 | `daily_catalyst_analysis.md`, `article_relevance_scoring.md` |
| Financial Modeling | 2 | `assumptions_inference.md`, `industry_classification.md` |
| Report Generation | 10 | `professional_analyst_report.md`, `report_valuation.md` |
| Recommendations | 3 | `investment_recommendation.md`, `recommendation_explainer.md` |
| Sector Analysis | 5 | `sector_catalyst_analysis.md`, `sector_report_generation.md` |
| Other | 5 | `peer_identification.md`, `batch_analysis.md` |

Anti-hallucination constraints are embedded directly in prompts: no data fabrication, mandatory source citation, structured JSON output schemas, strict number formatting rules.

---

## Performance & Experiments

Benchmarked across repeated runs. Full methodology, scripts, and raw data in [`experiments/`](experiments/).

LLM-bound operations (news + report) account for ~93% of the ~6.4 min total execution time. Data collection and DCF model generation complete in under 10 seconds combined. Supervisor routing overhead is ~4%.

**Reproducibility** (9 runs across 3 tickers):

| Ticker | Success Rate | Mean Duration | CV (sigma/mu) | Reproducibility Score |
|---|---|---|---|---|
| NVDA | 100% | 384.5s | 0.016 | 0.985 |
| AAPL | 100% | 215.8s | 0.033 | 0.969 |
| MSFT | 100% | 195.6s | 0.035 | 0.965 |

Paraphrased prompts ("Analyze NVDA stock...", "Give me a comprehensive analysis of NVIDIA...", "What's your investment recommendation for NVDA?") all extracted the correct ticker, triggered identical 4-agent workflows, and completed within a 13-second window. Overall stability score: 0.983.

**Case studies** (end-to-end on real tickers):

| Company | Articles | Catalysts | Risks | DCF Fair Value | Market Price | Upside | Rating |
|---|---|---|---|---|---|---|---|
| NVDA | 50 screened | 13 | 10 | $215.62 | $191.98 | +12.3% | HOLD |
| ORCL | 50 screened | 9 | 8 | $49.04 | $222.85 | -78.0% | SELL |
| META | 18 analyzed | 7 | 6 | $604.06 | $621.71 | -2.8% | HOLD |

AAPL was tested separately with a simple query ("What happened to Apple stock?") and demonstrated the supervisor routing to a single news agent instead of the full 4-agent pipeline -- optimizing both cost and latency.

**Estimated API cost per comprehensive analysis:** ~$0.50-1.50 depending on model choice and article count (primarily LLM calls in news screening and report generation). SerpAPI costs ~$0.01 per search query.

---

## Known Limitations

- **Yahoo Finance rate limiting.** `yfinance` can hit rate limits under heavy concurrent use. The system retries with backoff but does not currently implement request queuing across concurrent analyses.
- **News freshness.** SerpAPI returns Google News results which can lag breaking news by 15-30 minutes. The system is not suitable for intraday trading signals.
- **LLM assumption quality.** DCF assumptions (WACC, growth rates, margins) are LLM-inferred. While calibrated against historical data and sector benchmarks, they can produce unreasonable values for edge-case companies (e.g., pre-revenue biotechs, SPACs, recently-IPO'd companies with limited financial history). The Summary tab includes QA flags to catch some of these.
- **Negative equity edge case.** Companies with high debt and low FCF (e.g., Oracle) can produce negative intrinsic values under the perpetual growth method. The system surfaces this rather than hiding it, but the averaged intrinsic value can be misleading when the two methods diverge sharply.
- **Sequential execution.** The dependency chain enforces sequential agent execution. News analysis does not depend on model output and could theoretically run in parallel with model generation, but the current graph enforces full sequencing.
- **Single-ticker scope.** Each analysis run handles one ticker. Cross-company comparative analysis requires multiple runs and manual synthesis.

---

## Getting Started

### Prerequisites

- Python 3.11+
- API keys: OpenAI or Anthropic (LLM), SerpAPI (news scraping)
- MongoDB (optional, for article caching)

### Installation

```bash
conda create -n stock-analyst python=3.11 -y
conda activate stock-analyst
pip install -r requirements.txt

cp .env.example .env
# Set: OPENAI_API_KEY, ANTHROPIC_API_KEY, SERPAPI_API_KEY
# Optional: MONGO_URI, MONGO_DB
```

Update the data layer:

```bash
pip install --upgrade --force-reinstall git+https://github.com/Agentic-Analyst/vynn-core.git
```

Verify:

```bash
python main.py --list-llms
```

---

## Usage

The `--email` and `--timestamp` flags are used for output directory namespacing (`data/{email}/{ticker}/{timestamp}/`). They are required in all modes.

### Chat Mode (Recommended)

Natural language interface with autonomous workflow selection:

```bash
# Comprehensive analysis
python main.py --email user@example.com --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "Analyze NVDA comprehensively with focus on AI chip market"

# Quick news check
python main.py --email user@example.com --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "What happened to Tesla stock recently?"

# DCF model only
python main.py --email user@example.com --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "Build a DCF model for Apple"

# Multi-turn (provide session-id)
python main.py --email user@example.com --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "Now compare it with AMD" \
  --session-id "abc123"
```

### Pipeline Mode

Deterministic execution with explicit control:

```bash
# Full pipeline
python main.py --ticker NVDA --email user@example.com --timestamp 20250216_120000

# Financial model only
python main.py --ticker AAPL --email user@example.com --timestamp 20250216_120000 \
  --pipeline financial-model

# News scraping + filtering
python main.py --ticker MSFT --email user@example.com --timestamp 20250216_120000 \
  --pipeline search-news

# Screen existing articles
python main.py --ticker MSFT --email user@example.com --timestamp 20250216_120000 \
  --pipeline screen-news

# Daily reports
python main.py --ticker NVDA --email user@example.com --timestamp 20250216_120000 \
  --pipeline company-daily-report

python main.py --ticker TECHNOLOGY --email user@example.com --timestamp 20250216_120000 \
  --pipeline sector-daily-report
```

### Model Selection

```bash
python main.py --ticker NVDA --email user@example.com --timestamp 20250216_120000 \
  --llm claude-3.5-sonnet
```

### Output Structure

```
data/{email}/{ticker}/{timestamp}/
├── financials/
│   └── financials_annual_modeling_latest.json       # Raw financial data
├── models/
│   ├── {TICKER}_financial_model.xlsx                # 10-tab Excel DCF workbook
│   └── {TICKER}_financial_model_computed_values.json # Formula-evaluated values
├── searched/                                         # Raw scraped articles
├── filtered/                                         # Relevance-scored articles
├── screened/
│   └── screening_data.json                           # Structured catalysts, risks, mitigations
├── reports/
│   └── professional_report.md                        # Final analyst report
└── logs/
    └── {TICKER}_analysis.log                         # Execution log with timing
```

---

## Deployment

### Docker

```bash
docker pull fuzanwenn/stock-analyst:latest

docker run --rm \
  -v $(pwd)/data:/app/data \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e SERPAPI_API_KEY=$SERPAPI_API_KEY \
  fuzanwenn/stock-analyst:latest \
  --ticker NVDA --email user@example.com --timestamp 20250216_120000
```

Docker Compose:

```bash
docker compose up
```

Multi-arch build:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t fuzanwenn/stock-analyst:latest --push .
```

---

## Project Structure

```
stock-analyst/
├── main.py                              # CLI entry point & pipeline orchestrator
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
│
├── src/
│   ├── config.py                        # Configuration defaults
│   ├── logger.py                        # Dual-sink logging (file + console)
│   ├── path_utils.py                    # Path utilities (Docker / local)
│   │
│   ├── financial_scraper.py             # Yahoo Finance data collection
│   ├── article_scraper.py               # Google News scraping (SerpAPI)
│   ├── article_filter.py                # LLM relevance scoring + MongoDB
│   ├── article_screener.py              # Structured insight extraction
│   ├── evidence_extractor.py            # Evidence pack builder
│   │
│   ├── recommendation_engine.py         # 3-layer recommendation pipeline
│   ├── recommendation_calculator.py     # Deterministic financial math
│   ├── recommendation_validator.py      # LLM output validation & auto-correction
│   │
│   ├── report_agent.py                  # Report synthesis
│   ├── financial_summary_agent.py       # Financial model summary
│   ├── news_summary_agent.py            # News analysis summary
│   ├── session_manager.py              # Multi-turn conversation persistence
│   │
│   ├── llms/                            # LLM provider abstraction
│   │   ├── config.py                    # Model registry, runtime switching
│   │   ├── openai.py                    # GPT wrapper + retry + cost tracking
│   │   └── claude.py                    # Claude wrapper + retry + cost tracking
│   │
│   └── agents/
│       ├── fm/                          # Financial Model Agent
│       │   ├── financial_model_builder.py
│       │   ├── formula_evaluator.py     # Excel formula interpreter
│       │   └── tabs/                    # 11 tab builder modules
│       │       ├── tab_raw.py
│       │       ├── tab_historical.py
│       │       ├── tab_assumptions.py
│       │       ├── tab_projections.py
│       │       ├── tab_valuation_perpetual_growth_dcf.py
│       │       ├── tab_valuation_exit_multiple_dcf.py
│       │       ├── tab_sensitivity.py
│       │       ├── tab_summary.py
│       │       ├── tab_llm_inferred_adjusted.py
│       │       ├── tab_keys_map.py
│       │       └── tab_lever_map.py
│       │
│       ├── news/daily/                  # Daily Intelligence Reports
│       │   ├── company_daily_report.py
│       │   └── sector_daily_report.py
│       │
│       └── supervisor/                  # LangGraph Supervisor
│           ├── supervisor_agent.py      # Entry point & session management
│           ├── supervisor.py            # LLM routing + dependency resolution
│           ├── graph.py                 # LangGraph cyclical graph
│           ├── state.py                 # FinancialState blackboard
│           └── task_agents/
│               ├── financial_data_agent.py
│               ├── model_generation_agent.py
│               ├── news_analysis_agent.py
│               ├── financial_summary_agent.py
│               ├── news_summary_agent.py
│               └── report_generator_agent.py
│
├── prompts/                             # 33 externalized LLM prompt templates
├── samples/                             # Sample output artifacts (Excel, PDF, JSON)
├── experiments/                         # Benchmarks & reproducibility studies
└── data/                                # Output artifacts (per user/ticker/timestamp)
```

---

## Design Decisions

**LangGraph over LangChain Agents.** LangGraph's cyclical state graph gives explicit conditional routing based on full state context rather than just the last message. Combined with `_resolve_dependencies()`, LLM routing failures degrade gracefully to deterministic sequencing. Objective-driven early termination (`MODEL_ONLY` stops after model + summary) avoids unnecessary compute.

**Deterministic numbers, LLM narrative.** The LLM never computes financial figures. `RecommendationCalculator` handles all math deterministically. The LLM writes the explanation. `RecommendationValidator` verifies every number in the output against source values, auto-corrects deviations, and enforces >=95% citation coverage. This achieves the reliability of deterministic systems with the communication quality of LLMs.

**Custom formula evaluator.** The system produces Excel files (for human analysts) and needs computed values programmatically (for downstream LLM agents). The `FormulaEvaluator` interprets the same formulas in-code -- cell references, cross-tab references, arithmetic, Excel functions -- keeping both outputs consistent without an Excel dependency.

**Dual DCF valuation.** Perpetual growth and exit multiple methods can produce wildly different values (see Oracle: -$19 vs. $117 per share). Rather than picking one, the system surfaces both with the disagreement visible. The Summary tab's QA flags and the report's valuation section explicitly call out when the methods diverge, forcing the reader to engage with the assumptions rather than accepting a single point estimate.

**Externalized prompts.** All 33 prompts are markdown files in `prompts/`. Changes are tracked in git, can be A/B tested without deployments, and can be edited by domain experts who don't touch Python.

**MongoDB via vynn-core.** The shared data layer ([`vynn-core`](https://github.com/Agentic-Analyst/vynn-core)) provides article caching in MongoDB. Subsequent runs skip re-scraping and re-filtering. If MongoDB is unavailable, the pipeline falls back to local file storage.

---

## Contributing

Contributions are welcome. If you're looking to get started:

- **Bug reports and feature requests** -- open an issue with reproduction steps or a clear description of the desired behavior.
- **Prompt improvements** -- the 33 templates in `prompts/` are the easiest high-impact contribution. If you find a prompt that produces poor output for a specific sector or company type, submit a PR with the improved version and a before/after example.
- **New sector strategies** -- the DCF builder uses a Strategy pattern. Adding a new sector (e.g., Insurance, Pharma) means implementing a new strategy class without touching existing code.

Please open an issue before starting significant work so we can discuss approach.

---

## License

See [LICENSE](LICENSE) for details.
