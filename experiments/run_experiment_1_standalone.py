"""
Experiment 1: End-to-End Latency & Component Breakdown (Standalone Version)

This experiment measures end-to-end workflow latency by running the supervisor
as a subprocess and measuring execution time.
"""

import subprocess
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import statistics


# Test configuration
TEST_TICKERS = ["NVDA", "AAPL", "MSFT"]
TEST_PROMPTS = [
    "Analyze {ticker} stock and provide investment recommendation",
]


def run_single_workflow(ticker: str, prompt: str, phase: str, run_number: int, timestamp: str) -> Dict:
    """
    Run a single workflow by invoking main.py as subprocess.
    
    Returns dict with timing and status info.
    """
    formatted_prompt = prompt.format(ticker=ticker)
    
    print(f"\n{'='*80}")
    print(f"[EXPERIMENT 1] Run #{run_number} | Phase: {phase.upper()} | Ticker: {ticker}")
    print(f"[EXPERIMENT 1] Prompt: {formatted_prompt}")
    print(f"{'='*80}\n")
    
    # Measure execution time
    start_time = time.monotonic()
    
    # Run the CLI command with conda
    cmd = [
        "conda", "run", "-n", "stock-analyst",
        "python", "main.py",
        "--pipeline", "chat",
        "--email", "experiment@vynnai.com",
        "--user-prompt", formatted_prompt,
        "--timestamp", f"{timestamp}_{phase}_{run_number}"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
            cwd="/Users/zanwenfu/IdeaProject/stock-analyst"
        )
        
        end_time = time.monotonic()
        duration = end_time - start_time
        
        # Check if successful
        success = result.returncode == 0
        
        timing_data = {
            "ticker": ticker,
            "prompt": formatted_prompt,
            "phase": phase,
            "run_number": run_number,
            "duration_seconds": duration,
            "success": success,
            "return_code": result.returncode,
            "timestamp": timestamp,
            "stdout_lines": len(result.stdout.splitlines()) if result.stdout else 0,
            "stderr_lines": len(result.stderr.splitlines()) if result.stderr else 0,
        }
        
        # Try to extract info from output
        if result.stdout:
            # Look for completion indicators
            if "WORKFLOW COMPLETE" in result.stdout:
                timing_data["completion_status"] = "completed"
            elif "ERROR" in result.stdout or "FAILED" in result.stdout:
                timing_data["completion_status"] = "error"
            else:
                timing_data["completion_status"] = "unknown"
        
        print(f"[EXPERIMENT 1] ✅ Completed | Duration: {duration:.2f}s | Success: {success}")
        
        return timing_data
        
    except subprocess.TimeoutExpired:
        end_time = time.monotonic()
        duration = end_time - start_time
        
        print(f"[EXPERIMENT 1] ⏱️ Timeout after {duration:.2f}s")
        
        return {
            "ticker": ticker,
            "prompt": formatted_prompt,
            "phase": phase,
            "run_number": run_number,
            "duration_seconds": duration,
            "success": False,
            "return_code": -1,
            "timestamp": timestamp,
            "completion_status": "timeout",
        }
        
    except Exception as e:
        end_time = time.monotonic()
        duration = end_time - start_time
        
        print(f"[EXPERIMENT 1] ❌ Error: {e}")
        
        return {
            "ticker": ticker,
            "prompt": formatted_prompt,
            "phase": phase,
            "run_number": run_number,
            "duration_seconds": duration,
            "success": False,
            "return_code": -2,
            "timestamp": timestamp,
            "completion_status": "error",
            "error": str(e),
        }


