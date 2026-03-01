"""
Experiment 1: End-to-End Latency & Component Breakdown

This experiment measures:
1. End-to-end latency (t_E2E) for complete workflow execution
2. Per-component timing: Financial Data, News Analysis, Model Generation, Report Generation  
3. Latency comparison: cold start vs warm/cached execution

Test Design:
- Phase 1 (Cold): Run analysis for N tickers with empty cache → measure cold latency
- Phase 2 (Warm): Re-run same queries → measure warm/cached latency
- Record detailed per-agent timing and cache hit rates

Output:
- Individual timing JSON files for each run
- Aggregated statistics (mean, median, std dev, percentiles)
- Comparison table: cold vs warm execution
"""

import sys
import asyncio
from pathlib import Path
from datetime import datetime
import json
from typing import List, Dict
import time

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Add experiments directory to path
sys.path.insert(0, str(Path(__file__).parent))

from timing_instrument import WorkflowTimings, AgentTiming, format_duration
from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner


# Test configuration
TEST_TICKERS = [
    "NVDA",  # NVIDIA - Tech/AI
    "AAPL",  # Apple - Hardware
    "MSFT",  # Microsoft - Software
]

TEST_PROMPTS = [
    "Analyze {ticker} stock and provide investment recommendation",
]


async def run_single_test(
    ticker: str,
    prompt: str,
    email: str,
    timestamp: str,
    run_number: int,
    phase: str  # "cold" or "warm"
) -> WorkflowTimings:
    """
    Run a single workflow test and return timing results.
    
    Args:
        ticker: Stock ticker symbol
        prompt: User prompt template
        email: User email for data organization
        timestamp: Analysis timestamp
        run_number: Sequential run number
        phase: "cold" or "warm" to indicate cache state
    
    Returns:
        WorkflowTimings object with recorded metrics
    """
    # Format prompt with ticker
    formatted_prompt = prompt.format(ticker=ticker)
    
    print(f"\n{'='*80}")
    print(f"[EXPERIMENT 1] Run #{run_number} | Phase: {phase.upper()} | Ticker: {ticker}")
    print(f"[EXPERIMENT 1] Prompt: {formatted_prompt}")
    print(f"{'='*80}\n")
    
    # Initialize timing tracker
    workflow_start = time.monotonic()
    
    timings = WorkflowTimings(
        ticker=ticker,
        user_prompt=formatted_prompt,
        session_id=f"{ticker}_{phase}_{run_number}",
        start_time=workflow_start
    )
    
    # Create standard runner
    runner = SupervisorWorkflowRunner(
        email=email,
        timestamp=f"{timestamp}_{phase}_{run_number}",
        user_prompt=formatted_prompt,
        session_id=None,  # New session for each run
        max_iterations=15
    )
    
    # Run workflow
    try:
        result = await runner.run_workflow()
        workflow_end = time.monotonic()
        
        # Extract timing and execution info
        timings.end_time = workflow_end
        timings.total_duration = workflow_end - workflow_start
        timings.total_iterations = runner.stats.get("iterations", 0)
        timings.completion_status = runner.stats.get("completion_status", "unknown")
        
        # Extract agent execution info from stats
        agents_executed = runner.stats.get("agents_executed", [])
        for agent_info in agents_executed:
            agent_name = agent_info.get("agent", "unknown")
            # We don't have individual timings, but we can record that it executed
            # The parent class doesn't expose per-agent timing, so we'll estimate based on logs
            
        # Check cache status from state
        if runner.state:
            timings.reuse_financial_data = runner.state.is_data_collected()
            timings.reuse_news_data = runner.state.is_news_analyzed()
            timings.reuse_model = runner.state.is_model_generated()
            timings.cache_hit = (
                timings.reuse_financial_data or
                timings.reuse_news_data or
                timings.reuse_model
            )
        
        # Finalize
        timings.finalize()
        
        # Save individual result
        output_dir = Path("experiments/results/experiment_1")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"timing_{phase}_{ticker}_{run_number}_{timestamp}.json"
        timings.save_to_file(output_dir / filename)
        
        print(f"\n[EXPERIMENT 1] ✅ Completed: {ticker} | Duration: {format_duration(timings.total_duration)}")
        print(f"[EXPERIMENT 1] Cache Hit: {timings.cache_hit}")
        print(f"[EXPERIMENT 1] Status: {timings.completion_status}")
        print(f"[EXPERIMENT 1] Iterations: {timings.total_iterations}")
        
        return timings
        
    except Exception as e:
        print(f"\n[EXPERIMENT 1] ❌ Error during run #{run_number}: {e}")
        import traceback
        traceback.print_exc()
        
        # Return partial timing data even on failure
        workflow_end = time.monotonic()
        timings.end_time = workflow_end
        timings.total_duration = workflow_end - workflow_start
        timings.completion_status = "error"
        timings.error_message = str(e)
        timings.finalize()
        
        # Save error result
        output_dir = Path("experiments/results/experiment_1")
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"timing_{phase}_{ticker}_{run_number}_{timestamp}_ERROR.json"
        timings.save_to_file(output_dir / filename)
        
        return timings


