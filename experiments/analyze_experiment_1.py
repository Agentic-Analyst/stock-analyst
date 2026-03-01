"""
Analyze Experiment 1 Results: End-to-End Latency & Component Breakdown

This script loads timing data from Experiment 1 runs and computes:
- Summary statistics (mean, median, std dev, percentiles) for each metric
- Comparison between cold and warm runs
- Per-component timing analysis
- Cache effectiveness metrics

Generates a markdown report with all findings.
"""

import sys
from pathlib import Path
import json
from typing import List, Dict, Tuple
import statistics

# Add experiments directory to path
sys.path.insert(0, str(Path(__file__).parent))

from timing_instrument import WorkflowTimings, format_duration


def load_results(results_dir: Path) -> Tuple[List[WorkflowTimings], List[WorkflowTimings]]:
    """
    Load cold and warm timing results from experiment directory.
    
    Returns:
        Tuple of (cold_results, warm_results)
    """
    cold_results = []
    warm_results = []
    
    for json_file in results_dir.glob("timing_*.json"):
        with open(json_file, 'r') as f:
            data = json.load(f)
        
        # Reconstruct WorkflowTimings
        timings = WorkflowTimings(
            ticker=data['ticker'],
            user_prompt=data['user_prompt'],
            session_id=data['session_id'],
            start_time=data['start_time'],
            end_time=data['end_time'],
            total_duration=data['total_duration'],
            financial_data_time=data.get('financial_data_time'),
            news_analysis_time=data.get('news_analysis_time'),
            model_generation_time=data.get('model_generation_time'),
            report_generation_time=data.get('report_generation_time'),
            cache_hit=data['cache_hit'],
            reuse_financial_data=data['reuse_financial_data'],
            reuse_news_data=data['reuse_news_data'],
            reuse_model=data['reuse_model'],
            total_iterations=data['total_iterations'],
            completion_status=data['completion_status'],
            error_message=data.get('error_message')
        )
        
        # Classify as cold or warm based on filename
        filename = json_file.name
        if "_cold_" in filename:
            cold_results.append(timings)
        elif "_warm_" in filename:
            warm_results.append(timings)
    
    return cold_results, warm_results


def compute_statistics(values: List[float]) -> Dict[str, float]:
    """
    Compute summary statistics for a list of values.
    
    Returns:
        Dictionary with mean, median, std_dev, min, max, p25, p75, p95
    """
    if not values:
        return {
            "count": 0,
            "mean": 0,
            "median": 0,
            "std_dev": 0,
            "min": 0,
            "max": 0,
            "p25": 0,
            "p75": 0,
            "p95": 0
        }
    
    sorted_values = sorted(values)
    n = len(sorted_values)
    
    return {
        "count": n,
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "std_dev": statistics.stdev(values) if n > 1 else 0,
        "min": min(values),
        "max": max(values),
        "p25": sorted_values[int(n * 0.25)],
        "p75": sorted_values[int(n * 0.75)],
        "p95": sorted_values[int(n * 0.95)] if n > 1 else sorted_values[0]
    }


