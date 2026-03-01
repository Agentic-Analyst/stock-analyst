"""
Experiment 3 Part 1: Reproducibility Testing

Tests whether running the same analysis multiple times produces consistent results.

Configuration:
- 3 tickers (NVDA, AAPL, MSFT)
- 5 runs per ticker
- Fixed prompt per ticker
- Total: 15 runs

Measures:
- Completion status consistency
- Execution time variance
- Output artifact consistency
"""

import subprocess
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import statistics


# Test configuration
TEST_TICKERS = ["NVDA", "AAPL", "MSFT"]
RUNS_PER_TICKER = 3  # Minimal but meaningful sample size
PROMPT_TEMPLATE = "Analyze {ticker} stock and provide investment recommendation"


def run_single_analysis(ticker: str, run_number: int, total_run: int, timestamp: str) -> Dict:
    """Run a single analysis and capture metrics."""
    
    prompt = PROMPT_TEMPLATE.format(ticker=ticker)
    
    print(f"\n{'='*80}")
    print(f"[EXPERIMENT 3.1] Run #{total_run} | Ticker: {ticker} | Repetition: {run_number}/{RUNS_PER_TICKER}")
    print(f"[EXPERIMENT 3.1] Prompt: {prompt}")
    print(f"{'='*80}\n")
    
    start_time = time.monotonic()
    
    # Unique timestamp for this run
    run_timestamp = f"{timestamp}_repro_{ticker}_{run_number}"
    
    cmd = [
        "conda", "run", "-n", "stock-analyst",
        "python", "main.py",
        "--pipeline", "chat",
        "--email", "experiment3@vynnai.com",
        "--user-prompt", prompt,
        "--timestamp", run_timestamp
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout
            cwd="/Users/zanwenfu/IdeaProject/stock-analyst"
        )
        
        end_time = time.monotonic()
        duration = end_time - start_time
        
        success = result.returncode == 0
        
        # Check if output directory was created
        data_dir = Path(f"data/experiment3@vynnai.com/{ticker}/{run_timestamp}")
        output_exists = data_dir.exists() if data_dir else False
        
        # Count output files if directory exists
        file_count = 0
        if output_exists:
            file_count = sum(1 for _ in data_dir.rglob('*') if _.is_file())
        
        # Check for specific output types
        has_financials = (data_dir / "financials").exists() if output_exists else False
        has_reports = (data_dir / "reports").exists() if output_exists else False
        has_news = (data_dir / "searched").exists() if output_exists else False
        has_log = (data_dir / "info.log").exists() if output_exists else False
        
        # Extract completion status from output
        completion_status = "unknown"
        if result.stdout:
            if "WORKFLOW COMPLETE" in result.stdout or "PROGRAM IS COMPLETED" in result.stdout:
                completion_status = "completed"
            elif "ERROR" in result.stdout or "FAILED" in result.stdout:
                completion_status = "error"
        
        run_data = {
            "ticker": ticker,
            "run_number": run_number,
            "total_run_number": total_run,
            "prompt": prompt,
            "timestamp": run_timestamp,
            "duration_seconds": duration,
            "success": success,
            "return_code": result.returncode,
            "completion_status": completion_status,
            "output": {
                "directory_exists": output_exists,
                "file_count": file_count,
                "has_financials": has_financials,
                "has_reports": has_reports,
                "has_news": has_news,
                "has_log": has_log,
            }
        }
        
        # Save logs
        output_dir = Path("experiments/results/experiment_3/reproducibility/logs")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_dir / f"stdout_{ticker}_{run_number}.log", 'w') as f:
            f.write(result.stdout)
        with open(output_dir / f"stderr_{ticker}_{run_number}.log", 'w') as f:
            f.write(result.stderr)
        
        print(f"\n[EXPERIMENT 3.1] ✅ Completed")
        print(f"  Duration: {duration:.2f}s")
        print(f"  Success: {success}")
        print(f"  Status: {completion_status}")
        print(f"  Output Files: {file_count}")
        
        return run_data
        
    except subprocess.TimeoutExpired:
        end_time = time.monotonic()
        duration = end_time - start_time
        
        print(f"\n[EXPERIMENT 3.1] ⏱️ Timeout after {duration:.2f}s")
        
        return {
            "ticker": ticker,
            "run_number": run_number,
            "total_run_number": total_run,
            "prompt": prompt,
            "timestamp": run_timestamp,
            "duration_seconds": duration,
            "success": False,
            "completion_status": "timeout",
            "output": {
                "directory_exists": False,
                "file_count": 0,
            }
        }
        
    except Exception as e:
        end_time = time.monotonic()
        duration = end_time - start_time
        
        print(f"\n[EXPERIMENT 3.1] ❌ Error: {e}")
        
        return {
            "ticker": ticker,
            "run_number": run_number,
            "total_run_number": total_run,
            "prompt": prompt,
            "timestamp": run_timestamp,
            "duration_seconds": duration,
            "success": False,
            "completion_status": "error",
            "error": str(e),
            "output": {
                "directory_exists": False,
                "file_count": 0,
            }
        }


