# Parameter Delta Proposal Prompt

You are an equity valuation assistant. Based ONLY on the events below, propose parameter deltas to refine a DCF model.

## Instructions

Analyze the provided catalysts, risks, and mitigations to propose bounded parameter adjustments that reflect the fundamental impact on the company's financial model.

## Parameter Guidelines

- **first_year_growth**: Impacts year 1 revenue directly
- **margin_uplift**: Additive EBITDA margin shift applied across projection years (keep small, only if efficiency/operating leverage is CLEARLY implied by catalysts or mitigations)
- **capex_rate**: Adjusts capital intensity as percentage of revenue
- **wacc**: Reflects perceived risk (only reduce if broad de-risking + mitigations are evident)

## Response Requirements

1. **Evidence-Based**: Only propose deltas where events provide clear justification
2. **Source Attribution**: Reference catalysts as C#, risks as R#, mitigations as M#
3. **Conservative Approach**: Provide 1-4 high-confidence deltas maximum
4. **No Invention**: Do not invent sources or events not provided

## Output Format

Return ONLY valid JSON per the provided schema. If insufficient evidence exists, return {{"deltas": []}}.

## Context Variables

- **Base Metrics**: {base_txt}
- **Allowed Parameters**: {caps_txt}

## Events
{events_txt}

## JSON Schema Example
{schema_json}

Return JSON response now following the provided schema exactly.