def analyze_timing_results(results: List[WorkflowTimings], phase_name: str) -> Dict:
    """
    Analyze timing results for a phase (cold or warm).
    
    Returns:
        Dictionary with analysis results
    """
    # Filter successful runs
    successful = [r for r in results if r.completion_status == "completed"]
    
    if not successful:
        return {
            "phase": phase_name,
            "total_runs": len(results),
            "successful_runs": 0,
            "failed_runs": len(results),
            "message": "No successful runs to analyze"
        }
    
    # Extract timing metrics
    e2e_times = [r.total_duration for r in successful if r.total_duration]
    financial_times = [r.financial_data_time for r in successful if r.financial_data_time]
    news_times = [r.news_analysis_time for r in successful if r.news_analysis_time]
    model_times = [r.model_generation_time for r in successful if r.model_generation_time]
    report_times = [r.report_generation_time for r in successful if r.report_generation_time]
    
    # Cache metrics
    cache_hits = sum(1 for r in successful if r.cache_hit)
    financial_reuse = sum(1 for r in successful if r.reuse_financial_data)
    news_reuse = sum(1 for r in successful if r.reuse_news_data)
    model_reuse = sum(1 for r in successful if r.reuse_model)
    
    return {
        "phase": phase_name,
        "total_runs": len(results),
        "successful_runs": len(successful),
        "failed_runs": len(results) - len(successful),
        "success_rate": len(successful) / len(results) * 100 if results else 0,
        
        "end_to_end": compute_statistics(e2e_times),
        "financial_data_agent": compute_statistics(financial_times),
        "news_analysis_agent": compute_statistics(news_times),
        "model_generation_agent": compute_statistics(model_times),
        "report_generation_agent": compute_statistics(report_times),
        
        "cache_metrics": {
            "overall_cache_hit_rate": cache_hits / len(successful) * 100 if successful else 0,
            "financial_data_reuse_rate": financial_reuse / len(successful) * 100 if successful else 0,
            "news_data_reuse_rate": news_reuse / len(successful) * 100 if successful else 0,
            "model_reuse_rate": model_reuse / len(successful) * 100 if successful else 0
        }
    }


