"""
Experiment 1 Demo: End-to-End Latency Measurement

This is a demonstration run with 1 ticker to show the experiment setup and generate a sample report.
For the full experiment, use run_experiment_1_standalone.py.
"""

import subprocess
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import statistics


def run_single_workflow(ticker: str, prompt: str, phase: str, run_number: int, timestamp: str) -> Dict:
    """Run a single workflow and measure timing."""
    formatted_prompt = prompt.format(ticker=ticker)
    
    print(f"\n{'='*80}")
    print(f"[EXPERIMENT 1 DEMO] Run #{run_number} | Phase: {phase.upper()} | Ticker: {ticker}")
    print(f"[EXPERIMENT 1 DEMO] Prompt: {formatted_prompt}")
    print(f"{'='*80}\n")
    
    start_time = time.monotonic()
    
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
            timeout=900,  # 15 minute timeout for full analysis
            cwd="/Users/zanwenfu/IdeaProject/stock-analyst"
        )
        
        end_time = time.monotonic()
        duration = end_time - start_time
        
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
        }
        
        # Extract completion status from output
        if result.stdout:
            if "WORKFLOW COMPLETE" in result.stdout:
                timing_data["completion_status"] = "completed"
            elif "ERROR" in result.stdout or "FAILED" in result.stdout:
                timing_data["completion_status"] = "error"
            else:
                timing_data["completion_status"] = "unknown"
            
            # Save stdout/stderr for debugging
            output_dir = Path("experiments/results/experiment_1/logs")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            with open(output_dir / f"stdout_{phase}_{ticker}_{run_number}.log", 'w') as f:
                f.write(result.stdout)
            with open(output_dir / f"stderr_{phase}_{ticker}_{run_number}.log", 'w') as f:
                f.write(result.stderr)
        
        print(f"\n[EXPERIMENT 1 DEMO] ✅ Completed | Duration: {duration:.2f}s | Success: {success}")
        
        return timing_data
        
    except subprocess.TimeoutExpired:
        end_time = time.monotonic()
        duration = end_time - start_time
        
        print(f"\n[EXPERIMENT 1 DEMO] ⏱️ Timeout after {duration:.2f}s")
        
        return {
            "ticker": ticker,
            "prompt": formatted_prompt,
            "phase": phase,
            "run_number": run_number,
            "duration_seconds": duration,
            "success": False,
            "completion_status": "timeout",
            "timestamp": timestamp,
        }
    except Exception as e:
        end_time = time.monotonic()
        duration = end_time - start_time
        
        print(f"\n[EXPERIMENT 1 DEMO] ❌ Error: {e}")
        
        return {
            "ticker": ticker,
            "prompt": formatted_prompt,
            "phase": phase,
            "run_number": run_number,
            "duration_seconds": duration,
            "success": False,
            "completion_status": "error",
            "error": str(e),
            "timestamp": timestamp,
        }