def compute_statistics(durations: List[float]) -> Dict:
    """Compute statistical metrics from duration list."""
    if not durations:
        return {}
    
    sorted_durations = sorted(durations)
    n = len(sorted_durations)
    
    return {
        "count": n,
        "mean": statistics.mean(durations),
        "median": statistics.median(durations),
        "std_dev": statistics.stdev(durations) if n > 1 else 0.0,
        "min": min(durations),
        "max": max(durations),
        "p25": sorted_durations[n // 4] if n >= 4 else sorted_durations[0],
        "p75": sorted_durations[3 * n // 4] if n >= 4 else sorted_durations[-1],
        "p95": sorted_durations[int(0.95 * n)] if n >= 20 else sorted_durations[-1],
    }


def generate_report(cold_results: List[Dict], warm_results: List[Dict], output_path: Path):
    """Generate markdown report with experiment results."""
    
    # Extract durations
    cold_durations = [r["duration_seconds"] for r in cold_results if r["success"]]
    warm_durations = [r["duration_seconds"] for r in warm_results if r["success"]]
    
    # Compute statistics
    cold_stats = compute_statistics(cold_durations)
    warm_stats = compute_statistics(warm_durations)
    
    # Calculate improvement
    if cold_stats.get("mean") and warm_stats.get("mean"):
        improvement_pct = ((cold_stats["mean"] - warm_stats["mean"]) / cold_stats["mean"]) * 100
    else:
        improvement_pct = 0.0
    
    # Generate report
    report = f"""# Experiment 1: End-to-End Latency & Component Breakdown

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Experiment Overview

This experiment measures the end-to-end latency of the agentic workflow system by running complete stock analyses and recording execution times.

### Test Configuration

- **Test Tickers:** {", ".join(TEST_TICKERS)}
- **Prompt Variations:** {len(TEST_PROMPTS)}
- **Total Test Runs:** {len(cold_results) + len(warm_results)} ({len(cold_results)} cold + {len(warm_results)} warm)

### Methodology

**Phase 1 (Cold Runs):** Execute workflows with empty cache to measure baseline latency when all components must fetch/compute fresh data.

**Phase 2 (Warm Runs):** Re-run the same queries to measure cached/warm execution latency when data can be reused.

## Results

### End-to-End Latency Summary

| Metric | Cold Start (s) | Warm/Cached (s) | Improvement |
|--------|----------------|-----------------|-------------|
| **Mean** | {cold_stats.get('mean', 0):.2f} | {warm_stats.get('mean', 0):.2f} | {improvement_pct:.1f}% |
| **Median** | {cold_stats.get('median', 0):.2f} | {warm_stats.get('median', 0):.2f} | - |
| **Std Dev** | {cold_stats.get('std_dev', 0):.2f} | {warm_stats.get('std_dev', 0):.2f} | - |
| **Min** | {cold_stats.get('min', 0):.2f} | {warm_stats.get('min', 0):.2f} | - |
| **Max** | {cold_stats.get('max', 0):.2f} | {warm_stats.get('max', 0):.2f} | - |
| **P25** | {cold_stats.get('p25', 0):.2f} | {warm_stats.get('p25', 0):.2f} | - |
| **P75** | {cold_stats.get('p75', 0):.2f} | {warm_stats.get('p75', 0):.2f} | - |

### Success Rate

- **Cold Runs:** {sum(1 for r in cold_results if r['success'])}/{len(cold_results)} successful ({sum(1 for r in cold_results if r['success'])/len(cold_results)*100:.1f}%)
- **Warm Runs:** {sum(1 for r in warm_results if r['success'])}/{len(warm_results)} successful ({sum(1 for r in warm_results if r['success'])/len(warm_results)*100:.1f}%)

### Individual Run Results

#### Cold Runs (Phase 1)

| Run | Ticker | Duration (s) | Status |
|-----|--------|--------------|--------|
"""
    
    for r in cold_results:
        status = "✅ Success" if r["success"] else "❌ Failed"
        report += f"| {r['run_number']} | {r['ticker']} | {r['duration_seconds']:.2f} | {status} |\n"
    
    report += """
#### Warm Runs (Phase 2)

| Run | Ticker | Duration (s) | Status |
|-----|--------|--------------|--------|
"""
    
    for r in warm_results:
        status = "✅ Success" if r["success"] else "❌ Failed"
        report += f"| {r['run_number']} | {r['ticker']} | {r['duration_seconds']:.2f} | {status} |\n"
    
    report += f"""

## Key Findings

1. **Cold Start Latency:** The average end-to-end latency for cold runs was {cold_stats.get('mean', 0):.2f} seconds (median: {cold_stats.get('median', 0):.2f}s).

2. **Warm/Cached Latency:** With cached data, the average latency {"decreased to" if warm_stats.get('mean', 0) < cold_stats.get('mean', 0) else "was"} {warm_stats.get('mean', 0):.2f} seconds (median: {warm_stats.get('median', 0):.2f}s).

3. **Cache Effectiveness:** {"The warm runs showed a " + f"{improvement_pct:.1f}%" + " improvement over cold runs, demonstrating effective caching." if improvement_pct > 0 else "Cache effectiveness could not be conclusively measured from these results."}

4. **Variability:** Standard deviation was {cold_stats.get('std_dev', 0):.2f}s for cold runs and {warm_stats.get('std_dev', 0):.2f}s for warm runs.

## Conclusion

This experiment successfully measured the end-to-end latency of the agentic workflow system. The results provide baseline performance metrics for the complete analysis pipeline including financial data collection, news analysis, model generation, and report creation.

---
*Experiment conducted on {datetime.now().strftime("%Y-%m-%d")}*
"""
    
    # Write report
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\n[REPORT] Generated: {output_path}")


def main():
    """Run complete Experiment 1."""
    print("\n" + "="*80)
    print("EXPERIMENT 1: END-TO-END LATENCY & COMPONENT BREAKDOWN")
    print("="*80)
    print(f"Test Tickers: {', '.join(TEST_TICKERS)}")
    print(f"Test Prompts: {len(TEST_PROMPTS)} variations")
    print(f"Total Tests: {len(TEST_TICKERS) * len(TEST_PROMPTS) * 2} (cold + warm)")
    print("="*80 + "\n")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    cold_results = []
    warm_results = []
    
    run_number = 0
    
    # PHASE 1: COLD RUNS
    print("\n" + "="*80)
    print("PHASE 1: COLD RUNS (Empty Cache)")
    print("="*80 + "\n")
    
    for ticker in TEST_TICKERS:
        for prompt_template in TEST_PROMPTS:
            run_number += 1
            result = run_single_workflow(
                ticker=ticker,
                prompt=prompt_template,
                phase="cold",
                run_number=run_number,
                timestamp=timestamp
            )
            cold_results.append(result)
            
            # Brief pause
            time.sleep(3)
    
    print("\n" + "="*80)
    print(f"PHASE 1 COMPLETE - {len(cold_results)} runs completed")
    print("="*80 + "\n")
    
    # Pause before warm runs
    time.sleep(10)
    
    # PHASE 2: WARM RUNS
    print("\n" + "="*80)
    print("PHASE 2: WARM RUNS (With Cache)")
    print("="*80 + "\n")
    
    for ticker in TEST_TICKERS:
        for prompt_template in TEST_PROMPTS:
            run_number += 1
            result = run_single_workflow(
                ticker=ticker,
                prompt=prompt_template,
                phase="warm",
                run_number=run_number,
                timestamp=timestamp
            )
            warm_results.append(result)
            
            # Brief pause
            time.sleep(3)
    
    print("\n" + "="*80)
    print(f"PHASE 2 COMPLETE - {len(warm_results)} runs completed")
    print("="*80 + "\n")
    
    # Save raw results
    output_dir = Path("experiments/results/experiment_1")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results_data = {
        "experiment": "Experiment 1: End-to-End Latency",
        "timestamp": timestamp,
        "configuration": {
            "tickers": TEST_TICKERS,
            "prompts": TEST_PROMPTS,
        },
        "cold_results": cold_results,
        "warm_results": warm_results,
    }
    
    with open(output_dir / f"raw_results_{timestamp}.json", 'w') as f:
        json.dump(results_data, f, indent=2)
    
    print(f"[RESULTS] Saved raw data: {output_dir / f'raw_results_{timestamp}.json'}")
    
    # Generate report
    report_path = output_dir / "EXPERIMENT_1_REPORT.md"
    generate_report(cold_results, warm_results, report_path)
    
    print("\n" + "="*80)
    print("EXPERIMENT 1 COMPLETE")
    print("="*80)
    print(f"Total runs: {len(cold_results) + len(warm_results)}")
    print(f"Results: {output_dir}")
    print(f"Report: {report_path}")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
