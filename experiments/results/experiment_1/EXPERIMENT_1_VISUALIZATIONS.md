# Experiment 1: Visual Results

## End-to-End Latency by Workflow Type

```
Full Workflow (4 agents, 5 iterations)
META: ████████████████████████████████████████ 383s (6.4 min)

Partial Workflows (2-3 agents)
AAPL: ██████████████████████ 215s (3.6 min)
GOOGL: ██████████ 98s (1.6 min)
AMZN: █████ 46s (0.8 min)
META-min: ██ 20s (0.3 min)
```

## Component Timing Breakdown (Full Workflow)

### Absolute Time (383s total)

```
┌────────────────────────────────────────────────────────────────┐
│ Component                Time (s)   % of Total   Visualization │
├────────────────────────────────────────────────────────────────┤
│ News Analysis Agent      189.36s      49.4%   ████████████████ │
│ Report Generator Agent   167.60s      43.8%   ██████████████   │
│ Financial Data Agent       4.66s       1.2%   █                │
│ Model Generation Agent     5.16s       1.3%   █                │
│ Supervisor Overhead       16.24s       4.2%   ██               │
└────────────────────────────────────────────────────────────────┘
```

### Proportional View

```
Total: 383 seconds (6.4 minutes)

News Analysis (49.4%)
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

Report Generation (43.8%)
▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓

Supervisor (4.2%)
▓▓▓▓

Financial+Model (2.6%)
▓▓▓
```

## Performance Comparison Matrix

```
┌─────────────┬─────────┬────────────┬────────────┬──────────────┐
│   Ticker    │ Agents  │ Iterations │  Time (s)  │  Complexity  │
├─────────────┼─────────┼────────────┼────────────┼──────────────┤
│ META (full) │    4    │     5      │   383.02   │ ████████████ │
│ AAPL        │    2    │     2      │   215.43   │ ███████      │
│ GOOGL       │    2    │     3      │    98.04   │ ███          │
│ AMZN        │    3    │     4      │    45.88   │ ██           │
│ META (min)  │    2    │     3      │    20.02   │ █            │
└─────────────┴─────────┴────────────┴────────────┴──────────────┘
```

## Workflow Composition Patterns

### Pattern 1: Full Analysis (383s)

```
Start → Financial (5s) → News (189s) → Model (5s) → Report (168s) → End
        ═══════════════████████████████════════════████████████████
```

### Pattern 2: News Focus (215s)

```
Start → News (206s) → Summary (0s) → End
        ████████████════════════════
```

### Pattern 3: Financial Only (20-98s)

```
Start → Financial (5s) → Model (5-7s) → [Other] → End
        ════════════════════════════════════
```

## Latency Distribution

```
Time (seconds)
  0 ─┤
 50 ─┤  █
100 ─┤  █ █
150 ─┤  █ █
200 ─┤  █ █ █
250 ─┤  █ █ █
300 ─┤  █ █ █
350 ─┤  █ █ █
400 ─┤  █ █ █ █
     └──────────────
      Runs
      
      Legend: █ = 1 workflow run
```

## Agent Execution Frequency

```
┌──────────────────────┬───────┬──────────┐
│        Agent         │ Runs  │   Freq   │
├──────────────────────┼───────┼──────────┤
│ Financial Data       │ 5/5   │ 100%  ██ │
│ Model Generation     │ 4/5   │  80%  ██ │
│ News Analysis        │ 2/5   │  40%  █  │
│ Report Generator     │ 1/5   │  20%  ▓  │
│ News Summary         │ 1/5   │  20%  ▓  │
└──────────────────────┴───────┴──────────┘
```

## Time-per-Agent Analysis

```
Average Execution Time per Agent Type

News Analysis:      ~198s  ████████████████████
Report Generator:   ~168s  ████████████████▓
Model Generation:     ~6s  ▓
Financial Data:       ~5s  ▓
News Summary:        ~0s   (cached)
```

## LLM vs Non-LLM Time

```
Full Workflow (383s) Breakdown:

LLM-Intensive (357s / 93%)
┌────────────────────────────────────────────┐
│ News Analysis    ████████████████████       │ 189s
│ Report Gen       ████████████████           │ 168s
└────────────────────────────────────────────┘

Non-LLM (26s / 7%)
┌────────┐
│ Data   │ 5s
│ Model  │ 5s
│ Other  │ 16s
└────────┘
```

## Optimization Impact Estimates

```
Current Performance:  383s

With Optimizations:

┌─────────────────────┬──────────┬──────────┬──────────┐
│    Optimization     │ Savings  │ New Time │ Speedup  │
├─────────────────────┼──────────┼──────────┼──────────┤
│ Caching (warm)      │  ~200s   │   183s   │   2.1x   │
│ Parallelization     │   ~60s   │   323s   │   1.2x   │
│ Prompt optimization │   ~40s   │   343s   │   1.1x   │
│ Combined            │  ~280s   │   103s   │   3.7x   │
└─────────────────────┴──────────┴──────────┴──────────┘

Estimated Best Case: ~100 seconds (1.7 minutes)
```

## Throughput Analysis

```
Current Sequential Processing:

1 workflow = 383s ≈ 6.4 minutes
Throughput = 60/6.4 ≈ 9.4 analyses/hour

With 5x Parallelization:

5 parallel workflows = 383s (same wall time)
Throughput = 5 × 9.4 ≈ 47 analyses/hour

Bottleneck: LLM API rate limits
```

## Scalability Projection

```
Number of Parallel Workflows vs. Throughput

Workflows/hour
 50 │                           ╱──
    │                       ╱───
 40 │                   ╱───
    │               ╱───
 30 │           ╱───
    │       ╱───
 20 │   ╱───
    │╱──
 10 │
    └─────────────────────────────────
     1    2    5    10   20   50
          Parallelism Factor
          
Note: Assumes LLM rate limits allow parallelism
```

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| **Samples** | 5 workflows |
| **Tickers** | META (2x), AAPL, GOOGL, AMZN |
| **Mean E2E** | 152.5s (all) / 383s (full only) |
| **Median E2E** | 98.0s |
| **Fastest** | 20.0s (minimal workflow) |
| **Slowest** | 383.0s (full workflow) |
| **LLM %** | 93% (full workflow) |
| **Data %** | 3% (full workflow) |
| **Overhead %** | 4% (full workflow) |

---

*Generated: December 12, 2024*  
*Data source: Production workflow logs*
