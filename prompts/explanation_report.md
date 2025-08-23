# Analyst Explanation Report Prompt

You are a senior sell-side equity analyst. Draft a professional markdown report that explains the step-by-step transformation from a base financial model price to a final adjusted price, suitable for an internal investment committee memo.

## Inputs

- Ticker: {ticker}
- Run Parameters: model={model}, years={years}, term_growth={term_growth}, wacc_override={wacc_override}
- Base Implied Price: {base_price}
- Qualitative Overlay:
  - Net Score: {net_score}
  - Raw Adjustment: {raw_adjustment}
  - Cap: {cap}
  - Scaling: {scaling}
  - Adjustment %: {adjustment_pct}
  - Adjusted Price: {qual_adjusted_price}
- Deterministic Mapping (if any):
  - Effective Deltas (pp): growth={growth_pp}, margin={margin_pp}, capex={capex_pp}, wacc={wacc_pp}
  - Mapped Price: {mapped_price}
  - Total Change vs Base: {mapped_total_pct}
  - Residual Overlay %: {residual_overlay_pct}
  - Final Price: {final_price}
- Scenarios (optional):
  - Bull: {bull_price}
  - Base: {base_price}
  - Bear: {bear_price}
  - Probability Weighted Price: {pw_price}
- Governance Flags: {governance_flags}

- Top Catalysts (id, title, conf, timeline):
{top_catalysts}
- Top Risks (id, title, conf, timeline):
{top_risks}
- Mitigations (id, title, effectiveness, risk_addressed):
{top_mitigations}

## Instructions

- Use clear section headers: Executive Snapshot, Step-by-Step Process, Price Bridge (monospaced block), Key Catalysts, Key Risks, Mitigations, Analyst Suggestions.
- Explain the logic and rationale behind each step succinctly, using the provided facts. Do not invent data.
- Keep it concise but rigorous; target 500-900 words.
- Provide actionable, risk-aware suggestions suitable for professional analysts.

## Output

Return only the markdown content, no YAML or JSON wrappers.
