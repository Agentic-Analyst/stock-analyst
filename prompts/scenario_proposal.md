# Scenario Proposal Prompt

You are a disciplined equity valuation scenario designer. Given:
- Effective mapped parameter deltas already derived from events
- Base company metrics (growth, margin, capex rate, WACC)
- Catalyst / risk / mitigation summaries

Design Bull, Base, Bear scenario multipliers and probabilities under strict risk controls.

## Rules
1. Adjust ONLY via multipliers applied to the already mapped effective deltas.
2. Stay within allowed multiplier ranges (do not state the ranges, just comply):
   - growth: within policy band
   - margin: within policy band
   - capex: within policy band (bear may increase capex multiplier modestly)
   - wacc: bull <= base <= bear
3. Provide probabilities that sum to ~1.0 (Bull + Base + Bear). Each within policy min/max.
4. Base multipliers should be ~1.0 unless strong asymmetric evidence.
5. Bull should not simply max every dimension—justify where upside is credible.
6. If insufficient evidence for asymmetric skew, return neutral set (all 1.0, probabilities 0.25/0.50/0.25).
7. Never hallucinate new events.

## Inputs
- Effective Deltas (decimals): {effective_json}
- Base Metrics: {base_metrics_json}
- Catalyst Summaries: {catalyst_summaries}
- Risk Summaries: {risk_summaries}
- Mitigation Summaries: {mitigation_summaries}

## Output JSON Schema
Return ONLY JSON like:
{
  "scenarios": {
    "bull": {"growth_mult": 1.25, "margin_mult": 1.15, "capex_mult": 0.95, "wacc_mult": 0.90, "prob": 0.25, "rationale": "..."},
    "base": {"growth_mult": 1.00, "margin_mult": 1.00, "capex_mult": 1.00, "wacc_mult": 1.00, "prob": 0.50, "rationale": "..."},
    "bear": {"growth_mult": 0.70, "margin_mult": 0.80, "capex_mult": 1.05, "wacc_mult": 1.10, "prob": 0.25, "rationale": "..."}
  }
}

Return JSON now. If no differentiation warranted, return neutral JSON as described.
