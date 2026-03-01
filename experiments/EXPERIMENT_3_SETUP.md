# Experiment 3: Reproducibility & Stability

## Experiment Objective

Evaluate the reproducibility and stability of the agentic workflow system by:
1. **Reproducibility:** Testing whether identical inputs produce consistent outputs across multiple runs
2. **Stability:** Measuring output variance when inputs are slightly perturbed (paraphrased prompts)

## Experimental Design

### Part 1: Reproducibility Testing

**Goal:** Verify that running the same analysis multiple times produces consistent results

**Test Configuration:**
- **Tickers:** NVDA, AAPL, MSFT (3 companies)
- **Prompt:** Fixed prompt per ticker
- **Runs per ticker:** 5 repetitions
- **Total runs:** 15 (3 tickers × 5 runs)

**Metrics Collected:**
1. **Completion Status:** Success/failure consistency
2. **Execution Time:** Variance across runs
3. **Output Artifacts:** Existence and consistency of generated files
4. **Session IDs:** Track each run uniquely

**Expected Behavior:**
- All runs should complete successfully
- Execution times should be similar (within reasonable variance)
- Output artifacts should be generated consistently
- File structures should match across runs

### Part 2: Stability Testing (Prompt Paraphrasing)

**Goal:** Measure robustness to natural language variations in user prompts

**Test Configuration:**
- **Tickers:** NVDA (primary test case)
- **Prompt Variations:** 4 paraphrases of the same intent
- **Total runs:** 4 (1 ticker × 4 prompts)

**Prompt Variations (Semantically Equivalent):**
1. "Analyze NVDA stock and provide investment recommendation"
2. "Give me a comprehensive analysis of NVIDIA stock"
3. "What's your investment recommendation for NVDA?"
4. "Provide detailed analysis and recommendation for NVIDIA"

**Metrics Collected:**
1. **Intent Recognition:** Does each prompt trigger full analysis?
2. **Workflow Consistency:** Same agents executed across prompts?
3. **Execution Time Variance:** How much variation in latency?
4. **Output Consistency:** Are report structures similar?

## Implementation

### Infrastructure

**Scripts:**
1. `run_experiment_3_reproducibility.py` - Reproducibility testing (5 runs per ticker)
2. `run_experiment_3_stability.py` - Stability testing (4 prompt variations)
3. `analyze_experiment_3.py` - Statistical analysis and report generation

**Execution Method:**
```bash
# Part 1: Reproducibility
python experiments/run_experiment_3_reproducibility.py

# Part 2: Stability
python experiments/run_experiment_3_stability.py

# Analysis & Report
python experiments/analyze_experiment_3.py
```

### Data Collection

**For each run, capture:**
- Start/end timestamps
- Execution duration
- Completion status (success/error)
- Session ID for traceability
- Output directory path
- Generated file counts and types

**Output Structure:**
```
experiments/results/experiment_3/
├── reproducibility/
│   ├── run_NVDA_1_TIMESTAMP.json
│   ├── run_NVDA_2_TIMESTAMP.json
│   ├── ... (15 total)
│   └── logs/
├── stability/
│   ├── run_NVDA_prompt1_TIMESTAMP.json
│   ├── run_NVDA_prompt2_TIMESTAMP.json
│   ├── ... (4 total)
│   └── logs/
├── reproducibility_summary.json
├── stability_summary.json
└── EXPERIMENT_3_REPORT.md
```

## Statistical Analysis

### Reproducibility Metrics

**Success Rate:**
- % of runs that complete successfully per ticker
- Consistency of completion status

**Execution Time Variance:**
- Mean, Median, Std Dev, CV (coefficient of variation)
- Formula: `CV = σ / μ`
- Low CV (<0.2) indicates high reproducibility

**Output Consistency:**
- % of runs that generate expected artifacts
- File count variance

**Reproducibility Score:**
```
R = (Success Rate) × (1 - CV_time) × (Output Consistency)
R ∈ [0, 1], higher is better
```

### Stability Metrics

**Prompt Robustness:**
- % of prompts that trigger intended workflow
- Consistency of agent execution paths