def generate_markdown_report(cold_analysis: Dict, warm_analysis: Dict, output_file: Path):
    """
    Generate a markdown report with experiment results.
    """
    report = []
    
    report.append("# Experiment 1: End-to-End Latency & Component Breakdown")
    report.append("")
    report.append("## Experiment Overview")
    report.append("")
    report.append("**Objective:** Measure end-to-end workflow latency and per-component execution times for VYNN AI's agentic analysis pipeline.")
    report.append("")
    report.append("**Test Design:**")
    report.append("- **Phase 1 (Cold):** Execute workflow with empty cache → measure cold start latency")
    report.append("- **Phase 2 (Warm):** Re-execute same queries → measure warm/cached latency")
    report.append("")
    report.append("**Metrics Collected:**")
    report.append("- `t_E2E`: End-to-end workflow duration (seconds)")
    report.append("- `t_financial`: Financial Data Agent execution time")
    report.append("- `t_news`: News Analysis Agent execution time")
    report.append("- `t_model`: Model Generation Agent execution time")
    report.append("- `t_report`: Report Generation Agent execution time")
    report.append("- Cache hit rates and component reuse rates")
    report.append("")
    
    report.append("---")
    report.append("")
    
    # Cold Results
    report.append("## Phase 1: Cold Execution (No Cache)")
    report.append("")
    report.append(f"**Total Runs:** {cold_analysis['total_runs']}")
    report.append(f"**Successful:** {cold_analysis['successful_runs']}")
    report.append(f"**Failed:** {cold_analysis['failed_runs']}")
    report.append(f"**Success Rate:** {cold_analysis['success_rate']:.1f}%")
    report.append("")
    
    if cold_analysis['successful_runs'] > 0:
        report.append("### End-to-End Latency (t_E2E)")
        report.append("")
        e2e = cold_analysis['end_to_end']
        report.append("| Metric | Value |")
        report.append("|--------|-------|")
        report.append(f"| Mean | {format_duration(e2e['mean'])} |")
        report.append(f"| Median | {format_duration(e2e['median'])} |")
        report.append(f"| Std Dev | {format_duration(e2e['std_dev'])} |")
        report.append(f"| Min | {format_duration(e2e['min'])} |")
        report.append(f"| Max | {format_duration(e2e['max'])} |")
        report.append(f"| P25 | {format_duration(e2e['p25'])} |")
        report.append(f"| P75 | {format_duration(e2e['p75'])} |")
        report.append(f"| P95 | {format_duration(e2e['p95'])} |")
        report.append("")
        
        report.append("### Per-Component Timing")
        report.append("")
        report.append("| Component | Mean | Median | Std Dev | Min | Max |")
        report.append("|-----------|------|--------|---------|-----|-----|")
        
        for comp_name, comp_key in [
            ("Financial Data Agent", "financial_data_agent"),
            ("News Analysis Agent", "news_analysis_agent"),
            ("Model Generation Agent", "model_generation_agent"),
            ("Report Generation Agent", "report_generation_agent")
        ]:
            comp = cold_analysis[comp_key]
            if comp['count'] > 0:
                report.append(
                    f"| {comp_name} | {format_duration(comp['mean'])} | "
                    f"{format_duration(comp['median'])} | {format_duration(comp['std_dev'])} | "
                    f"{format_duration(comp['min'])} | {format_duration(comp['max'])} |"
                )
        report.append("")
    
    report.append("---")
    report.append("")
    
    # Warm Results
    report.append("## Phase 2: Warm Execution (With Cache)")
    report.append("")
    report.append(f"**Total Runs:** {warm_analysis['total_runs']}")
    report.append(f"**Successful:** {warm_analysis['successful_runs']}")
    report.append(f"**Failed:** {warm_analysis['failed_runs']}")
    report.append(f"**Success Rate:** {warm_analysis['success_rate']:.1f}%")
    report.append("")
    
    if warm_analysis['successful_runs'] > 0:
        report.append("### End-to-End Latency (t_E2E)")
        report.append("")
        e2e = warm_analysis['end_to_end']
        report.append("| Metric | Value |")
        report.append("|--------|-------|")
        report.append(f"| Mean | {format_duration(e2e['mean'])} |")
        report.append(f"| Median | {format_duration(e2e['median'])} |")
        report.append(f"| Std Dev | {format_duration(e2e['std_dev'])} |")
        report.append(f"| Min | {format_duration(e2e['min'])} |")
        report.append(f"| Max | {format_duration(e2e['max'])} |")
        report.append(f"| P25 | {format_duration(e2e['p25'])} |")
        report.append(f"| P75 | {format_duration(e2e['p75'])} |")
        report.append(f"| P95 | {format_duration(e2e['p95'])} |")
        report.append("")
        
        report.append("### Cache Effectiveness")
        report.append("")
        cache = warm_analysis['cache_metrics']
        report.append("| Metric | Rate |")
        report.append("|--------|------|")
        report.append(f"| Overall Cache Hit Rate | {cache['overall_cache_hit_rate']:.1f}% |")
        report.append(f"| Financial Data Reuse | {cache['financial_data_reuse_rate']:.1f}% |")
        report.append(f"| News Data Reuse | {cache['news_data_reuse_rate']:.1f}% |")
        report.append(f"| Model Reuse | {cache['model_reuse_rate']:.1f}% |")
        report.append("")
        
        report.append("### Per-Component Timing")
        report.append("")
        report.append("| Component | Mean | Median | Std Dev | Min | Max |")
        report.append("|-----------|------|--------|---------|-----|-----|")
        
        for comp_name, comp_key in [
            ("Financial Data Agent", "financial_data_agent"),
            ("News Analysis Agent", "news_analysis_agent"),
            ("Model Generation Agent", "model_generation_agent"),
            ("Report Generation Agent", "report_generation_agent")
        ]:
            comp = warm_analysis[comp_key]
            if comp['count'] > 0:
                report.append(
                    f"| {comp_name} | {format_duration(comp['mean'])} | "
                    f"{format_duration(comp['median'])} | {format_duration(comp['std_dev'])} | "
                    f"{format_duration(comp['min'])} | {format_duration(comp['max'])} |"
                )
        report.append("")
    
    report.append("---")
    report.append("")
    
    # Comparison
    if cold_analysis['successful_runs'] > 0 and warm_analysis['successful_runs'] > 0:
        report.append("## Cold vs Warm Comparison")
        report.append("")
        
        cold_e2e = cold_analysis['end_to_end']['mean']
        warm_e2e = warm_analysis['end_to_end']['mean']
        improvement = ((cold_e2e - warm_e2e) / cold_e2e) * 100 if cold_e2e > 0 else 0
        
        report.append("### End-to-End Latency Reduction")
        report.append("")
        report.append("| Metric | Cold | Warm | Improvement |")
        report.append("|--------|------|------|-------------|")
        report.append(f"| Mean | {format_duration(cold_e2e)} | {format_duration(warm_e2e)} | {improvement:.1f}% |")
        report.append("")
        
        report.append("### Component-wise Comparison (Mean Duration)")
        report.append("")
        report.append("| Component | Cold | Warm | Improvement |")
        report.append("|-----------|------|------|-------------|")
        
        for comp_name, comp_key in [
            ("Financial Data", "financial_data_agent"),
            ("News Analysis", "news_analysis_agent"),
            ("Model Generation", "model_generation_agent"),
            ("Report Generation", "report_generation_agent")
        ]:
            cold_comp = cold_analysis[comp_key]
            warm_comp = warm_analysis[comp_key]
            
            if cold_comp['count'] > 0 and warm_comp['count'] > 0:
                cold_mean = cold_comp['mean']
                warm_mean = warm_comp['mean']
                comp_improvement = ((cold_mean - warm_mean) / cold_mean) * 100 if cold_mean > 0 else 0
                
                report.append(
                    f"| {comp_name} | {format_duration(cold_mean)} | "
                    f"{format_duration(warm_mean)} | {comp_improvement:.1f}% |"
                )
        report.append("")
    
    report.append("---")
    report.append("")
    report.append("## Conclusions")
    report.append("")
    report.append("**Key Findings:**")
    report.append("")
    
    if cold_analysis['successful_runs'] > 0:
        report.append(f"1. **Cold Start Performance:** Mean end-to-end latency = {format_duration(cold_analysis['end_to_end']['mean'])}")
    
    if warm_analysis['successful_runs'] > 0:
        report.append(f"2. **Warm Performance:** Mean end-to-end latency = {format_duration(warm_analysis['end_to_end']['mean'])}")
        cache = warm_analysis['cache_metrics']
        report.append(f"3. **Cache Effectiveness:** {cache['overall_cache_hit_rate']:.1f}% overall cache hit rate")
    
    if cold_analysis['successful_runs'] > 0 and warm_analysis['successful_runs'] > 0:
        improvement = ((cold_analysis['end_to_end']['mean'] - warm_analysis['end_to_end']['mean']) / cold_analysis['end_to_end']['mean']) * 100
        report.append(f"4. **Latency Reduction:** {improvement:.1f}% faster with caching enabled")
    
    report.append("")
    report.append("---")
    report.append("")
    report.append(f"*Report generated: {Path(output_file).name}*")
    
    # Write report
    with open(output_file, 'w') as f:
        f.write('\n'.join(report))
    
    print(f"\n✅ Report generated: {output_file}")


