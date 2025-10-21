# Assumptions Inference Prompt

You are a financial analyst inferring DCF model assumptions for a company.

## Context
- Company: {company_name} ({ticker})
- Sector: {sector}
- Latest FY: {latest_fy}
- Historical metrics provided below

## Historical Data (FY0)
- Revenue Growth (YoY): {revenue_growth_fy0}%
- Gross Margin: {gross_margin_fy0}%
- EBITDA Margin: {ebitda_margin_fy0}%
- Operating Margin: {operating_margin_fy0}%
- DSO: {dso_fy0} days
- DIO: {dio_fy0} days
- DPO: {dpo_fy0} days
- Effective Tax Rate: {tax_rate_fy0}%

## Task
Infer the following assumptions for FY1-FY5 (5 years forward). Return ONLY a JSON object with numeric values (no explanations).

Required fields:
- wacc: Weighted average cost of capital (decimal, e.g., 0.09 for 9%)
- terminal_growth_rate: Long-term perpetual growth rate (decimal, e.g., 0.025 for 2.5%)
- revenue_growth_rates: Array of 5 growth rates for FY1-FY5 (decimals)
- gross_margins: Array of 5 gross margins for FY1-FY5 (decimals)
- ebitda_margins: Array of 5 EBITDA margins for FY1-FY5 (decimals)
- operating_margins: Array of 5 operating margins for FY1-FY5 (decimals)
- dso_days: Array of 5 DSO values for FY1-FY5 (days)
- dio_days: Array of 5 DIO values for FY1-FY5 (days)
- dpo_days: Array of 5 DPO values for FY1-FY5 (days)

## Guidelines
- WACC typically 7-12% for mature companies, higher for growth/risky companies
- Terminal growth rate typically 2-3% (GDP growth rate)
- Revenue growth should gradually decline toward terminal rate
- Margins should reflect industry trends and company maturity
- Working capital days should remain stable or improve slightly
- Consider sector benchmarks and company stage (growth vs mature)

Return JSON only, no markdown formatting:
