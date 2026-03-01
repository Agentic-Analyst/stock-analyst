#!/usr/bin/env python3
"""
Quick progress checker for Experiment 3
"""
import json
from pathlib import Path
from datetime import datetime

def check_progress():
    results_dir = Path("experiments/results/experiment_3")
    
    # Check reproducibility
    repro_dir = results_dir / "reproducibility"
    if repro_dir.exists():
        json_files = list(repro_dir.glob("run_*.json"))
        print(f"\n📊 Reproducibility Progress: {len(json_files)}/9 runs complete")
        
        if json_files:
            for f in sorted(json_files)[-3:]:  # Show last 3
                with open(f) as file:
                    data = json.load(file)
                    ticker = data.get("ticker", "?")
                    run = data.get("run_number", "?")
                    dur = data.get("duration_seconds", 0)
                    success = "✅" if data.get("success") else "❌"
                    print(f"  {ticker} run {run}: {dur:.1f}s {success}")
    else:
        print("\n📊 Reproducibility: Not started")
    
    # Check stability
    stab_dir = results_dir / "stability"
    if stab_dir.exists():
        json_files = list(stab_dir.glob("run_*.json"))
        print(f"\n🔄 Stability Progress: {len(json_files)}/3 runs complete")
        
        if json_files:
            for f in sorted(json_files):
                with open(f) as file:
                    data = json.load(file)
                    pnum = data.get("prompt_number", "?")
                    dur = data.get("duration_seconds", 0)
                    success = "✅" if data.get("success") else "❌"
                    print(f"  Prompt {pnum}: {dur:.1f}s {success}")
    else:
        print("\n🔄 Stability: Not started")
    
    # Check summaries
    summaries = list(results_dir.glob("*_summary_*.json"))
    if summaries:
        print(f"\n📄 Summaries generated: {len(summaries)}")
    
    print()

if __name__ == "__main__":
    check_progress()
