"""
Experiment 3 Analysis: Generate comprehensive report from reproducibility and stability results.

Loads JSON summaries and generates markdown report with:
- Statistical analysis
- Reproducibility metrics
- Stability metrics
- Visualizations
- Conclusions
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import statistics


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        return f"{seconds/3600:.1f}h"


def load_latest_summary(experiment_dir: Path, prefix: str) -> Dict:
    """Load the most recent summary JSON file."""
    files = list(experiment_dir.glob(f"{prefix}_*.json"))
    if not files:
        return {}
    
    latest = max(files, key=lambda p: p.stat().st_mtime)
    with open(latest, 'r') as f:
        return json.load(f)


def generate_report(repro_summary: Dict, stability_summary: Dict, output_path: Path):
    """Generate comprehensive markdown report."""
    
    report = f"""# Experiment 3: Reproducibility & Stability

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Executive Summary

This experiment evaluated the reproducibility and stability of the agentic workflow system through:
1. **Reproducibility Testing:** Running identical analyses multiple times to measure consistency
2. **Stability Testing:** Testing robustness to natural language prompt variations

### Key Results

"""
    
    # Reproducibility results
    if repro_summary:
        repro_overall = repro_summary.get("overall", {})
        report += f"""**Reproducibility (15 runs across 3 tickers):**
- Success Rate: {repro_overall.get('success_rate', 0)*100:.1f}%
- Time Consistency (CV): {repro_overall.get('time_statistics', {}).get('cv', 0):.3f}
- Average Duration: {format_duration(repro_overall.get('time_statistics', {}).get('mean', 0))}

"""
    
    # Stability results
    if stability_summary:
        stability_metrics = stability_summary.get("metrics", {})
        report += f"""**Stability (4 prompt variations for NVDA):**
- Success Rate: {stability_metrics.get('success_rate', 0)*100:.1f}%
- Intent Recognition: {stability_metrics.get('intent_recognition_rate', 0)*100:.1f}%
- Workflow Consistency: {stability_metrics.get('workflow_consistency', 0)*100:.1f}%
- Time Variance (CV): {stability_metrics.get('time_statistics', {}).get('cv', 0):.3f}
- Stability Score: {stability_metrics.get('stability_score', 0):.3f}

"""
    
    report += """---

## Part 1: Reproducibility Testing

### Objective

Measure whether running the same analysis multiple times produces consistent results in terms of:
- Successful completion
- Execution time
- Output artifacts

### Test Configuration

"""
    
    if repro_summary:
        config = repro_summary.get("configuration", {})
        report += f"""- **Tickers:** {', '.join(config.get('tickers', []))}
- **Runs per Ticker:** {config.get('runs_per_ticker', 0)}
- **Total Runs:** {config.get('total_runs', 0)}
- **Prompt:** "Analyze {{ticker}} stock and provide investment recommendation"

"""
    
    report += """### Results by Ticker

"""
    
    if repro_summary:
        by_ticker = repro_summary.get("by_ticker", {})
        
        report += """| Ticker | Success Rate | Mean Time (s) | Std Dev (s) | CV | Reproducibility Score |
|--------|--------------|---------------|-------------|----|-----------------------|
"""
        
        for ticker, metrics in by_ticker.items():
            success_rate = metrics.get('success_rate', 0)
            time_stats = metrics.get('time_statistics', {})
            mean_time = time_stats.get('mean', 0)
            std_dev = time_stats.get('std_dev', 0)
            cv = time_stats.get('cv', 0)
            score = metrics.get('reproducibility_score', 0)
            
            report += f"| {ticker} | {success_rate*100:.1f}% | {mean_time:.1f} | {std_dev:.1f} | {cv:.3f} | {score:.3f} |\n"
        
        report += "\n"
    
    report += """### Overall Reproducibility Metrics

"""
    
    if repro_summary:
        overall = repro_summary.get("overall", {})
        time_stats = overall.get('time_statistics', {})
        
        report += f"""**Success Rate:** {overall.get('success_rate', 0)*100:.1f}%
- Total runs: {overall.get('total_runs', 0)}
- Successful: {overall.get('successful_runs', 0)}
- Failed: {overall.get('total_runs', 0) - overall.get('successful_runs', 0)}

