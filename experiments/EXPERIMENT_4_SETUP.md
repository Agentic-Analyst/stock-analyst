# Experiment 4: Qualitative Case Studies

**Date:** 2025-12-12  
**Experiment Type:** Qualitative Analysis  
**Purpose:** Research Paper Evaluation Section

## Objective

Demonstrate the agentic workflow system's capabilities through detailed qualitative case studies showing:
- How news events are identified and parsed
- What parameter adjustments are made to valuations
- How the DCF model changes in response to events
- What narratives and recommendations are produced

## Research Paper Goals

This experiment populates:
- **Case Study Examples:** Detailed walkthrough of 2-3 real company analyses
- **System Reasoning:** How agents process information and make decisions
- **End-to-End Demonstration:** From news ingestion to final investment recommendation
- **Real-World Validation:** System behavior on actual market events

## Experimental Design

### Case Selection Criteria

Select 2-3 companies with:
1. **Significant Recent Events:** Earnings reports, product launches, regulatory changes
2. **Rich News Coverage:** Multiple articles to demonstrate news screener
3. **Quantifiable Impact:** Clear financial metrics that can be adjusted
4. **Diverse Scenarios:** Different industries, sentiment, and event types

### Candidate Companies

Based on existing data in system:

1. **META (Meta Platforms)**
   - Event: Q3 2023 earnings beat (Revenue +23%, Net Income +164%)
   - Sentiment: Mixed (growth vs regulatory concerns)
   - Data: Multiple complete analyses available

2. **NVDA (NVIDIA)**
   - Event: AI/GPU demand surge, data center growth
   - Sentiment: Bullish (technology leadership)
   - Data: Recent analyses available

3. **AAPL (Apple)**
   - Event: Product cycle updates, supply chain considerations
   - Sentiment: Neutral to Bullish
   - Data: Historical analyses available

### Data to Extract Per Case

For each company case study, extract:

#### 1. News Analysis (`s_t^{news}`)
- Articles analyzed (count and sources)
- Overall sentiment (bullish/bearish/neutral)
- Key catalysts identified (type, description, confidence)
- Key risks identified (type, description, confidence)
- Supporting evidence and direct quotes

#### 2. Financial Data
- Revenue, earnings, cash flow metrics
- Historical trends
- Peer comparisons (if available)

#### 3. Parameter Adjustments (`s_t^{adj}`)
- Growth rate adjustments
- Margin adjustments  
- WACC/risk adjustments
- Reasoning for each adjustment

#### 4. Valuation Changes
- **Before:** Base DCF without news adjustments
- **After:** DCF with news-driven adjustments
- Fair value calculation
- Price target
- Upside/downside percentage

#### 5. Generated Narrative
- Executive summary
- Investment thesis
- Key recommendation (Buy/Hold/Sell)
- Risk factors highlighted
- Confidence level

## Metrics to Report

### Quantitative Metrics
- Number of articles analyzed per company
- Catalyst/risk count
- Confidence scores (average)
- Valuation change magnitude (%)
- Processing time per analysis

### Qualitative Metrics
- Coherence of reasoning chain
- Appropriateness of parameter adjustments
- Quality of narrative generation
- Alignment between news and recommendations

## Execution Plan

### Step 1: Setup (5 minutes)
- Create experiment infrastructure
- Identify which existing analyses to use
- OR run fresh analyses if needed

### Step 2: Data Collection (30-60 minutes)
- For each company:
  - Run full analysis OR extract from existing runs
  - Save all intermediate outputs
  - Collect artifacts (JSON, reports, logs)

### Step 3: Data Extraction (30 minutes)
- Parse JSON outputs
- Structure data according to schema above
- Extract key quotes and evidence
- Calculate metrics

### Step 4: Report Generation (30 minutes)
- Create comprehensive markdown report
- Include detailed walkthrough for each case
- Add tables, quotes, and comparisons
- Highlight interesting patterns

## Expected Outcomes

### Success Criteria
- At least 2 complete case studies with full data
- Clear demonstration of agent reasoning
- Quantifiable valuation impacts from news
- High-quality narratives suitable for paper inclusion

### Report Structure
```
EXPERIMENT_4_REPORT.md
├── Executive Summary
├── Methodology
├── Case Study 1: [Company]
│   ├── Company Overview
│   ├── Event Context
│   ├── News Analysis
│   ├── Parameter Adjustments
│   ├── Valuation Impact
│   └── Generated Narrative
├── Case Study 2: [Company]
│   └── ... (same structure)
├── Cross-Case Analysis
│   ├── Common Patterns
│   ├── System Strengths
│   └── Areas for Improvement
└── Conclusions
```

## Data Sources

### Primary Data
- Session JSON files: `data/*/sessions/{TICKER}/*.json`
- Screening data: `data/*/{TICKER}/*/screened/screening_data.json`
- Financial models: `data/*/{TICKER}/*/models/*_financial_model_computed_values.json`
- Generated reports: `data/*/{TICKER}/*/reports/*.md`

### Logs
- Info logs: `data/*/{TICKER}/*/info.log`
- For timing and execution details

## Timeline

- **Setup:** 5 minutes
- **Execution:** 30-60 minutes (if running fresh analyses)
- **Data Extraction:** 30 minutes
- **Report Writing:** 30 minutes
- **Total:** ~2 hours (or <1 hour if using existing data)

## Notes

- Can use existing analysis data to save time
- Focus on quality over quantity (2-3 cases is sufficient)
- Extract actual system outputs (no fake data)
- Highlight both strengths and limitations honestly
- Make findings suitable for research paper case study section

---

**Status:** Ready to execute  
**Next Step:** Run case study collection script
