# Experiment 1: End-to-End Latency & Component Breakdown

## Experiment Objective

Measure the end-to-end latency of the agentic workflow system and compare cold start performance versus warm/cached execution to evaluate system efficiency and cache effectiveness.

## Experimental Design

### Test Configuration

- **Test Tickers:** NVDA, AAPL, MSFT (representative tech stocks)
- **Prompt Template:** "Analyze {ticker} stock and provide investment recommendation"
- **Phases:** 2 (Cold Start + Warm/Cached)
- **Total Runs:** 6 (3 tickers × 2 phases)

### Phases

**Phase 1: Cold Start Execution**
- Clear cache/state before each run
- Measure baseline latency when all components must fetch and compute fresh data
- Records: Financial data retrieval, news analysis, model generation, report creation

**Phase 2: Warm/Cached Execution**
- Re-run same queries immediately after cold runs
- Measure latency when data can be reused from cache
- Evaluates effectiveness of caching mechanisms

### Metrics Collected

1. **End-to-End Latency (t_E2E):** Total time from request initiation to workflow completion
2. **Completion Status:** Success/failure status of workflow execution
3. **Phase Comparison:** Cold vs warm execution time differences
4. **Success Rate:** Percentage of successful completions per phase

## Implementation

### Infrastructure

The experiment uses a subprocess-based approach to run the supervisor workflow:

1. **`run_experiment_1_standalone.py`**: Full experiment runner
   - Executes 6 complete workflow runs (3 tickers × 2 phases)
   - Captures timing, status, and output for each run
   - Saves raw results to JSON
   - Generates comprehensive statistical report

2. **`run_experiment_1_demo.py`**: Demo/proof-of-concept version
   - Executes 2 runs (1 ticker × 2 phases)
   - Faster execution for testing and demonstration
   - Generates sample report showing experiment methodology

### Execution Method

```bash
# Demo run (1 ticker, faster)
python experiments/run_experiment_1_demo.py

# Full experiment (3 tickers)
python experiments/run_experiment_1_standalone.py
```

Each run invokes the supervisor workflow via CLI:
```bash
conda run -n stock-analyst python main.py \\
    --pipeline chat \\
    --email experiment@vynnai.com \\
    --user-prompt "Analyze TICKER stock and provide investment recommendation" \\
    --timestamp YYYYMMDD_HHMMSS_phase_runnum
```

### Data Collection

For each run, we capture:
- **Execution time:** Measured using `time.monotonic()` for precision
- **Return code:** Subprocess exit status
- **stdout/stderr:** Saved to log files for debugging
- **Completion status:** Extracted from workflow output
- **Phase identifier:** Cold vs warm for comparison

### Output Structure

```
experiments/results/experiment_1/
├── raw_results_TIMESTAMP.json          # Raw timing data
├── EXPERIMENT_1_REPORT.md              # Statistical analysis report
└── logs/
    ├── stdout_cold_NVDA_1.log
    ├── stderr_cold_NVDA_1.log
    └── ... (all run logs)
```

## Statistical Analysis

The analysis script computes:

- **Mean, Median:** Central tendency measures
- **Standard Deviation:** Variability in execution times
- **Min, Max:** Range of observed latencies
- **Percentiles (P25, P75, P95):** Distribution characteristics
- **Improvement Percentage:** (Cold - Warm) / Cold × 100%

## Expected Results

### Hypotheses

1. **H1:** Cold start latency > Warm latency (cache provides speedup)
2. **H2:** Variance in cold runs > Variance in warm runs (more external dependencies)
3. **H3:** Success rate ≈ 100% for both phases (system reliability)

### Key Questions

1. What is the baseline end-to-end latency for a complete analysis?
2. How much speedup does caching provide?
3. Are there significant differences across different tickers?
4. Is the system performance consistent (low variance)?

## Limitations & Considerations

1. **Network Variability:** API call latencies may vary due to network conditions
2. **API Rate Limits:** May affect timing if rate limits are hit
3. **System Load:** Host machine load can impact results
4. **Sample Size:** Limited to 3 tickers for time efficiency (can be expanded)
5. **Cache Behavior:** Assumes caching mechanisms are working as designed

## Future Extensions

1. **Expanded Ticker Set:** Test with 10-20 tickers for better statistics
2. **Multiple Prompts:** Test different prompt variations per ticker
3. **Component Breakdown:** Instrument individual agents for per-component timing
4. **Repeated Trials:** Run each configuration 3-5 times for confidence intervals
5. **Cache Control:** Explicitly clear/warm cache with known states

## Notes

- This experiment focuses on system-level E2E metrics
- Per-component timing requires code instrumentation (see `timing_instrument.py`)
- Actual results will depend on API performance, data availability, and LLM response times
- All runs use the stock-analyst conda environment with required dependencies

---

**Experiment Status:** In Progress  
**Created:** December 12, 2024  
**Last Updated:** December 12, 2024