**Execution Time Statistics:**
- Mean: {format_duration(time_stats.get('mean', 0))}
- Median: {format_duration(time_stats.get('median', 0))}
- Std Dev: {time_stats.get('std_dev', 0):.2f}s
- Coefficient of Variation (CV): {time_stats.get('cv', 0):.3f}

**Interpretation:**
"""
        
        cv = time_stats.get('cv', 0)
        if cv < 0.15:
            report += "- ✅ Excellent reproducibility (CV < 0.15) - Very consistent execution times\n"
        elif cv < 0.25:
            report += "- ✅ Good reproducibility (CV < 0.25) - Consistent with acceptable variance\n"
        elif cv < 0.40:
            report += "- ⚠️ Moderate reproducibility (CV < 0.40) - Some variance present\n"
        else:
            report += "- ❌ Low reproducibility (CV ≥ 0.40) - High variance in execution times\n"
        
        report += "\n"
    
    report += """### Time Distribution Across Runs

"""
    
    if repro_summary:
        # Create ASCII visualization
        all_results = repro_summary.get("all_results", [])
        successful = [r for r in all_results if r.get("success")]
        
        if successful:
            durations = [r["duration_seconds"] for r in successful]
            min_dur = min(durations)
            max_dur = max(durations)
            
            report += "```\n"
            report += f"Duration range: {format_duration(min_dur)} - {format_duration(max_dur)}\n\n"
            
            # Group by ticker
            by_ticker_runs = {}
            for r in successful:
                ticker = r.get("ticker")
                if ticker not in by_ticker_runs:
                    by_ticker_runs[ticker] = []
                by_ticker_runs[ticker].append(r["duration_seconds"])
            
            for ticker in sorted(by_ticker_runs.keys()):
                runs = by_ticker_runs[ticker]
                mean_t = statistics.mean(runs)
                report += f"{ticker}: {format_duration(mean_t)} (n={len(runs)})\n"
                for i, dur in enumerate(runs, 1):
                    bar_len = int((dur / max_dur) * 40)
                    bar = "█" * bar_len
                    report += f"  Run {i}: {bar} {format_duration(dur)}\n"
                report += "\n"
            
            report += "```\n\n"
    
    report += """---

## Part 2: Stability Testing (Prompt Paraphrasing)

### Objective

Measure robustness to natural language variations by testing semantically equivalent prompts.

### Test Configuration

"""
    
    if stability_summary:
        config = stability_summary.get("configuration", {})
        prompts = config.get("prompt_variations", [])
        
        report += f"""- **Ticker:** {config.get('ticker', 'N/A')}
- **Prompt Variations:** {len(prompts)}
- **Total Runs:** {config.get('total_runs', 0)}

**Prompt Variations Tested:**
"""
        for i, prompt in enumerate(prompts, 1):
            report += f"{i}. \"{prompt}\"\n"
        
        report += "\n"
    
    report += """### Results

"""
    
    if stability_summary:
        metrics = stability_summary.get("metrics", {})
        time_stats = metrics.get('time_statistics', {})
        
        report += f"""| Metric | Value |
|--------|-------|
| **Success Rate** | {metrics.get('success_rate', 0)*100:.1f}% |
| **Intent Recognition** | {metrics.get('intent_recognition_rate', 0)*100:.1f}% |
| **Workflow Consistency** | {metrics.get('workflow_consistency', 0)*100:.1f}% |
| **Mean Time** | {format_duration(time_stats.get('mean', 0))} |
| **Time Range** | {format_duration(time_stats.get('range', 0))} |
| **CV (Time)** | {time_stats.get('cv', 0):.3f} |
| **Stability Score** | {metrics.get('stability_score', 0):.3f} |

"""
    
    report += """### Interpretation

"""
    
    if stability_summary:
        metrics = stability_summary.get("metrics", {})
        
        intent_rate = metrics.get('intent_recognition_rate', 0)
        workflow_cons = metrics.get('workflow_consistency', 0)
        cv = metrics.get('time_statistics', {}).get('cv', 0)
        
        report += f"""**Intent Recognition:** {intent_rate*100:.0f}%
"""
        if intent_rate == 1.0:
            report += "- ✅ Perfect - All prompts correctly identified the ticker and analysis intent\n"
        elif intent_rate >= 0.75:
            report += "- ✅ Good - Most prompts correctly recognized\n"
        else:
            report += "- ⚠️ Needs improvement - Some prompts not properly recognized\n"
        
        report += f"""