**Time Variance Across Prompts:**
- Range, IQR, coefficient of variation
- Compare to reproducibility variance (should be similar)

**Stability Score:**
```
S = (Intent Recognition Rate) × (1 - CV_time) × (Workflow Consistency)
S ∈ [0, 1], higher is better
```

## Expected Results

### Reproducibility Hypotheses

**H1:** Success rate ≥ 90% across all runs
- System should be reliable for production use

**H2:** CV of execution time ≤ 0.3
- Some variance expected due to network/API latency
- But overall should be consistent

**H3:** Output consistency = 100%
- Deterministic file generation
- Same artifacts produced every time

### Stability Hypotheses

**H1:** Intent recognition = 100%
- All paraphrases should trigger same workflow

**H2:** CV across prompts ≈ CV within reproducibility
- Natural language variation shouldn't add significant variance

**H3:** Workflow consistency = 100%
- Same sequence of agents for semantically equivalent prompts

## Limitations & Considerations

### Known Variability Sources

1. **Network Latency:** API calls have inherent variance
2. **LLM Non-determinism:** Even with temperature=0, some models show variance
3. **News Data:** Time-varying (articles published between runs)
4. **System Load:** Background processes, API rate limits

### Controlled Variables

1. **Same Environment:** All runs use stock-analyst conda env
2. **Same Timestamp:** Fix timestamp to ensure same data directories
3. **Sequential Execution:** Avoid concurrency effects
4. **Consistent Configuration:** No changes to system settings between runs

### Uncontrolled Variables

1. **API Response Times:** OpenAI/Claude latency varies
2. **News Sources:** Google News may return different articles
3. **Market Data:** Yahoo Finance may update between runs
4. **System Resources:** Memory, CPU, network conditions

## Comparison to Evaluation Plan

### Original Specification

The plan called for:
- **Reproducibility:** K=5-10 runs, compare valuation outputs (FCF, WACC, EV)
- **Stability:** Paraphrased news articles, compare adjusted parameters

### Our Implementation

**Adaptations:**
- Focus on **workflow-level reproducibility** (completion, timing, outputs)
- Use **prompt paraphrasing** instead of news article paraphrasing (more feasible)
- Measure **system consistency** rather than parameter-level comparisons
- Test **natural language robustness** of intent detection

**Why These Adaptations:**
1. **Feasibility:** Prompt-level testing is easier to implement and control
2. **Meaningfulness:** Workflow consistency is critical for production systems
3. **Scope:** This is stock-analyst (CLI/supervisor), not full VYNN backend
4. **Timeline:** Can execute in reasonable time without complex instrumentation

## Success Criteria

### Minimum Acceptable Performance

- **Reproducibility:** Success rate ≥ 80%, CV ≤ 0.4
- **Stability:** Intent recognition ≥ 90%, similar CV to reproducibility

### Target Performance

- **Reproducibility:** Success rate ≥ 95%, CV ≤ 0.2
- **Stability:** Intent recognition = 100%, CV ≤ 0.25

### Excellent Performance

- **Reproducibility:** Success rate = 100%, CV ≤ 0.15
- **Stability:** Intent recognition = 100%, CV ≤ 0.20

## Future Extensions

1. **Larger Sample Sizes:** 10-20 runs per ticker for confidence intervals
2. **More Tickers:** Test across 10+ companies
3. **Parameter-Level Analysis:** Extract and compare DCF parameters if available
4. **News Article Paraphrasing:** Implement original plan with controlled news
5. **Seed Control:** If LLM framework supports it, fix seeds for exact reproducibility
6. **Cross-Model Testing:** Test reproducibility across different LLM providers

## Notes

- This experiment provides **system-level validation** of consistency
- Results will demonstrate production readiness and reliability
- Low variance indicates well-engineered system with minimal non-determinism
- High variance would suggest need for additional guardrails or caching

---

**Experiment Status:** Ready to Run  
**Created:** December 12, 2024  
**Estimated Duration:** ~60-90 minutes (19 total runs × 3-5 min each)