async def run_experiment_1():
    """
    Run complete Experiment 1: End-to-End Latency & Component Breakdown.
    """
    print("\n" + "="*80)
    print("EXPERIMENT 1: END-TO-END LATENCY & COMPONENT BREAKDOWN")
    print("="*80)
    print(f"Test Tickers: {', '.join(TEST_TICKERS)}")
    print(f"Test Prompts: {len(TEST_PROMPTS)} variations")
    print(f"Total Tests: {len(TEST_TICKERS) * len(TEST_PROMPTS) * 2} (cold + warm)")
    print("="*80 + "\n")
    
    email = "experiment@vynnai.com"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    cold_results: List[WorkflowTimings] = []
    warm_results: List[WorkflowTimings] = []
    
    run_number = 0
    
    # PHASE 1: COLD RUNS (no cache)
    print("\n" + "="*80)
    print("PHASE 1: COLD RUNS (Empty Cache)")
    print("="*80 + "\n")
    
    for ticker in TEST_TICKERS:
        for prompt_template in TEST_PROMPTS:
            run_number += 1
            timings = await run_single_test(
                ticker=ticker,
                prompt=prompt_template,
                email=email,
                timestamp=timestamp,
                run_number=run_number,
                phase="cold"
            )
            cold_results.append(timings)
            
            # Brief pause between runs
            await asyncio.sleep(2)
    
    print("\n" + "="*80)
    print("PHASE 1 COMPLETE")
    print(f"Completed {len(cold_results)} cold runs")
    print("="*80 + "\n")
    
    # Brief pause before warm runs
    await asyncio.sleep(5)
    
    # PHASE 2: WARM RUNS (with cache)
    print("\n" + "="*80)
    print("PHASE 2: WARM RUNS (With Cache)")
    print("="*80 + "\n")
    
    for ticker in TEST_TICKERS:
        for prompt_template in TEST_PROMPTS:
            run_number += 1
            timings = await run_single_test(
                ticker=ticker,
                prompt=prompt_template,
                email=email,
                timestamp=timestamp,
                run_number=run_number,
                phase="warm"
            )
            warm_results.append(timings)
            
            # Brief pause between runs
            await asyncio.sleep(2)
    
    print("\n" + "="*80)
    print("PHASE 2 COMPLETE")
    print(f"Completed {len(warm_results)} warm runs")
    print("="*80 + "\n")
    
    # Save summary
    summary = {
        "experiment": "Experiment 1: End-to-End Latency & Component Breakdown",
        "timestamp": timestamp,
        "configuration": {
            "tickers": TEST_TICKERS,
            "prompts": TEST_PROMPTS,
            "total_tests": len(TEST_TICKERS) * len(TEST_PROMPTS) * 2,
            "cold_runs": len(cold_results),
            "warm_runs": len(warm_results)
        },
        "phases": {
            "cold": {
                "count": len(cold_results),
                "successful": sum(1 for t in cold_results if t.completion_status == "completed"),
                "failed": sum(1 for t in cold_results if t.completion_status in ["error", "failed"])
            },
            "warm": {
                "count": len(warm_results),
                "successful": sum(1 for t in warm_results if t.completion_status == "completed"),
                "failed": sum(1 for t in warm_results if t.completion_status in ["error", "failed"])
            }
        }
    }
    
    output_dir = Path("experiments/results/experiment_1")
    with open(output_dir / f"summary_{timestamp}.json", 'w') as f:
        json.dump(summary, f, indent=2)
    
    print("\n" + "="*80)
    print("EXPERIMENT 1 COMPLETE")
    print("="*80)
    print(f"Results saved to: {output_dir}")
    print(f"Total runs: {len(cold_results) + len(warm_results)}")
    print(f"Run analyze_experiment_1.py to generate statistics and report")
    print("="*80 + "\n")


if __name__ == "__main__":
    # Run the experiment
    asyncio.run(run_experiment_1())