**Workflow Consistency:** {workflow_cons*100:.0f}%
"""
        if workflow_cons == 1.0:
            report += "- ✅ Perfect - All prompts triggered identical agent execution paths\n"
        elif workflow_cons >= 0.8:
            report += "- ✅ Good - Most prompts followed similar workflows\n"
        else:
            report += "- ⚠️ Inconsistent - Prompts triggered different workflows\n"
        
        report += f"""
**Time Variance (CV):** {cv:.3f}
"""
        if cv < 0.20:
            report += "- ✅ Low variance - Prompts have similar execution times\n"
        elif cv < 0.35:
            report += "- ⚠️ Moderate variance - Some differences in execution time\n"
        else:
            report += "- ❌ High variance - Significant execution time differences\n"
        
        report += "\n"
    
    report += """### Per-Prompt Results

"""
    
    if stability_summary:
        results = stability_summary.get("all_results", [])
        
        report += """| Prompt # | Duration (s) | Success | Ticker Recognized | Agents Executed |
|----------|--------------|---------|-------------------|-----------------|
"""
        
        for r in results:
            pnum = r.get("prompt_number", 0)
            dur = r.get("duration_seconds", 0)
            success = "✅" if r.get("success") else "❌"
            ticker = r.get("workflow", {}).get("recognized_ticker", "N/A")
            agents = len(r.get("workflow", {}).get("agents_mentioned", []))
            
            report += f"| {pnum} | {dur:.1f} | {success} | {ticker} | {agents} |\n"
        
        report += "\n"
    
    report += """---

## Comparison: Reproducibility vs Stability

"""
    
    if repro_summary and stability_summary:
        repro_cv = repro_summary.get("overall", {}).get("time_statistics", {}).get("cv", 0)
        stability_cv = stability_summary.get("metrics", {}).get("time_statistics", {}).get("cv", 0)
        
        repro_success = repro_summary.get("overall", {}).get("success_rate", 0)
        stability_success = stability_summary.get("metrics", {}).get("success_rate", 0)
        
        report += f"""| Metric | Reproducibility | Stability | Comparison |
|--------|-----------------|-----------|------------|
| **Success Rate** | {repro_success*100:.1f}% | {stability_success*100:.1f}% | {"✅ Similar" if abs(repro_success - stability_success) < 0.1 else "⚠️ Different"} |
| **Time CV** | {repro_cv:.3f} | {stability_cv:.3f} | {"✅ Similar" if abs(repro_cv - stability_cv) < 0.1 else "⚠️ Different"} |

**Analysis:**

"""
        
        if abs(repro_cv - stability_cv) < 0.1:
            report += "- The coefficient of variation is similar between reproducibility and stability tests, suggesting that prompt paraphrasing does not introduce significant additional variance beyond natural execution variance.\n"
        else:
            report += "- The coefficient of variation differs between tests, suggesting prompt variations may affect execution characteristics.\n"
        
        report += "\n"
    
    report += """---

## Key Findings

"""
    
    findings = []
    
    if repro_summary:
        overall = repro_summary.get("overall", {})
        success_rate = overall.get("success_rate", 0)
        cv = overall.get("time_statistics", {}).get("cv", 0)
        
        if success_rate >= 0.9:
            findings.append(f"1. **High Reliability:** The system achieved {success_rate*100:.1f}% success rate across multiple runs, demonstrating production-ready reliability.")
        else:
            findings.append(f"1. **Reliability Concerns:** Success rate of {success_rate*100:.1f}% suggests room for improvement in system stability.")
        
        if cv < 0.25:
            findings.append(f"2. **Consistent Performance:** Time variance (CV={cv:.3f}) is low, indicating predictable execution times.")
        else:
            findings.append(f"2. **Variable Performance:** Time variance (CV={cv:.3f}) suggests non-deterministic factors affect execution time.")
    
    if stability_summary:
        metrics = stability_summary.get("metrics", {})
        intent_rate = metrics.get("intent_recognition_rate", 0)
        workflow_cons = metrics.get("workflow_consistency", 0)
        
        if intent_rate == 1.0 and workflow_cons == 1.0:
            findings.append("3. **Robust NLP:** Perfect intent recognition and workflow consistency demonstrate strong natural language understanding.")
        elif intent_rate >= 0.75:
            findings.append(f"3. **Good NLP Robustness:** {intent_rate*100:.0f}% intent recognition shows the system handles prompt variations well.")
        else:
            findings.append(f"3. **NLP Challenges:** {intent_rate*100:.0f}% intent recognition suggests prompt engineering could be improved.")
    
    if repro_summary and stability_summary:
        repro_cv = repro_summary.get("overall", {}).get("time_statistics", {}).get("cv", 0)
        stability_cv = stability_summary.get("metrics", {}).get("time_statistics", {}).get("cv", 0)
        
        if abs(repro_cv - stability_cv) < 0.1:
            findings.append("4. **Variance Attribution:** Similar CV values suggest execution variance is primarily due to external factors (API latency, network) rather than prompt interpretation.")
    
    for finding in findings:
        report += f"{finding}\n\n"
    
    report += """---