def compute_reproducibility_metrics(ticker_results: List[Dict]) -> Dict:
    """Compute reproducibility metrics for a ticker."""
    
    if not ticker_results:
        return {}
    
    # Success rate
    successful_runs = [r for r in ticker_results if r.get("success", False)]
    success_rate = len(successful_runs) / len(ticker_results)
    
    # Execution time statistics
    durations = [r["duration_seconds"] for r in ticker_results if r.get("success")]
    
    time_stats = {}
    if durations:
        mean_time = statistics.mean(durations)
        time_stats = {
            "mean": mean_time,
            "median": statistics.median(durations),
            "std_dev": statistics.stdev(durations) if len(durations) > 1 else 0.0,
            "min": min(durations),
            "max": max(durations),
            "cv": statistics.stdev(durations) / mean_time if len(durations) > 1 and mean_time > 0 else 0.0,
        }
    
    # Output consistency
    output_exists_count = sum(1 for r in ticker_results if r.get("output", {}).get("directory_exists", False))
    output_consistency = output_exists_count / len(ticker_results)
    
    # File count consistency
    file_counts = [r.get("output", {}).get("file_count", 0) for r in ticker_results if r.get("success")]
    file_count_stats = {}
    if file_counts:
        file_count_stats = {
            "mean": statistics.mean(file_counts),
            "min": min(file_counts),
            "max": max(file_counts),
            "variance": statistics.variance(file_counts) if len(file_counts) > 1 else 0.0,
        }
    
    # Reproducibility score
    cv_penalty = 1 - min(time_stats.get("cv", 0), 1.0)  # Lower CV is better
    reproducibility_score = success_rate * cv_penalty * output_consistency
    
    return {
        "ticker": ticker_results[0]["ticker"],
        "total_runs": len(ticker_results),
        "successful_runs": len(successful_runs),
        "success_rate": success_rate,
        "time_statistics": time_stats,
        "output_consistency": output_consistency,
        "file_count_statistics": file_count_stats,
        "reproducibility_score": reproducibility_score,
    }


def main():
    """Run reproducibility experiment."""
    
    print("\n" + "="*80)
    print("EXPERIMENT 3 PART 1: REPRODUCIBILITY TESTING")
    print("="*80)
    print(f"Tickers: {', '.join(TEST_TICKERS)}")
    print(f"Runs per ticker: {RUNS_PER_TICKER}")
    print(f"Total runs: {len(TEST_TICKERS) * RUNS_PER_TICKER}")
    print("="*80 + "\n")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    all_results = []
    ticker_grouped_results = {ticker: [] for ticker in TEST_TICKERS}
    
    total_run = 0
    
    for ticker in TEST_TICKERS:
        print(f"\n{'='*80}")
        print(f"TESTING TICKER: {ticker}")
        print(f"{'='*80}\n")
        
        for run_num in range(1, RUNS_PER_TICKER + 1):
            total_run += 1
            
            result = run_single_analysis(
                ticker=ticker,
                run_number=run_num,
                total_run=total_run,
                timestamp=timestamp
            )
            
            all_results.append(result)
            ticker_grouped_results[ticker].append(result)
            
            # Save individual result
            output_dir = Path("experiments/results/experiment_3/reproducibility")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            with open(output_dir / f"run_{ticker}_{run_num}_{timestamp}.json", 'w') as f:
                json.dump(result, f, indent=2)
            
            # Brief pause between runs
            if run_num < RUNS_PER_TICKER:
                print(f"\n[PAUSE] Waiting 5 seconds before next run...")
                time.sleep(5)
        
        print(f"\n{'='*80}")
        print(f"COMPLETED ALL RUNS FOR {ticker}")
        print(f"{'='*80}\n")
        
        # Longer pause between tickers
        if ticker != TEST_TICKERS[-1]:
            print(f"\n[PAUSE] Waiting 10 seconds before next ticker...")
            time.sleep(10)
    
    # Compute metrics per ticker
    metrics_by_ticker = {}
    for ticker in TEST_TICKERS:
        metrics = compute_reproducibility_metrics(ticker_grouped_results[ticker])
        metrics_by_ticker[ticker] = metrics
    
    # Compute overall metrics
    all_successful = [r for r in all_results if r.get("success", False)]
    overall_success_rate = len(all_successful) / len(all_results) if all_results else 0
    
    all_durations = [r["duration_seconds"] for r in all_successful]
    overall_time_stats = {}
    if all_durations:
        mean_time = statistics.mean(all_durations)
        overall_time_stats = {
            "mean": mean_time,
            "median": statistics.median(all_durations),
            "std_dev": statistics.stdev(all_durations) if len(all_durations) > 1 else 0.0,
            "cv": statistics.stdev(all_durations) / mean_time if len(all_durations) > 1 and mean_time > 0 else 0.0,
        }
    
    # Save summary
    summary = {
        "experiment": "Experiment 3 Part 1: Reproducibility",
        "timestamp": timestamp,
        "configuration": {
            "tickers": TEST_TICKERS,
            "runs_per_ticker": RUNS_PER_TICKER,
            "total_runs": len(all_results),
        },
        "overall": {
            "total_runs": len(all_results),
            "successful_runs": len(all_successful),
            "success_rate": overall_success_rate,
            "time_statistics": overall_time_stats,
        },
        "by_ticker": metrics_by_ticker,
        "all_results": all_results,
    }
    
    output_dir = Path("experiments/results/experiment_3")
    with open(output_dir / f"reproducibility_summary_{timestamp}.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    print("\n" + "="*80)
    print("EXPERIMENT 3.1 COMPLETE")
    print("="*80)
    print(f"Total runs: {len(all_results)}")
    print(f"Successful: {len(all_successful)} ({overall_success_rate*100:.1f}%)")
    print(f"Overall CV: {overall_time_stats.get('cv', 0):.3f}")
    print(f"\nResults: {output_dir}")
    print(f"Summary: reproducibility_summary_{timestamp}.json")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
