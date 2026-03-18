<div align="center">

<img src="assets/vynnai-logo.jpg" alt="VYNN AI logo" width="200">

# 🏦 Agentic Financial Analyst

### AI-Powered Equity Research Platform with Multi-Agent Orchestration

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_Workflow-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Docker](https://img.shields.io/badge/Docker-Production_Ready-2496ED.svg)](https://hub.docker.com/r/fuzanwenn/stock-analyst)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)]()
[![Users](https://img.shields.io/badge/pilot_users-~500-brightgreen.svg)](https://vynnai.com)

**Deployed at [vynnai.com](https://vynnai.com) · ~500 Pilot Users · Production-Grade**

*An autonomous, multi-agent system that performs institutional-quality equity research — from financial data collection and DCF modeling to news intelligence and professional analyst report generation — in under 7 minutes.*

### 🎥 Demo Video

[![VYNN AI Agent Demo](https://img.youtube.com/vi/aXR1ZIEdezs/maxresdefault.jpg)](https://www.youtube.com/watch?v=aXR1ZIEdezs)

▶️ *Click to watch the full demo — agentic chatbot and broker-style dashboard*

</div>

---

## Table of Contents

- [Why This Project](#why-this-project)
- [Architecture Overview](#architecture-overview)
- [Key Capabilities](#key-capabilities)
- [System Components](#system-components)
  - [Supervisor Agent (LangGraph Orchestrator)](#1-supervisor-agent--langgraph-orchestrator)
  - [Financial Data Agent](#2-financial-data-agent)
  - [Financial Model Agent (DCF Builder)](#3-financial-model-agent--9-tab-dcf-builder)
  - [News Intelligence Agent](#4-news-intelligence-agent)
  - [Report Generator Agent](#5-report-generator-agent)
  - [Recommendation Engine](#6-recommendation-engine)
  - [Daily Intelligence Reports](#7-daily-intelligence-reports)
- [LLM Abstraction Layer](#llm-abstraction-layer)
- [Prompt Engineering System](#prompt-engineering-system)
- [Experiment Results & Performance](#experiment-results--performance)
- [Getting Started](#getting-started)
- [Usage Guide](#usage-guide)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Technical Design Decisions](#technical-design-decisions)

---

## Why This Project

Traditional equity research is manual, time-consuming, and expensive — a single analyst report at an investment bank takes hours to days. **VYNN AI Agentic Financial Analyst** automates the entire pipeline end-to-end:

| Capability | Traditional Analyst | This System |
|---|---|---|
| Financial data collection | 30–60 min | **< 5 seconds** |
| DCF model (9-tab Excel) | 2–4 hours | **< 10 seconds** |
| News research (17–18 articles) | 1–2 hours | **~3 minutes** |
| Professional analyst report | 3–6 hours | **~3 minutes** |
| **Total end-to-end** | **6–12 hours** | **< 7 minutes** |

The platform is live at **[vynnai.com](https://vynnai.com)**, serving **~500 pilot users** with real-time, AI-driven equity research. It has been battle-tested across hundreds of analyses covering mega-cap tech (NVDA, AAPL, META, GOOGL, MSFT, AMZN), healthcare, financials, and other sectors.

---

## Architecture Overview

The system implements a **Supervisor-Worker multi-agent architecture** built on [LangGraph](https://github.com/langchain-ai/langgraph), where an LLM-powered supervisor dynamically routes between specialized task agents based on user intent and workflow state.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Query (Natural Language)                │
│           "Analyze NVDA comprehensively with focus on AI chips"     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     🧠 SUPERVISOR AGENT                              │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ • Ticker extraction from NL prompt (LLM-powered)              │  │
│  │ • Intent classification (COMPREHENSIVE / MODEL_ONLY /         │  │
│  │   QUICK_NEWS / CUSTOM)                                        │  │
│  │ • Dynamic routing with dependency resolution                  │  │
│  │ • Deterministic fallback when LLM fails                       │  │
│  │ • Workflow completion detection                                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│           │              │              │              │             │
│     ┌─────┘        ┌─────┘        ┌─────┘        ┌─────┘            │
│     ▼              ▼              ▼              ▼                  │
│  ┌───────┐   ┌───────────┐   ┌────────┐   ┌──────────┐            │
│  │ Fin.  │   │  Model    │   │  News  │   │  Report  │            │
│  │ Data  │──▶│  Gen.     │   │ Intel. │   │  Gen.    │            │
│  │ Agent │   │  Agent    │   │ Agent  │   │  Agent   │            │
│  └───────┘   └───────────┘   └────────┘   └──────────┘            │
│      │              │              │              │                 │
│      ▼              ▼              ▼              ▼                 │
│  Yahoo Fin.    9-Tab Excel    Google News   Professional           │
│  JSON Data     DCF Model     + MongoDB     Analyst Report          │
│                + JSON         Analysis     (Markdown)              │
└──────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     📊 OUTPUT ARTIFACTS                              │
│  • Banker-grade Excel DCF model (9 tabs with live formulas)        │
│  • Computed values JSON (formula evaluation without Excel)          │
│  • Structured screening data (catalysts, risks, mitigations)       │
│  • Professional markdown analyst report                            │
│  • Session persistence for multi-turn chat                         │
└──────────────────────────────────────────────────────────────────────┘
```

### Core Architectural Patterns

| Pattern | Implementation | Why |
|---|---|---|
| **Supervisor + Worker** | LangGraph cyclical graph with conditional edges | LLM proposes routing; dependency resolver enforces valid sequencing |
| **Blackboard State** | `FinancialState` dataclass passed between all agents | Single source of truth; every agent reads/writes to shared state |
| **Builder Pattern** | Each Excel tab has a dedicated builder class | Separation of concerns; tabs can be tested/modified independently |
| **Deterministic Math + LLM Narrative** | `RecommendationCalculator` → `EvidenceExtractor` → LLM → `RecommendationValidator` | Numbers are code; narrative is LLM; validator ensures integrity |
| **Prompt Externalization** | 33 markdown prompt templates in `prompts/` | Version-controlled, auditable prompt engineering |
| **Strategy Pattern** | Pluggable DCF strategies (SaaS, REIT, Bank, Utility, Energy) | Sector-aware modeling without code changes |

---

## Key Capabilities

### 🤖 Autonomous Multi-Agent Orchestration
- **Natural language interface** — ask questions like *"What's your investment recommendation for NVDA?"*
- **Automatic ticker extraction** from free-form text via LLM
- **Intelligent intent classification** — routes simple queries differently from comprehensive analyses
- **Dependency-aware routing** — model generation waits for financial data; report waits for model + news
- **Deterministic fallback** — if LLM routing fails, a rule-based router takes over
- **Session persistence** — multi-turn chat with conversation memory per user/ticker

### 📊 Investment-Banking-Grade Financial Modeling
- **9-tab Excel workbook** with live formulas (not static values)
- **LLM-inferred assumptions** — WACC, terminal growth, revenue growth, margins all automatically calibrated
- **Dual DCF valuation** — Perpetual Growth method + Exit Multiple method with blended fair value
- **Sensitivity analysis** — WACC vs. Terminal Growth and Growth vs. Margin matrices
- **Formula evaluator** — computes all Excel formulas programmatically for downstream use without Excel
- **6 sector-specific strategies**: Generic DCF, SaaS (Rule of 40), REIT (FFO/AFFO), Bank (Excess Returns), Utility, Energy NAV

### 📰 AI-Powered News Intelligence
- **Autonomous multi-perspective scraping** — AI generates search queries across financial, management, industry, and competitive categories
- **LLM-powered relevance filtering** — batch scoring against investment thesis with MongoDB persistence
- **Structured insight extraction** — catalysts, risks, and mitigations with confidence scores, direct quotes, source URLs, and evidence chains
- **Database-aware caching** — skips re-scraping when recent articles exist; saves API costs on subsequent runs

### 📝 Professional Analyst Reports
- **Institutional-quality output** — Executive Summary, Investment Thesis, Financial Analysis, News Analysis, Valuation, Risk Assessment, Recommendation
- **Evidence-backed recommendations** — every claim cites structured evidence IDs (E1, E2, …)
- **Validation pipeline** — `RecommendationValidator` ensures LLM-generated text matches deterministic numbers with ≥95% citation coverage
- **Multi-horizon price targets** — 3-month, 6-month, and 12-month with confidence ranges

### 📅 Daily Intelligence Reports
- **Company-level daily reports** — 24-hour news intelligence with catalyst/risk mapping, peer context, and financial materiality assessment
- **Sector-level daily reports** — cross-company aggregation with rotation trends, thematic analysis, and sector-wide catalyst identification
- **3-step LLM workflow** — Batch analysis → Peer identification → Report generation

---

## System Components

### 1. Supervisor Agent — LangGraph Orchestrator

The brain of the system. Built on [LangGraph](https://github.com/langchain-ai/langgraph)'s cyclical state graph, the supervisor manages the entire workflow lifecycle.

**Key files:** `src/agents/supervisor/`

| Module | Purpose |
|---|---|
| `supervisor_agent.py` | Entry point — `SupervisorWorkflowRunner` handles session management, ticker extraction, and workflow execution |
| `supervisor.py` | Routing logic — `route_workflow_with_llm()` with `_resolve_dependencies()` guardrails |
| `graph.py` | LangGraph graph construction with 4 agent nodes + conditional edges |
| `state.py` | `FinancialState` blackboard + `AgentStage` / `AnalysisObjective` enums |

**Routing Intelligence:**
```
User Prompt → Ticker Extraction (LLM) → Intent Classification → Objective Detection
                                                                        │
                                              ┌─────────────────────────┼──────────────────┐
                                              ▼                         ▼                  ▼
                                        COMPREHENSIVE            MODEL_ONLY          QUICK_NEWS
                                     (all 4 agents)         (fin data + model    (news + summary)
                                                              + summary)
```

**Dependency chain enforcement:**
```
financial_data_agent → model_generation_agent → news_analysis_agent → report_generator_agent
```

The supervisor ensures no agent runs before its prerequisites are complete, even if the LLM suggests otherwise.

### 2. Financial Data Agent

Collects comprehensive financial data from Yahoo Finance via `yfinance`.

**Key file:** `src/financial_scraper.py` (1,127 lines)

- Scrapes income statements, balance sheets, and cash flow statements (annual + quarterly)
- Extracts company metadata (sector, industry, employees, market cap)
- Handles data normalization — converts pandas DataFrames to clean JSON with proper type handling (NaN, numpy types, dates)
- Outputs structured JSON ready for the model generator

### 3. Financial Model Agent — 9-Tab DCF Builder

Generates a **banker-grade Excel DCF workbook** from scraped financial data with LLM-inferred assumptions.

**Key file:** `src/agents/fm/financial_model_builder.py` (381 lines)

**The 9-tab Excel workbook:**

| Tab | Purpose |
|---|---|
| **Raw** | Imported financial data (income, balance sheet, cash flow) |
| **Keys_Map** | Cell reference mapping for cross-tab formula wiring |
| **Assumptions** | FY0 actuals + FY1–FY5 projected assumptions (LLM-inferred) |
| **Historical** | Derived historical metrics (margins, growth rates, ratios) |
| **Projections** | 5-year forward projections with formula-driven line items |
| **Valuation (Perpetual Growth)** | DCF via Gordon Growth Model |
| **Valuation (Exit Multiple)** | DCF via terminal EV/EBITDA exit |
| **Sensitivity** | WACC vs. g and Growth vs. Margin matrices |
| **Summary** | Blended valuation dashboard with QA flags and sanity checks |

**Hidden tab:** `LLM_Inferred` — stores raw LLM assumptions referenced by the Assumptions tab.

**Formula Evaluator** (`formula_evaluator.py`, 1,293 lines): An interpreter that evaluates all Excel formulas without opening Excel — resolves cell references, cross-tab references, arithmetic, and common Excel functions like `SUMIFS`. Outputs computed values to JSON for downstream agents.

### 4. News Intelligence Agent

A multi-stage pipeline for autonomous news collection, filtering, and analysis.

| Stage | Module | Lines | Description |
|---|---|---|---|
| **Scraping** | `article_scraper.py` | 747 | AI-generated search queries → Google News via SerpAPI → `newspaper3k` parsing |
| **Filtering** | `article_filter.py` | 564 | LLM batch scoring (0–10) against investment query → MongoDB persistence |
| **Screening** | `article_screener.py` | 815 | Deep LLM analysis → structured catalysts, risks, mitigations with quotes & evidence |

**Output data model** (Python dataclasses):
- `Catalyst` — type, description, confidence (0–1), evidence, timeline, impact assessment, direct quotes with source URLs
- `Risk` — type, description, severity, confidence, likelihood, impact, mitigation potential
- `Mitigation` — strategy, effectiveness, timeline, evidence

### 5. Report Generator Agent

Synthesizes all pipeline outputs into an institutional-quality analyst report.

**Key file:** `src/report_agent.py` (1,093 lines)

**Data sources aggregated:**
1. Financial data JSON (company info, historical metrics)
2. Computed DCF model JSON (fair value, WACC, projections)
3. Screening data JSON (catalysts, risks, mitigations with evidence)

**Report sections:** Executive Summary → Investment Thesis → Company Overview → Financial Performance → Valuation Analysis (dual DCF) → News & Catalyst Analysis → Risk Assessment → Recommendation (with multi-horizon price targets)

### 6. Recommendation Engine

A unique **3-layer architecture** that ensures LLM-generated recommendations are grounded in verifiable math.

**Key files:** `src/recommendation_engine.py`, `recommendation_calculator.py`, `recommendation_validator.py`, `evidence_extractor.py`

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1: RecommendationCalculator (deterministic)                │
│   Pure Python — expected return, price targets, rating bands     │
│   Sector-aware premiums, volatility caps, time decay framework   │
│   Output: FixedNumbers (immutable, auditable)                    │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2: EvidenceExtractor → LLM Explainer                       │
│   Builds evidence pack with unique IDs (E1, E2, …)              │
│   Source quality scoring (primary > tier-1 > syndication)        │
│   LLM writes narrative using ONLY provided numbers + evidence    │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3: RecommendationValidator                                 │
│   Regex-based number verification against FixedNumbers           │
│   Citation coverage check (≥95% required)                        │
│   Auto-correction of LLM number deviations                       │
│   Output: Validated recommendation ready for publication         │
└──────────────────────────────────────────────────────────────────┘
```

**Rating bands:** STRONG BUY (>20%) · BUY (10–20%) · HOLD (−5% to +10%) · SELL (−20% to −5%) · STRONG SELL (<−20%)

### 7. Daily Intelligence Reports

Standalone modules for recurring daily news intelligence, running independently of the supervisor workflow.

**Key files:** `src/agents/news/daily/`

| Report Type | Module | Description |
|---|---|---|
| **Company Daily** | `company_daily_report.py` (977 lines) | Per-company 24h intelligence — top headlines, impact analysis, financial materiality, peer context, risks & watch items |
| **Sector Daily** | `sector_daily_report.py` (840 lines) | Sector-wide aggregation — rotation trends, thematic signals, company movers, sector catalysts |

**3-step LLM workflow:** Batch catalyst/risk extraction → Peer identification (3–5 peers) → Professional report generation

---

## LLM Abstraction Layer

A unified, provider-agnostic LLM interface with runtime model switching.

**Key file:** `src/llms/config.py`

```python
from llms.config import init_llm, get_llm

init_llm("claude-3.5-sonnet")   # Switch model at runtime
response, cost = get_llm()(messages)  # Callable pattern — provider-agnostic
```

| Model | Provider | Best For |
|---|---|---|
| `gpt-4o-mini` | OpenAI | Fast iteration, cost-effective |
| `claude-3.5-sonnet` | Anthropic | Balanced quality / speed (recommended) |
| `claude-3.5-haiku` | Anthropic | Fastest, lowest cost |
| `claude-3-opus` | Anthropic | Highest quality, complex analysis |

**Features:**
- Retry logic with exponential backoff (3 retries) on rate limits and server errors
- Automatic message format conversion (OpenAI-style → Anthropic-style)
- Per-call cost tracking with model-specific pricing tables
- API key verification before model selection

---

## Prompt Engineering System

All 33 LLM prompts are externalized as versioned markdown files in `prompts/`, enabling rapid iteration without code changes.

| Category | Count | Examples |
|---|---|---|
| **Supervisor Routing** | 3 | `ticker_extraction_and_routing.md`, `workflow_routing.md`, `workflow_completion_summary.md` |
| **News Analysis** | 5 | `daily_catalyst_analysis.md`, `article_relevance_scoring.md`, `comprehensive_news_queries.md` |
| **Financial Modeling** | 2 | `assumptions_inference.md`, `industry_classification.md` |
| **Report Generation** | 10 | `professional_analyst_report.md`, `report_executive_summary.md`, `report_valuation.md`, etc. |
| **Recommendations** | 3 | `investment_recommendation.md`, `recommendation_explainer.md`, `recommendation_rewrite.md` |
| **Sector Analysis** | 5 | `sector_catalyst_analysis.md`, `sector_report_generation.md`, `sector_companies_identification.md` |
| **Miscellaneous** | 5 | `peer_identification.md`, `batch_analysis.md`, `supervisor_performance_summary.md` |

**Anti-hallucination safeguards** embedded in prompts:
- *"NEVER fabricate data"*
- *"If you cannot find the source article, DO NOT include the claim"*
- Hard rules for number formatting and citation requirements
- Structured JSON output schemas enforced in prompt instructions

---

## Experiment Results & Performance

We conducted three rigorous experiments to evaluate system performance, reproducibility, and real-world utility. These results informed the production deployment at [vynnai.com](https://vynnai.com).

### Experiment 1: End-to-End Latency & Component Breakdown

**Objective:** Measure system throughput and identify bottlenecks across the full analysis pipeline.

| Component | Avg. Time | % of Total |
|---|---|---|
| News Analysis Agent (scraping + filtering + screening) | 189.4s | **49.4%** |
| Report Generator Agent | 167.6s | **43.8%** |
| Financial Data Agent (Yahoo Finance) | 4.7s | 1.2% |
| Model Generation Agent (9-tab DCF) | 5.2s | 1.3% |
| Supervisor Overhead | 16.2s | 4.2% |
| **Total (full comprehensive analysis)** | **~383s (6.4 min)** | 100% |

**Key findings:**
- LLM-intensive operations (news analysis + report generation) account for **~93%** of total execution time
- Financial data collection and DCF model building are near-instantaneous (**< 10s combined**)
- Supervisor routing overhead is minimal at **~4%**, validating the lightweight orchestration design
- **System throughput:** ~10 full analyses per hour (sequential execution)

### Experiment 3: Reproducibility & Stability

**Objective:** Evaluate consistency of results across repeated runs and paraphrased prompts.

**Part 1 — Reproducibility (3 tickers × 3 runs each = 9 runs):**

| Ticker | Success Rate | Mean Duration | CV (σ/μ) | Reproducibility Score |
|---|---|---|---|---|
| NVDA | 100% | 384.5s | 0.016 | **0.985** |
| AAPL | 100% | 215.8s | 0.033 | **0.969** |
| MSFT | 100% | 195.6s | 0.035 | **0.965** |

**Part 2 — Stability (3 paraphrased prompts for NVDA):**

| Metric | Result |
|---|---|
| Intent recognition across paraphrases | **100%** |
| Workflow consistency (identical agents triggered) | **100%** |
| Time coefficient of variation | **0.017** |
| **Overall stability score** | **0.983** |

All prompt variations (*"Analyze NVDA stock..."*, *"Give me a comprehensive analysis of NVIDIA..."*, *"What's your investment recommendation for NVDA?"*) correctly extracted the ticker, triggered identical 4-agent workflows, and completed within a 13-second window (378.9s–391.7s).

### Experiment 4: Qualitative Case Studies

**Objective:** Demonstrate real-world output quality through detailed end-to-end case walkthroughs.

| Company | Articles Analyzed | Catalysts Found | Risks Found | DCF Fair Value | Market Price | Implied Upside |
|---|---|---|---|---|---|---|
| **META** | 18 | 7 (90% top conf.) | 6 | $604.06 | $621.71 | **−2.8%** (fairly valued) |
| **NVDA** | 17 | 7 (90% top conf.) | 5 | $208.82 | $188.15 | **+11.0%** (undervalued) |
| **AAPL** | — | — | — | — | — | *Simple query → intelligent single-agent routing* |

**META analysis highlights:** Revenue +23% YoY, Net Income +164%. Top catalysts: earnings beat (90% confidence), WhatsApp monetization (85%), AI capabilities (80%). Risks: EU/US regulatory scrutiny, AI/advertising competition.

**NVDA analysis highlights:** Revenue +69% YoY ($44.1B). Top catalysts: revenue surge (90% confidence), AI infrastructure partnerships (85%), AI demand growth (90%). Risks: US export controls on H20 chips, AMD/Broadcom competition.

**AAPL** demonstrated the supervisor's ability to intelligently route simple queries to a single agent instead of running the full 4-agent pipeline — optimizing both cost and latency.

---

## Getting Started

### Prerequisites

- **Python 3.11+** (recommended via Conda)
- **API Keys:** OpenAI and/or Anthropic (for LLM), SerpAPI (for Google News scraping)
- **MongoDB** (optional — for article caching and platform integration via `vynn-core`)

### Installation

```bash
# 1. Create and activate conda environment
conda create -n stock-analyst python=3.11 -y
conda activate stock-analyst

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env with your API keys:
#   OPENAI_API_KEY=sk-...
#   ANTHROPIC_API_KEY=sk-ant-...
#   SERPAPI_API_KEY=...
#   MONGO_URI=mongodb+srv://...  (optional)
#   MONGO_DB=vynn                (optional)
```

### Update vynn-core (data layer)

```bash
pip install --upgrade --force-reinstall git+https://github.com/Agentic-Analyst/vynn-core.git
```

### Verify Setup

```bash
# Check available LLM models
python main.py --list-llms

# Expected output:
#   ✅ gpt-4o-mini
#   ✅ claude-3.5-sonnet
#   ✅ claude-3.5-haiku
#   ✅ claude-3-opus
```

---

## Usage Guide

### Agentic Chat Mode (Recommended)

The **chat pipeline** accepts natural language queries and autonomously determines the optimal workflow:

```bash
# Comprehensive analysis via natural language
python main.py \
  --email user@example.com \
  --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "Analyze NVDA comprehensively with focus on AI chip market"

# Quick news-only analysis
python main.py \
  --email user@example.com \
  --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "What happened to Tesla stock recently?"

# Financial model only
python main.py \
  --email user@example.com \
  --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "Build a DCF model for Apple"

# Multi-turn conversation (provide session-id for continuity)
python main.py \
  --email user@example.com \
  --timestamp 20250216_120000 \
  --pipeline chat \
  --user-prompt "Now compare it with AMD" \
  --session-id "abc123"
```

### Traditional Pipeline Mode

For deterministic, reproducible analyses with explicit control:

```bash
# Full 7-step comprehensive pipeline
python main.py --ticker NVDA --email user@example.com --timestamp 20250216_120000

# Financial data + DCF model only
python main.py --ticker AAPL --email user@example.com --timestamp 20250216_120000 \
  --pipeline financial-model

# News scraping + filtering (saved to DB for later screening)
python main.py --ticker MSFT --email user@example.com --timestamp 20250216_120000 \
  --pipeline search-news

# Screen existing articles from database
python main.py --ticker MSFT --email user@example.com --timestamp 20250216_120000 \
  --pipeline screen-news

# Company daily intelligence report
python main.py --ticker NVDA --email user@example.com --timestamp 20250216_120000 \
  --pipeline company-daily-report

# Sector daily intelligence report
python main.py --ticker TECHNOLOGY --email user@example.com --timestamp 20250216_120000 \
  --pipeline sector-daily-report
```

### Choosing an LLM

```bash
# Use Claude Sonnet (recommended for quality)
python main.py --ticker NVDA --email user@example.com --timestamp 20250216_120000 \
  --llm claude-3.5-sonnet

# Use GPT-4o Mini (fastest, cheapest)
python main.py --ticker NVDA --email user@example.com --timestamp 20250216_120000 \
  --llm gpt-4o-mini
```

### Output Artifacts

After a comprehensive run, the analysis directory contains:

```
data/{email}/{ticker}/{timestamp}/
├── financials/
│   └── financials_annual_modeling_latest.json    # Raw financial data from Yahoo Finance
├── models/
│   ├── {TICKER}_financial_model.xlsx             # 9-tab Excel DCF workbook
│   └── {TICKER}_financial_model_computed_values.json  # Formula-evaluated JSON
├── searched/                                      # Raw scraped articles
├── filtered/                                      # LLM-scored, relevance-filtered articles
├── screened/
│   └── screening_data.json                        # Structured catalysts, risks, mitigations
├── reports/
│   └── professional_report.md                     # Final institutional-quality analyst report
└── logs/
    └── {TICKER}_analysis.log                      # Full execution log with timing
```

---

## Deployment

### Docker (Production)

```bash
# Pull the latest image
docker pull fuzanwenn/stock-analyst:latest

# Run a comprehensive analysis
docker run --rm \
  -v $(pwd)/data:/app/data \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -e SERPAPI_API_KEY=$SERPAPI_API_KEY \
  fuzanwenn/stock-analyst:latest \
  --ticker NVDA --email user@example.com --timestamp 20250216_120000

# Or use Docker Compose
docker compose up
```

**Image details:** `fuzanwenn/stock-analyst:latest` · ~975 MB · `python:3.11-slim` base

### Multi-Architecture Build & Push

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t fuzanwenn/stock-analyst:latest --push .
```

---

## Project Structure

```
stock-analyst/
├── main.py                          # CLI entry point & pipeline orchestrator (997 lines)
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Production container (python:3.11-slim)
├── docker-compose.yml               # Compose deployment
│
├── src/
│   ├── config.py                    # Centralized configuration defaults
│   ├── logger.py                    # Dual-sink logging (file + console)
│   ├── path_utils.py                # Environment-aware path utilities (Docker / local)
│   │
│   ├── financial_scraper.py         # Yahoo Finance data collection (1,127 lines)
│   ├── article_scraper.py           # Google News scraping via SerpAPI (747 lines)
│   ├── article_filter.py            # LLM-powered relevance scoring + MongoDB (564 lines)
│   ├── article_screener.py          # Deep LLM analysis → structured insights (815 lines)
│   ├── evidence_extractor.py        # Evidence pack builder with citation IDs (225 lines)
│   │
│   ├── recommendation_engine.py     # 3-layer recommendation pipeline (571 lines)
│   ├── recommendation_calculator.py # Deterministic financial math (339 lines)
│   ├── recommendation_validator.py  # LLM output validation & auto-correction (488 lines)
│   │
│   ├── report_agent.py              # Professional report synthesis (1,093 lines)
│   ├── financial_summary_agent.py   # Standalone financial summary (448 lines)
│   ├── news_summary_agent.py        # Standalone news summary (321 lines)
│   ├── session_manager.py           # Multi-turn conversation persistence (399 lines)
│   │
│   ├── llms/                        # LLM provider abstraction
│   │   ├── config.py                # Model registry, singleton, runtime switching
│   │   ├── openai.py                # GPT wrapper + retry + cost tracking
│   │   └── claude.py                # Claude wrapper + retry + cost tracking
│   │
│   └── agents/
│       ├── fm/                      # Financial Model Agent
│       │   ├── financial_model_builder.py   # 9-tab Excel orchestrator (381 lines)
│       │   ├── formula_evaluator.py         # Excel formula interpreter (1,293 lines)
│       │   └── tabs/                        # 11 tab builder modules
│       │       ├── tab_raw.py               #   Raw data import
│       │       ├── tab_historical.py        #   Historical metrics
│       │       ├── tab_assumptions.py       #   FY0 + FY1-FY5 assumptions
│       │       ├── tab_projections.py       #   5-year forward projections
│       │       ├── tab_valuation_perpetual_growth_dcf.py  # Perpetual growth DCF
│       │       ├── tab_valuation_exit_multiple_dcf.py     # Exit multiple DCF
│       │       ├── tab_sensitivity.py       #   Sensitivity matrices
│       │       ├── tab_summary.py           #   Blended valuation dashboard
│       │       ├── tab_llm_inferred_adjusted.py  # Hidden LLM assumptions
│       │       ├── tab_keys_map.py          #   Cell reference mapping
│       │       └── tab_lever_map.py         #   Toggle/lever mapping
│       │
│       ├── news/daily/              # Daily Intelligence Reports
│       │   ├── company_daily_report.py      # Per-company 24h report (977 lines)
│       │   └── sector_daily_report.py       # Sector-wide report (840 lines)
│       │
│       └── supervisor/              # LangGraph Supervisor Orchestrator
│           ├── supervisor_agent.py  # Entry point & session mgmt (1,272 lines)
│           ├── supervisor.py        # LLM routing + dependency resolution (949 lines)
│           ├── graph.py             # LangGraph cyclical graph (359 lines)
│           ├── state.py             # FinancialState blackboard (389 lines)
│           └── task_agents/         # Specialized worker agents
│               ├── financial_data_agent.py      # Yahoo Finance collection
│               ├── model_generation_agent.py    # DCF model building (247 lines)
│               ├── news_analysis_agent.py       # News pipeline orchestration (263 lines)
│               ├── financial_summary_agent.py   # Financial model summary
│               ├── news_summary_agent.py        # News analysis summary
│               └── report_generator_agent.py    # Final report generation
│
├── prompts/                         # 33 externalized LLM prompt templates
│   ├── ticker_extraction_and_routing.md
│   ├── workflow_routing.md
│   ├── daily_catalyst_analysis.md
│   ├── professional_analyst_report.md
│   ├── investment_recommendation.md
│   ├── assumptions_inference.md
│   └── ... (27 more)
│
├── experiments/                     # Research experiments & benchmarks
│   ├── EXPERIMENT_1_SETUP.md        # Latency & component breakdown
│   ├── EXPERIMENT_3_README.md       # Reproducibility & stability
│   ├── EXPERIMENT_4_README.md       # Qualitative case studies
│   ├── run_experiment_*.py          # Experiment runners
│   ├── analyze_experiment_*.py      # Result analysis & metrics
│   ├── visualize_experiment_1.py    # Publication-quality figures
│   ├── instrumented_supervisor.py   # Timing instrumentation wrapper
│   └── results/                     # Experiment output data & figures
│
└── data/                            # Analysis outputs (per user/ticker/timestamp)
```

**Total codebase:** ~15,000+ lines of Python across 40+ modules, plus 33 prompt templates.

---

## Technical Design Decisions

### Why LangGraph over LangChain Agents?

LangGraph's **cyclical state graph** provides explicit control over:
- **Conditional routing** — the supervisor decides the next agent based on full state context, not just the last message
- **Deterministic fallback** — when the LLM routing fails, a rule-based router takes over seamlessly via `_resolve_dependencies()`
- **State persistence** — the `FinancialState` blackboard survives across all agent invocations without message-passing overhead
- **Objective-driven early termination** — `MODEL_ONLY` workflows stop after model + summary; `QUICK_NEWS` stops after news + summary

### Why Deterministic Numbers + LLM Narrative?

A core design principle: **the LLM never invents numbers.** All financial calculations (expected returns, price targets, rating bands) are computed deterministically in `RecommendationCalculator`. The LLM only writes the narrative explanation, and `RecommendationValidator` verifies every number in the output matches the source — with auto-correction for deviations and a 95% minimum citation coverage requirement. This achieves the reliability of deterministic systems with the communication quality of LLMs.

### Why a Custom Formula Evaluator?

The system needs to generate Excel files (for human analysts) AND use computed values programmatically (for downstream LLM agents). Rather than requiring an Excel installation or a heavyweight library, the `FormulaEvaluator` (1,293 lines) interprets the same formulas that appear in the Excel tabs — resolving cell references, cross-tab references, arithmetic, and functions. This ensures the Excel workbook and the JSON output are always consistent.

### Why Externalized Prompts?

All 33 prompts live in `prompts/` as markdown files. This enables:
- **Version control** — prompt changes are tracked in git with full diff visibility
- **A/B testing** — swap prompt versions without code deployments
- **Domain expert editing** — financial analysts can modify prompts directly without touching Python
- **Audit trail** — every prompt version used in production is traceable

### Why MongoDB via vynn-core?

The [`vynn-core`](https://github.com/Agentic-Analyst/vynn-core) package provides a shared data layer (MongoDB + Redis) used by the broader Vynn AI platform at [vynnai.com](https://vynnai.com). Article filtering results are persisted to MongoDB, enabling:
- **Cross-session caching** — subsequent runs skip re-scraping and re-filtering, saving API costs
- **Platform integration** — the vynnai.com frontend reads from the same database
- **Graceful degradation** — if MongoDB is unavailable, the pipeline still works with local file storage

---

<div align="center">

**Built by the [Vynn AI](https://vynnai.com) team · Deployed in production · Serving ~500 pilot users**

*Automating institutional-quality equity research with multi-agent AI orchestration*

</div>
