#!/usr/bin/env python3
"""
Experiment 1: Agent Breakdown Visualization for Research Paper
Generates a professional figure showing the latency breakdown by component.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np
from pathlib import Path

# Set style for academic paper
plt.rcParams['font.family'] = 'serif'
plt.rcParams['font.serif'] = ['Times New Roman', 'DejaVu Serif']
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 11
plt.rcParams['axes.titlesize'] = 12
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 9
plt.rcParams['figure.titlesize'] = 12

# Data from META full workflow (383.0s total)
components = {
    'News Screening': 189.4,
    'Reporting': 167.6,
    'Financial Data': 4.66,
    'Valuation': 5.16,
    'Supervisor': 16.24
}

# Calculate percentages
total = sum(components.values())
percentages = {k: (v/total)*100 for k, v in components.items()}

# Colors - professional palette suitable for papers
colors = {
    'News Screening': '#2E86AB',    # Blue - semantic/LLM
    'Reporting': '#A23B72',         # Purple - semantic/LLM
    'Financial Data': '#F18F01',    # Orange - symbolic
    'Valuation': '#C73E1D',         # Red - symbolic
    'Supervisor': '#6A994E'         # Green - coordination
}

def create_figure():
    """Create the main visualization figure."""
    fig = plt.figure(figsize=(10, 6))
    
    # Create main subplot
    ax1 = plt.subplot(1, 2, 1)
    
    # Create pie chart
    wedges, texts, autotexts = ax1.pie(
        list(components.values()),
        labels=None,  # We'll create custom legend
        autopct='%1.1f%%',
        colors=[colors[k] for k in components.keys()],
        startangle=90,
        pctdistance=0.85,
        explode=[0.05, 0.05, 0, 0, 0]  # Slightly explode the two largest
    )
    
    # Make percentage text more readable
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontsize(9)
        autotext.set_weight('bold')
    
    ax1.set_title('Agent Execution Time Distribution\n(META Full Workflow: 383.0s)', 
                  fontsize=12, pad=15, weight='bold')
    
    # Create bar chart on the right
    ax2 = plt.subplot(1, 2, 2)
    
    # Sort by time for bar chart
    sorted_items = sorted(components.items(), key=lambda x: x[1], reverse=True)
    names = [item[0] for item in sorted_items]
    times = [item[1] for item in sorted_items]
    bar_colors = [colors[name] for name in names]
    
    bars = ax2.barh(names, times, color=bar_colors, alpha=0.8, edgecolor='black', linewidth=0.5)
    
    # Add time labels on bars
    for i, (bar, time) in enumerate(zip(bars, times)):
        width = bar.get_width()
        ax2.text(width + 5, bar.get_y() + bar.get_height()/2, 
                f'{time:.1f}s ({percentages[names[i]]:.1f}%)',
                va='center', fontsize=9, weight='normal')
    
    ax2.set_xlabel('Execution Time (seconds)', fontsize=11, weight='bold')
    ax2.set_title('Per-Component Latency Breakdown', fontsize=12, pad=15, weight='bold')
    ax2.set_xlim(0, max(times) * 1.3)
    ax2.grid(axis='x', alpha=0.3, linestyle='--', linewidth=0.5)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    
    # Add legend with component categorization
    legend_elements = [
        mpatches.Patch(facecolor=colors['News Screening'], edgecolor='black', 
                      label='News Screening (49.4%, LLM)'),
        mpatches.Patch(facecolor=colors['Reporting'], edgecolor='black', 
                      label='Reporting (43.8%, LLM)'),
        mpatches.Patch(facecolor=colors['Supervisor'], edgecolor='black', 
                      label='Supervisor (4.2%, Coordination)'),
        mpatches.Patch(facecolor=colors['Financial Data'], edgecolor='black', 
                      label='Financial Data (1.2%, Symbolic)'),
        mpatches.Patch(facecolor=colors['Valuation'], edgecolor='black', 
                      label='Valuation (1.3%, Symbolic)'),
    ]
    
    fig.legend(handles=legend_elements, loc='lower center', ncol=3, 
              frameon=True, fancybox=True, shadow=True, bbox_to_anchor=(0.5, -0.05))
    
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.15)
    
    return fig

def create_stacked_bar_comparison():
    """Create a stacked bar chart comparing workflows."""
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Data for different workflows
    workflows = ['META\nFull\n(383s)', 'AAPL\nNews+Summary\n(215s)', 
                 'GOOGL\nFinance+Model\n(98s)', 'META\nMinimal\n(20s)']
    
    news_times = [189.4, 206.3, 0, 0]
    report_times = [167.6, 0, 0, 0]
    financial_times = [4.66, 0, 18.0, 8.5]
    valuation_times = [5.16, 0, 65.0, 6.2]
    supervisor_times = [16.24, 9.2, 15.0, 5.3]
    
    # Create stacked bars
    bar_width = 0.6
    x_pos = np.arange(len(workflows))
    
    p1 = ax.bar(x_pos, news_times, bar_width, label='News Screening', 
                color=colors['News Screening'], edgecolor='black', linewidth=0.5)
    p2 = ax.bar(x_pos, report_times, bar_width, bottom=news_times,
                label='Reporting', color=colors['Reporting'], edgecolor='black', linewidth=0.5)
    
    bottom2 = [n + r for n, r in zip(news_times, report_times)]
    p3 = ax.bar(x_pos, financial_times, bar_width, bottom=bottom2,
                label='Financial Data', color=colors['Financial Data'], edgecolor='black', linewidth=0.5)
    
    bottom3 = [b + f for b, f in zip(bottom2, financial_times)]
    p4 = ax.bar(x_pos, valuation_times, bar_width, bottom=bottom3,
                label='Valuation', color=colors['Valuation'], edgecolor='black', linewidth=0.5)
    
    bottom4 = [b + v for b, v in zip(bottom3, valuation_times)]
    p5 = ax.bar(x_pos, supervisor_times, bar_width, bottom=bottom4,
                label='Supervisor', color=colors['Supervisor'], edgecolor='black', linewidth=0.5)
    
    # Add total time labels on top
    totals = [sum(x) for x in zip(news_times, report_times, financial_times, 
                                   valuation_times, supervisor_times)]
    for i, total in enumerate(totals):
        ax.text(i, total + 10, f'{total:.0f}s', ha='center', va='bottom', 
                fontsize=10, weight='bold')
    
    ax.set_ylabel('Execution Time (seconds)', fontsize=11, weight='bold')
    ax.set_xlabel('Workflow Configuration', fontsize=11, weight='bold')
    ax.set_title('Latency Comparison Across Workflow Configurations', 
                 fontsize=12, pad=15, weight='bold')
    ax.set_xticks(x_pos)
    ax.set_xticklabels(workflows)
    ax.legend(loc='upper right', frameon=True, fancybox=True, shadow=True)
    ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    plt.tight_layout()
    return fig

def create_semantic_vs_symbolic():
    """Create visualization showing semantic vs symbolic time split."""
    fig, ax = plt.subplots(figsize=(8, 5))
    
    # Categories
    categories = ['Semantic\nProcessing\n(LLM)', 'Symbolic\nProcessing\n(Deterministic)', 
                  'Coordination\n(Supervisor)']
    
    # Times from META full workflow
    semantic_time = 189.4 + 167.6  # News + Reporting
    symbolic_time = 4.66 + 5.16     # Financial + Valuation
    supervisor_time = 16.24
    
    times = [semantic_time, symbolic_time, supervisor_time]
    percentages_val = [(t/sum(times))*100 for t in times]
    
    bar_colors = ['#7B2CBF', '#FF9F1C', '#6A994E']
    
    bars = ax.bar(categories, times, color=bar_colors, alpha=0.8, 
                  edgecolor='black', linewidth=1.5, width=0.6)
    
    # Add value labels
    for bar, time, pct in zip(bars, times, percentages_val):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 5,
                f'{time:.1f}s\n({pct:.1f}%)',
                ha='center', va='bottom', fontsize=11, weight='bold')
    
    ax.set_ylabel('Execution Time (seconds)', fontsize=12, weight='bold')
    ax.set_title('Semantic vs. Symbolic Processing Time\n(META Full Workflow: 383.0s)', 
                 fontsize=13, pad=15, weight='bold')
    ax.set_ylim(0, max(times) * 1.2)
    ax.grid(axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    
    # Add annotation
    ax.annotate('93.2% of time\nin LLM operations',
                xy=(0, semantic_time), xytext=(0.5, semantic_time * 0.6),
                arrowprops=dict(arrowstyle='->', lw=1.5, color='red'),
                fontsize=10, weight='bold', color='red',
                bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7))
    
    plt.tight_layout()
    return fig

def save_all_figures():
    """Generate and save all visualization figures."""
    output_dir = Path("experiments/results/experiment_1/figures")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("="*70)
    print("EXPERIMENT 1: GENERATING VISUALIZATION FIGURES")
    print("="*70)
    
    # Figure 1: Main breakdown (pie + bar)
    print("\n📊 Generating Figure 1: Agent Breakdown (Pie + Bar Chart)")
    fig1 = create_figure()
    fig1.savefig(output_dir / "experiment_1_agent_breakdown.png", dpi=300, bbox_inches='tight')
    fig1.savefig(output_dir / "experiment_1_agent_breakdown.pdf", bbox_inches='tight')
    print(f"   ✅ Saved: {output_dir / 'experiment_1_agent_breakdown.png'}")
    print(f"   ✅ Saved: {output_dir / 'experiment_1_agent_breakdown.pdf'}")
    plt.close(fig1)
    
    # Figure 2: Workflow comparison
    print("\n📊 Generating Figure 2: Workflow Comparison (Stacked Bar)")
    fig2 = create_stacked_bar_comparison()
    fig2.savefig(output_dir / "experiment_1_workflow_comparison.png", dpi=300, bbox_inches='tight')
    fig2.savefig(output_dir / "experiment_1_workflow_comparison.pdf", bbox_inches='tight')
    print(f"   ✅ Saved: {output_dir / 'experiment_1_workflow_comparison.png'}")
    print(f"   ✅ Saved: {output_dir / 'experiment_1_workflow_comparison.pdf'}")
    plt.close(fig2)
    
    # Figure 3: Semantic vs Symbolic
    print("\n📊 Generating Figure 3: Semantic vs. Symbolic Processing")
    fig3 = create_semantic_vs_symbolic()
    fig3.savefig(output_dir / "experiment_1_semantic_vs_symbolic.png", dpi=300, bbox_inches='tight')
    fig3.savefig(output_dir / "experiment_1_semantic_vs_symbolic.pdf", bbox_inches='tight')
    print(f"   ✅ Saved: {output_dir / 'experiment_1_semantic_vs_symbolic.png'}")
    print(f"   ✅ Saved: {output_dir / 'experiment_1_semantic_vs_symbolic.pdf'}")
    plt.close(fig3)
    
    print("\n" + "="*70)
    print("VISUALIZATION COMPLETE")
    print("="*70)
    print(f"\n📁 All figures saved to: {output_dir}")
    print("\n🎯 Recommended for paper (matching your screenshot):")
    print("   - experiment_1_agent_breakdown.pdf (main figure)")
    print("   - experiment_1_semantic_vs_symbolic.pdf (highlights 93% LLM time)")
    print("\n💡 Use PDF format for best quality in LaTeX/Word")

if __name__ == "__main__":
    save_all_figures()
