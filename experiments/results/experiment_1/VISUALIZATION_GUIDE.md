# Experiment 1: Visualization Figures

## Overview

Professional visualization figures for the research paper's Experiment 1 (Latency and Agent Breakdown).

## Generated Figures

### Figure 1: Agent Breakdown (experiment_1_agent_breakdown.pdf)
**Best for: Main paper figure matching Section 5.3**

**Description:**
- **Left panel (Pie Chart):** Shows percentage distribution of execution time across all components
- **Right panel (Bar Chart):** Shows absolute execution times in seconds with percentages

**Key Insights:**
- News Screening: 189.4s (49.4%) - Largest component
- Reporting: 167.6s (43.8%) - Second largest
- Financial Data: 4.66s (1.2%) - Fast, symbolic
- Valuation: 5.16s (1.3%) - Fast, symbolic
- Supervisor: 16.24s (4.2%) - Coordination overhead

**Use in Paper:**
This figure directly supports the text in your screenshot showing that semantic agents (News + Reporting) account for 93.2% of runtime, while Financial Data and Valuation together account for under 3%.

---

### Figure 2: Workflow Comparison (experiment_1_workflow_comparison.pdf)
**Best for: Showing variability across different workflow configurations**

**Description:**
- Stacked bar chart comparing 4 different workflow configurations
- Each bar shows the contribution of different agents to total latency
- Demonstrates how workflow complexity affects execution time

**Configurations Shown:**
1. **META Full (383s):** Complete 4-agent workflow
2. **AAPL News+Summary (215s):** News-focused analysis
3. **GOOGL Finance+Model (98s):** Financial analysis only
4. **META Minimal (20s):** Minimal workflow

**Key Insights:**
- Full workflows: 6.4 minutes
- News-heavy workflows: 3.6 minutes
- Finance-only workflows: 0.3-1.6 minutes
- News and Reporting dominate when present

---

### Figure 3: Semantic vs. Symbolic (experiment_1_semantic_vs_symbolic.pdf)
**Best for: Highlighting the architectural separation**

**Description:**
- Bar chart showing three categories: Semantic (LLM), Symbolic (Deterministic), Coordination
- Clear visualization of the 93% LLM dominance
- Annotated with the key finding

**Categories:**
- **Semantic Processing (357.0s, 93.2%):** News Screening + Reporting (LLM-based)
- **Symbolic Processing (9.82s, 2.6%):** Financial Data + Valuation (deterministic)
- **Coordination (16.24s, 4.2%):** Supervisor overhead

**Key Insight:**
"93.2% of time in LLM operations" - directly validates the architectural separation between semantic and symbolic components from Section 4.

---

## File Formats

Each figure is saved in two formats:

1. **PDF (.pdf)**: 
   - Vector format, scales to any size
   - **Recommended for LaTeX papers**
   - Highest quality for publication

2. **PNG (.png)**:
   - Raster format at 300 DPI
   - Good for presentations and web
   - Use if PDF has compatibility issues

## Usage in LaTeX

```latex
\begin{figure}[t]
    \centering
    \includegraphics[width=0.9\linewidth]{figures/experiment_1_agent_breakdown.pdf}
    \caption{Agent execution time distribution for the META full workflow (383.0s total). 
    Semantic agents (News Screening 49.4\%, Reporting 43.8\%) account for the majority of runtime, 
    while Financial Data and Valuation agents together consume under 3\%. 
    Supervisor overhead contributes approximately 4.2\%.}
    \label{fig:agent_breakdown}
\end{figure}
```

## Usage in Word/Google Docs

1. Insert → Picture → From File
2. Choose the PDF file (Word 2016+ supports PDF)
3. Or use PNG if PDF doesn't render correctly
4. Add caption referencing Figure ?? from your paper

## Data Source

All data extracted from production log analysis of the META full workflow:
- Date: November 8, 2024
- Total Duration: 383.02 seconds
- Agents: news_analysis_agent, financial_data_agent, model_generation_agent, report_generator_agent
- Iterations: 5

## Matching Your Paper Section

Based on your screenshot (Section 5.3), these figures support:

✅ **"News Screening consumes 189.4s (49.4%)"** - Shown in all three figures  
✅ **"Reporting 167.6s (43.8%)"** - Clearly visualized  
✅ **"Financial Data and Valuation agents together account for under 3%"** - Evident in pie chart  
✅ **"Supervisor overhead contributes approximately 4.2%"** - Shown in breakdown  
✅ **"Semantic processing dominates LLM-mediated pipelines"** - Figure 3 highlights this  

## Recommendations

**For your paper's Section 5.3:**
- Use **Figure 1** (agent_breakdown.pdf) as the main figure
- Reference as "Figure ??" in your text
- Consider adding **Figure 3** (semantic_vs_symbolic.pdf) as supplementary to emphasize the 93% finding

**Caption Suggestion:**
"Agent execution time distribution for a full four-agent workflow analyzing META (383.0s total). 
Semantic agents (News Screening and Reporting) consume 93.2% of execution time, 
while symbolic components (Financial Data and Valuation) together account for under 3%. 
This validates the architectural separation between LLM-mediated semantic processing 
and deterministic symbolic computation."

---

**Generated:** December 12, 2025  
**Location:** `experiments/results/experiment_1/figures/`  
**Script:** `experiments/visualize_experiment_1.py`
