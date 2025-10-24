# News-Based Model Adjustment Prompt

You are a financial analyst adjusting DCF model parameters based on news analysis.

## Context
**{company_name} ({ticker})** | Sector: {sector} | Date: {model_date}

**FY0 Actuals**: Rev Growth {revenue_growth_fy0}%, GM {gross_margin_fy0}%, OpM {operating_margin_fy0}%

**Base Assumptions (FY1-FY5)**:
- Revenue Growth: {base_revenue_growth}
- Gross Margin: {base_gross_margins}
- Operating Margin: {base_operating_margins}
- WACC: {base_wacc}% | Terminal Growth: {base_terminal_growth}%

## News Summary
{news_summary}

{catalysts_detail}

{risks_detail}

{mitigations_detail}

## Task: Propose Conservative Adjustments

**Mapping Rules**:
- Product/Market catalysts → Revenue Growth (FY1-FY2, ±100-200 bps)
- Financial catalysts → Revenue + Operating Margin (FY1, ±50-100 bps)
- Regulatory/Cost risks → Gross/Operating Margin (FY1, -20 to -75 bps)
- Competitive risks → Revenue Growth (FY1, -25 to -75 bps)
- Mitigations → Offset 30-60% of related risk (FY2+)

**Caps**: Revenue ±300bps, Margins ±50-75bps, WACC ±25bps, Terminal ±10bps

**Scaling**: Multiply by confidence × (severity/likelihood for risks) × timeline factor

**Timeline**: "short-term" → FY1 (taper 50% to FY2), "medium-term" → FY1-FY2, "long-term" → FY2-FY5

## Output (JSON only, no markdown):

```json
{{
  "adjusted_assumptions": {{
    "revenue_growth_rates": [0.065, 0.055, 0.05, 0.045, 0.035],
    "gross_margins": [0.4565, 0.46, 0.46, 0.46, 0.46],
    "ebitda_margins": [0.33, 0.33, 0.33, 0.33, 0.33],
    "operating_margins": [0.31, 0.31, 0.31, 0.31, 0.31],
    "dso_days": [45, 45, 45, 45, 45],
    "dio_days": [10, 10, 10, 10, 10],
    "dpo_days": [90, 90, 90, 90, 90],
    "wacc": 0.09,
    "terminal_growth_rate": 0.025
  }},
  "adjustments_summary": {{
    "revenue_growth_fy1_bps": 150,
    "gross_margin_fy1_bps": -35,
    "operating_margin_fy1_bps": 0,
    "wacc_bps": 0,
    "key_drivers": ["iPhone 17 demand +150bps Rev FY1", "Tariff -35bps GM FY1"]
  }},
  "factor_mappings": [
    {{
      "factor_id": "catalyst_1",
      "lever_adjustments": [
        {{"lever": "revenue_growth_fy1", "delta_bps": 150, "reasoning": "Strong pre-orders"}}
      ]
    }}
  ]
}}
```

Return JSON only.