def generate_demo_report(cold_result: Dict, warm_result: Dict, output_path: Path):
    """Generate markdown report for demo run."""
    
    cold_duration = cold_result.get("duration_seconds", 0)
    warm_duration = warm_result.get("duration_seconds", 0)
    
    if cold_duration > 0 and warm_duration > 0:
        improvement_pct = ((cold_duration - warm_duration) / cold_duration) * 100
    else:
        improvement_pct = 0.0
    
    report = f"""# Experiment 1: End-to-End Latency & Component Breakdown (Demo)

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Experiment Overview

This is a demonstration run of Experiment 1, which measures the end-to-end latency of the agentic workflow system. The full experiment would test multiple tickers across cold and warm execution phases.

### Demo Configuration

- **Test Ticker:** {cold_result.get('ticker', 'N/A')}
- **Phases:** Cold Start + Warm/Cached
- **Total Test Runs:** 2 (1 cold + 1 warm)

### Methodology

**Phase 1 (Cold Run):** Execute workflow with empty cache to measure baseline latency when all components must fetch/compute fresh data.

**Phase 2 (Warm Run):** Re-run the same query to measure cached/warm execution latency when data can be reused.

## Results

### End-to-End Latency

| Metric | Cold Start | Warm/Cached | Improvement |
|--------|-----------|-------------|-------------|
| **Duration** | {cold_duration:.2f}s | {warm_duration:.2f}s | {improvement_pct:.1f}% |
| **Status** | {cold_result.get('completion_status', 'unknown')} | {warm_result.get('completion_status', 'unknown')} | - |

### Execution Details

#### Cold Run (Phase 1)

- **Ticker:** {cold_result.get('ticker', 'N/A')}
- **Duration:** {cold_duration:.2f} seconds
- **Success:** {"✅ Yes" if cold_result.get('success') else "❌ No"}
- **Status:** {cold_result.get('completion_status', 'unknown')}
- **Return Code:** {cold_result.get('return_code', 'N/A')}

#### Warm Run (Phase 2)

- **Ticker:** {warm_result.get('ticker', 'N/A')}
- **Duration:** {warm_duration:.2f} seconds
- **Success:** {"✅ Yes" if warm_result.get('success') else "❌ No"}
- **Status:** {warm_result.get('completion_status', 'unknown')}
- **Return Code:** {warm_result.get('return_code', 'N/A')}

## Key Findings (Demo)

1. **Cold Start Latency:** The end-to-end latency for a cold run was {cold_duration:.2f} seconds.

2. **Warm/Cached Latency:** With potentially cached data, the latency was {warm_duration:.2f} seconds.

3. **Cache Effectiveness:** {"The warm run showed a " + f"{improvement_pct:.1f}%" + " improvement, demonstrating cache effectiveness." if improvement_pct > 5 else "The difference between cold and warm runs was minimal (" + f"{improvement_pct:.1f}%" + "), suggesting limited cache benefit or that caching was not fully utilized."}

4. **System Performance:** The agentic workflow completed {"successfully" if cold_result.get('success') and warm_result.get('success') else "with issues"} in this demo run.

## Next Steps

For the full experiment:
- Test multiple tickers (NVDA, AAPL, MSFT, etc.)
- Multiple prompt variations per ticker
- Statistical analysis across N runs
- Per-component timing breakdown

Run the full experiment with:
```bash
python experiments/run_experiment_1_standalone.py
```

## Notes

This demo run provides a proof-of-concept for the experiment methodology. The full experiment would provide statistically significant results with mean, median, standard deviation, and percentile analysis across multiple test cases.

---
*Demo run conducted on {datetime.now().strftime("%Y-%m-%d")}*
"""
    
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\n[DEMO REPORT] Generated: {output_path}")


def main():
    """Run demo experiment with 1 ticker."""
    print("\n" + "="*80)
    print("EXPERIMENT 1 DEMO: END-TO-END LATENCY MEASUREMENT")
    print("="*80)
    print("Demo Configuration: 1 ticker × 2 phases (cold + warm)")
    print("="*80 + "\n")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ticker = "NVDA"
    prompt = "Analyze {ticker} stock and provide investment recommendation"
    
    # Phase 1: Cold Run
    print("\n" + "="*80)
    print("PHASE 1: COLD RUN")
    print("="*80 + "\n")
    
    cold_result = run_single_workflow(
        ticker=ticker,
        prompt=prompt,
        phase="cold",
        run_number=1,
        timestamp=timestamp
    )
    
    print("\n[DEMO] Phase 1 complete. Waiting 10 seconds before Phase 2...")
    time.sleep(10)
    
    # Phase 2: Warm Run
    print("\n" + "="*80)
    print("PHASE 2: WARM RUN (WITH CACHE)")
    print("="*80 + "\n")
    
    warm_result = run_single_workflow(
        ticker=ticker,
        prompt=prompt,
        phase="warm",
        run_number=2,
        timestamp=timestamp
    )
    
    # Save raw results
    output_dir = Path("experiments/results/experiment_1")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results_data = {
        "experiment": "Experiment 1 Demo: End-to-End Latency",
        "timestamp": timestamp,
        "demo": True,
        "cold_result": cold_result,
        "warm_result": warm_result,
    }
    
    with open(output_dir / f"demo_results_{timestamp}.json", 'w') as f:
        json.dump(results_data, f, indent=2)
    
    # Generate report
    report_path = output_dir / "EXPERIMENT_1_DEMO_REPORT.md"
    generate_demo_report(cold_result, warm_result, report_path)
    
    print("\n" + "="*80)
    print("EXPERIMENT 1 DEMO COMPLETE")
    print("="*80)
    print(f"Results: {output_dir}")
    print(f"Report: {report_path}")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
