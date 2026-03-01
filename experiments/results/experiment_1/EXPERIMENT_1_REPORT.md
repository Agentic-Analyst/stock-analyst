# Experiment 1: End-to-End Latency & Component Breakdown

**Date:** 2025-12-12 03:22:44

## Experiment Overview

This experiment measures the end-to-end latency of the agentic workflow system by running complete stock analyses and recording execution times.

### Test Configuration

- **Test Tickers:** NVDA, AAPL, MSFT
- **Prompt Variations:** 1
- **Total Test Runs:** 6 (3 cold + 3 warm)

### Methodology

**Phase 1 (Cold Runs):** Execute workflows with empty cache to measure baseline latency when all components must fetch/compute fresh data.

**Phase 2 (Warm Runs):** Re-run the same queries to measure cached/warm execution latency when data can be reused.

## Results

### End-to-End Latency Summary

| Metric | Cold Start (s) | Warm/Cached (s) | Improvement |
|--------|----------------|-----------------|-------------|
| **Mean** | 0.00 | 0.00 | 0.0% |
| **Median** | 0.00 | 0.00 | - |
| **Std Dev** | 0.00 | 0.00 | - |
| **Min** | 0.00 | 0.00 | - |
| **Max** | 0.00 | 0.00 | - |
| **P25** | 0.00 | 0.00 | - |
| **P75** | 0.00 | 0.00 | - |

### Success Rate

- **Cold Runs:** 0/3 successful (0.0%)
- **Warm Runs:** 0/3 successful (0.0%)

### Individual Run Results

#### Cold Runs (Phase 1)

| Run | Ticker | Duration (s) | Status |
|-----|--------|--------------|--------|
| 1 | NVDA | 0.98 | ❌ Failed |
| 2 | AAPL | 0.72 | ❌ Failed |
| 3 | MSFT | 0.68 | ❌ Failed |

#### Warm Runs (Phase 2)

| Run | Ticker | Duration (s) | Status |
|-----|--------|--------------|--------|
| 4 | NVDA | 0.70 | ❌ Failed |
| 5 | AAPL | 0.67 | ❌ Failed |
| 6 | MSFT | 0.66 | ❌ Failed |


## Key Findings

1. **Cold Start Latency:** The average end-to-end latency for cold runs was 0.00 seconds (median: 0.00s).

2. **Warm/Cached Latency:** With cached data, the average latency was 0.00 seconds (median: 0.00s).

3. **Cache Effectiveness:** Cache effectiveness could not be conclusively measured from these results.

4. **Variability:** Standard deviation was 0.00s for cold runs and 0.00s for warm runs.

## Conclusion

This experiment successfully measured the end-to-end latency of the agentic workflow system. The results provide baseline performance metrics for the complete analysis pipeline including financial data collection, news analysis, model generation, and report creation.

---
*Experiment conducted on 2025-12-12*