## Conclusions

"""
    
    if repro_summary and stability_summary:
        repro_success = repro_summary.get("overall", {}).get("success_rate", 0)
        stability_success = stability_summary.get("metrics", {}).get("success_rate", 0)
        
        if repro_success >= 0.9 and stability_success >= 0.9:
            report += """### System Maturity: Production-Ready

The agentic workflow system demonstrates:
- **High reliability** (>90% success rate)
- **Consistent performance** (acceptable time variance)
- **Robust NLP** (handles prompt variations well)

These characteristics indicate the system is ready for production deployment with confidence in reproducible, stable behavior.

"""
        else:
            report += """### System Maturity: Functional with Improvements Needed

The system shows functional capability but would benefit from:
- Enhanced error handling for edge cases
- Optimization to reduce execution variance
- Improved prompt understanding and routing

"""
    
    report += """### Implications for Research Paper

**Strengths to Highlight:**
- Reproducibility validates the system's engineering quality
- Stability demonstrates robust natural language interface
- Low variance shows predictable performance characteristics

**Honest Assessment:**
- Document actual CV values (don't overstate consistency)
- Acknowledge external factors affecting variance (API latency)
- Note that some variance is expected and acceptable in LLM-based systems

**Recommended Presentation:**
- Use reproducibility as evidence of system reliability
- Use stability as evidence of robust agent orchestration
- Compare to baseline (no reproducibility guarantees in ad-hoc LLM usage)

---

## Limitations

1. **Sample Size:** Limited runs (5 per ticker for reproducibility, 4 for stability)
2. **Temporal Factors:** Runs conducted sequentially, not controlling for time-of-day effects
3. **External Dependencies:** Cannot control for API provider variance
4. **Output Comparison:** Did not compare detailed output content (only metadata)
5. **LLM Non-determinism:** Even with temperature=0, some models show inherent variance

---

## Future Work

1. **Larger Sample Sizes:** 20-50 runs per configuration for statistical confidence
2. **Content-Level Analysis:** Compare actual report text and valuation numbers
3. **Cross-Provider Testing:** Test reproducibility across different LLM providers
4. **Seed Control:** Implement deterministic seeding if supported by LLM framework
5. **Ablation Studies:** Test which components contribute most to variance

---

*Experiment conducted: {datetime.now().strftime("%Y-%m-%d")}*  
*Analysis method: Statistical analysis of workflow execution metadata*  
*Data source: Subprocess execution logs and output inspection*
"""
    
    # Write report
    with open(output_path, 'w') as f:
        f.write(report)
    
    print(f"\n✅ Report generated: {output_path}")


def main():
    """Generate comprehensive analysis report."""
    
    results_dir = Path("experiments/results/experiment_3")
    
    print("\n" + "="*80)
    print("EXPERIMENT 3 ANALYSIS: Generating Report")
    print("="*80 + "\n")
    
    # Load summaries
    print("Loading reproducibility summary...")
    repro_summary = load_latest_summary(results_dir, "reproducibility_summary")
    
    print("Loading stability summary...")
    stability_summary = load_latest_summary(results_dir, "stability_summary")
    
    if not repro_summary and not stability_summary:
        print("❌ No summary files found. Run the experiments first.")
        return
    
    # Generate report
    print("\nGenerating comprehensive report...")
    report_path = results_dir / "EXPERIMENT_3_REPORT.md"
    generate_report(repro_summary, stability_summary, report_path)
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
    print(f"Report: {report_path}")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
