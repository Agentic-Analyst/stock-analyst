"""
Experiment 3 Part 2: Stability Testing (Prompt Paraphrasing)

Tests robustness to natural language variations in user prompts.

Configuration:
- 1 ticker (NVDA)
- 4 semantically equivalent prompt variations
- Total: 4 runs

Measures:
- Intent recognition consistency
- Workflow path consistency
- Execution time variance across prompts
"""

import subprocess
import time
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import statistics


# Test configuration
TEST_TICKER = "NVDA"

PROMPT_VARIATIONS = [
    "Analyze NVDA stock and provide investment recommendation",
    "Give me a comprehensive analysis of NVIDIA stock",
    "What's your investment recommendation for NVDA?",
]  # 3 variations for minimal testing


def run_single_analysis(ticker: str, prompt: str, prompt_number: int, timestamp: str) -> Dict:
    """Run a single analysis with a specific prompt variation."""
    
    print(f"\n{'='*80}")
    print(f"[EXPERIMENT 3.2] Run #{prompt_number} | Ticker: {ticker}")
    print(f"[EXPERIMENT 3.2] Prompt Variation {prompt_number}: {prompt}")
    print(f"{'='*80}\n")
    
    start_time = time.monotonic()
    
    # Unique timestamp for this run
    run_timestamp = f"{timestamp}_stable_{ticker}_p{prompt_number}"
    
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
        has_screened = (data_dir / "screened").exists() if output_exists else False
        
        # Extract completion status and workflow info from output
        completion_status = "unknown"
        workflow_info = {
            "recognized_ticker": None,
            "agents_mentioned": [],
        }
        
        if result.stdout:
            if "WORKFLOW COMPLETE" in result.stdout or "PROGRAM IS COMPLETED" in result.stdout:
                completion_status = "completed"
            elif "ERROR" in result.stdout or "FAILED" in result.stdout:
                completion_status = "error"
            
            # Extract ticker recognition
            if "NVDA" in result.stdout or "NVIDIA" in result.stdout:
                workflow_info["recognized_ticker"] = "NVDA"
            
            # Check which agents were mentioned
            agents = ["financial_data_agent", "news_analysis_agent", "model_generation_agent", "report_generator_agent"]
            for agent in agents:
                if agent in result.stdout:
                    workflow_info["agents_mentioned"].append(agent)
        
        run_data = {
            "ticker": ticker,
            "prompt": prompt,
            "prompt_number": prompt_number,
            "timestamp": run_timestamp,
            "duration_seconds": duration,
            "success": success,
            "return_code": result.returncode,
            "completion_status": completion_status,
            "workflow": workflow_info,
            "output": {
                "directory_exists": output_exists,
                "file_count": file_count,
                "has_financials": has_financials,
                "has_reports": has_reports,
                "has_news": has_news,
                "has_screened": has_screened,
            }
        }
        
        # Save logs
        output_dir = Path("experiments/results/experiment_3/stability/logs")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_dir / f"stdout_prompt{prompt_number}.log", 'w') as f:
            f.write(result.stdout)
        with open(output_dir / f"stderr_prompt{prompt_number}.log", 'w') as f:
            f.write(result.stderr)
        
        print(f"\n[EXPERIMENT 3.2] ✅ Completed")
        print(f"  Duration: {duration:.2f}s")
        print(f"  Success: {success}")
        print(f"  Status: {completion_status}")
        print(f"  Ticker Recognized: {workflow_info['recognized_ticker']}")
        print(f"  Agents: {len(workflow_info['agents_mentioned'])}")
        
        return run_data
        
    except subprocess.TimeoutExpired:
        end_time = time.monotonic()
        duration = end_time - start_time
        
        print(f"\n[EXPERIMENT 3.2] ⏱️ Timeout after {duration:.2f}s")
        
        return {
            "ticker": ticker,
            "prompt": prompt,
            "prompt_number": prompt_number,
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
        
        print(f"\n[EXPERIMENT 3.2] ❌ Error: {e}")
        
        return {
            "ticker": ticker,
            "prompt": prompt,
            "prompt_number": prompt_number,
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


def compute_stability_metrics(results: List[Dict]) -> Dict:
    """Compute stability metrics across prompt variations."""
    
    if not results:
        return {}
    
    # Intent recognition (ticker correctly identified)
    recognized_count = sum(1 for r in results if r.get("workflow", {}).get("recognized_ticker") == TEST_TICKER)
    intent_recognition_rate = recognized_count / len(results)
    
    # Success rate
    successful_runs = [r for r in results if r.get("success", False)]
    success_rate = len(successful_runs) / len(results)
    
    # Execution time variance
    durations = [r["duration_seconds"] for r in results if r.get("success")]
    time_stats = {}
    if durations:
        mean_time = statistics.mean(durations)
        time_stats = {
            "mean": mean_time,
            "median": statistics.median(durations),
            "std_dev": statistics.stdev(durations) if len(durations) > 1 else 0.0,
            "min": min(durations),
            "max": max(durations),
            "range": max(durations) - min(durations) if durations else 0,
            "cv": statistics.stdev(durations) / mean_time if len(durations) > 1 and mean_time > 0 else 0.0,
        }
    
    # Workflow consistency (same agents executed)
    agent_sets = [set(r.get("workflow", {}).get("agents_mentioned", [])) for r in results if r.get("success")]
    workflow_consistency = 0.0
    if agent_sets:
        # Check if all sets are identical
        first_set = agent_sets[0]
        all_same = all(s == first_set for s in agent_sets)
        workflow_consistency = 1.0 if all_same else 0.0
        
        # If not all same, compute Jaccard similarity
        if not all_same and len(agent_sets) > 1:
            similarities = []
            for i in range(len(agent_sets)):
                for j in range(i + 1, len(agent_sets)):
                    union = agent_sets[i] | agent_sets[j]
                    intersection = agent_sets[i] & agent_sets[j]
                    if union:
                        similarities.append(len(intersection) / len(union))
            workflow_consistency = statistics.mean(similarities) if similarities else 0.0
    
    # Output consistency
    output_exists_count = sum(1 for r in results if r.get("output", {}).get("directory_exists", False))
    output_consistency = output_exists_count / len(results)
    
    # Stability score
    cv_penalty = 1 - min(time_stats.get("cv", 0), 1.0)
    stability_score = intent_recognition_rate * cv_penalty * workflow_consistency * success_rate
    
    return {
        "total_runs": len(results),
        "successful_runs": len(successful_runs),
        "success_rate": success_rate,
        "intent_recognition_rate": intent_recognition_rate,
        "time_statistics": time_stats,
        "workflow_consistency": workflow_consistency,
        "output_consistency": output_consistency,
        "stability_score": stability_score,
    }


def main():
    """Run stability experiment."""
    
    print("\n" + "="*80)
    print("EXPERIMENT 3 PART 2: STABILITY TESTING (PROMPT PARAPHRASING)")
    print("="*80)
    print(f"Ticker: {TEST_TICKER}")
    print(f"Prompt variations: {len(PROMPT_VARIATIONS)}")
    print("="*80 + "\n")
    
    print("Prompt Variations:")
    for i, prompt in enumerate(PROMPT_VARIATIONS, 1):
        print(f"  {i}. {prompt}")
    print()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    all_results = []
    
    for prompt_num, prompt in enumerate(PROMPT_VARIATIONS, 1):
        result = run_single_analysis(
            ticker=TEST_TICKER,
            prompt=prompt,
            prompt_number=prompt_num,
            timestamp=timestamp
        )
        
        all_results.append(result)
        
        # Save individual result
        output_dir = Path("experiments/results/experiment_3/stability")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with open(output_dir / f"run_{TEST_TICKER}_prompt{prompt_num}_{timestamp}.json", 'w') as f:
            json.dump(result, f, indent=2)
        
        # Brief pause between runs
        if prompt_num < len(PROMPT_VARIATIONS):
            print(f"\n[PAUSE] Waiting 5 seconds before next prompt variation...")
            time.sleep(5)
    
    # Compute metrics
    metrics = compute_stability_metrics(all_results)
    
    # Save summary
    summary = {
        "experiment": "Experiment 3 Part 2: Stability (Prompt Paraphrasing)",
        "timestamp": timestamp,
        "configuration": {
            "ticker": TEST_TICKER,
            "prompt_variations": PROMPT_VARIATIONS,
            "total_runs": len(all_results),
        },
        "metrics": metrics,
        "all_results": all_results,
    }
    
    output_dir = Path("experiments/results/experiment_3")
    with open(output_dir / f"stability_summary_{timestamp}.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    print("\n" + "="*80)
    print("EXPERIMENT 3.2 COMPLETE")
    print("="*80)
    print(f"Total runs: {len(all_results)}")
    print(f"Successful: {metrics.get('successful_runs', 0)} ({metrics.get('success_rate', 0)*100:.1f}%)")
    print(f"Intent recognition: {metrics.get('intent_recognition_rate', 0)*100:.1f}%")
    print(f"Workflow consistency: {metrics.get('workflow_consistency', 0)*100:.1f}%")
    print(f"CV: {metrics.get('time_statistics', {}).get('cv', 0):.3f}")
    print(f"Stability score: {metrics.get('stability_score', 0):.3f}")
    print(f"\nResults: {output_dir}")
    print(f"Summary: stability_summary_{timestamp}.json")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