def main():
    """Main analysis function."""
    results_dir = Path("experiments/results/experiment_1")
    
    if not results_dir.exists():
        print(f"❌ Results directory not found: {results_dir}")
        print("Run run_experiment_1.py first to generate timing data.")
        return
    
    print("\n" + "="*80)
    print("ANALYZING EXPERIMENT 1 RESULTS")
    print("="*80 + "\n")
    
    # Load results
    print(f"Loading results from: {results_dir}")
    cold_results, warm_results = load_results(results_dir)
    
    print(f"Loaded {len(cold_results)} cold runs")
    print(f"Loaded {len(warm_results)} warm runs")
    print()
    
    # Analyze phases
    print("Analyzing cold execution...")
    cold_analysis = analyze_timing_results(cold_results, "Cold (No Cache)")
    
    print("Analyzing warm execution...")
    warm_analysis = analyze_timing_results(warm_results, "Warm (With Cache)")
    
    # Generate report
    print("\nGenerating markdown report...")
    report_file = results_dir / "EXPERIMENT_1_REPORT.md"
    generate_markdown_report(cold_analysis, warm_analysis, report_file)
    
    # Save raw analysis data
    analysis_file = results_dir / "analysis_data.json"
    with open(analysis_file, 'w') as f:
        json.dump({
            "cold": cold_analysis,
            "warm": warm_analysis
        }, f, indent=2)
    print(f"✅ Analysis data saved: {analysis_file}")
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
