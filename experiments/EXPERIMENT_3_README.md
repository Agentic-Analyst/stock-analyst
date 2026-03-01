# Experiment 3: Setup Complete ✅

## Overview

Experiment 3 tests **Reproducibility & Stability** of the agentic workflow system through:

### Part 1: Reproducibility Testing
- **Goal:** Same input → consistent output
- **Configuration:** 3 tickers × 5 runs = 15 total runs
- **Metrics:** Success rate, time variance (CV), output consistency

### Part 2: Stability Testing  
- **Goal:** Paraphrased prompts → consistent behavior
- **Configuration:** 1 ticker × 4 prompt variations = 4 total runs
- **Metrics:** Intent recognition, workflow consistency, time variance

---

## Files Created

### 1. Setup Documentation
- **`EXPERIMENT_3_SETUP.md`** - Complete experiment design, methodology, expected results

### 2. Experiment Scripts
- **`run_experiment_3_reproducibility.py`** - Part 1: Run 15 reproducibility tests
- **`run_experiment_3_stability.py`** - Part 2: Run 4 stability tests  
- **`analyze_experiment_3.py`** - Generate comprehensive analysis report

---

## How to Run

### Option 1: Run Both Parts Sequentially

```bash
# Part 1: Reproducibility (3 tickers × 5 runs = ~45-75 minutes)
cd /Users/zanwenfu/IdeaProject/stock-analyst
python experiments/run_experiment_3_reproducibility.py

# Part 2: Stability (4 prompts = ~20-30 minutes)
python experiments/run_experiment_3_stability.py

# Generate report
python experiments/analyze_experiment_3.py
```

### Option 2: Run Parts Independently

You can run either part separately if time is limited:

```bash
# Just reproducibility
python experiments/run_experiment_3_reproducibility.py
python experiments/analyze_experiment_3.py

# Just stability
python experiments/run_experiment_3_stability.py
python experiments/analyze_experiment_3.py
```

---

## What Gets Measured

### Reproducibility Metrics
- ✅ Success rate per ticker and overall
- ✅ Execution time: mean, median, std dev, CV
- ✅ Output consistency: file generation, directory structure
- ✅ Reproducibility score: composite metric (0-1)

### Stability Metrics
- ✅ Intent recognition rate (ticker correctly identified)
- ✅ Workflow consistency (same agents executed)
- ✅ Time variance across prompt variations
- ✅ Stability score: composite metric (0-1)

---

## Expected Output Structure

```
experiments/results/experiment_3/
├── reproducibility/
│   ├── run_NVDA_1_TIMESTAMP.json
│   ├── run_NVDA_2_TIMESTAMP.json
│   ├── ... (15 total)
│   └── logs/
│       ├── stdout_NVDA_1.log
│       └── stderr_NVDA_1.log
├── stability/
│   ├── run_NVDA_prompt1_TIMESTAMP.json
│   ├── ... (4 total)
│   └── logs/
│       ├── stdout_prompt1.log
│       └── stderr_prompt1.log
├── reproducibility_summary_TIMESTAMP.json
├── stability_summary_TIMESTAMP.json
└── EXPERIMENT_3_REPORT.md
```

---

## Key Metrics Explained

### Coefficient of Variation (CV)
```
CV = σ / μ (std dev / mean)
```
- **CV < 0.15:** Excellent consistency
- **CV < 0.25:** Good consistency  
- **CV < 0.40:** Moderate variance
- **CV ≥ 0.40:** High variance

### Reproducibility Score
```
R = (Success Rate) × (1 - CV) × (Output Consistency)
```
- **R > 0.8:** Excellent
- **R > 0.6:** Good
- **R > 0.4:** Moderate
- **R ≤ 0.4:** Needs improvement

### Stability Score
```
S = (Intent Recognition) × (1 - CV) × (Workflow Consistency) × (Success Rate)
```
- Same interpretation as reproducibility score

---

## Estimated Runtime

- **Reproducibility:** 15 runs × 5 min avg = ~75 minutes
- **Stability:** 4 runs × 5 min avg = ~20 minutes
- **Analysis:** < 1 minute
- **Total:** ~1.5-2 hours

---

## Success Criteria

### Minimum Acceptable
- Success rate ≥ 80%
- CV ≤ 0.40
- Intent recognition ≥ 90%

### Target Performance
- Success rate ≥ 95%
- CV ≤ 0.25
- Intent recognition = 100%

### Excellent Performance
- Success rate = 100%
- CV ≤ 0.15
- Intent recognition = 100%

---

## Next Steps

1. **Review setup:** Check `EXPERIMENT_3_SETUP.md` for full details
2. **Run experiments:** Execute the scripts above
3. **Analyze results:** Review generated `EXPERIMENT_3_REPORT.md`
4. **For paper:** Use findings to populate evaluation section

---

**Status:** ✅ Ready to run  
**Created:** December 12, 2024  
**Total Runs:** 19 (15 reproducibility + 4 stability)
