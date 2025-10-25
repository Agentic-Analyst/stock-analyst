# Professional Equity Research Report Generation

You are a senior equity research analyst at a top-tier investment bank. Generate a comprehensive, professional investment research report.

## COMPANY INFORMATION
- **Ticker**: {ticker}
- **Name**: {company_name}
- **Sector**: {sector} | {industry}
- **Market Cap**: {market_cap}
- **Current Price**: ${current_price}
- **Shares Outstanding**: {shares_outstanding}
- **Employees**: {employees}

## BASE CASE VALUATION (Pre-News)

### DCF Perpetual Growth Method
- Enterprise Value: {orig_perpetual_ev}
- Equity Value: {orig_perpetual_equity}
- **Price per Share**: ${orig_perpetual_price}

### DCF Exit Multiple Method
- Enterprise Value: {orig_exit_ev}
- Equity Value: {orig_exit_equity}
- **Price per Share**: ${orig_exit_price}

### Blended Valuation
- **Average Price Target**: ${orig_average_price}
- **Implied Upside**: {orig_upside}

### Key Assumptions
- WACC: {wacc}
- Terminal Growth Rate: {terminal_growth}
- Exit EV/EBITDA Multiple: {exit_multiple}
- Cash: {cash}
- Debt: {debt}

### 5-Year Base Case Projections

**Revenue (FY1-FY5)**: {orig_revenue_projections}
- **5-Year CAGR**: {orig_revenue_cagr}
- Year-over-Year Growth: {orig_revenue_growth_rates}

**EBITDA (FY1-FY5)**: {orig_ebitda_projections}
- **Margins**: {orig_ebitda_margins}

**Free Cash Flow (FY1-FY5)**: {orig_fcf_projections}
- **FCF Margins**: {orig_fcf_margins}

*DCF Methodology: FCFs for FY1-FY5 discounted at WACC {wacc}, plus terminal value calculated as FCF_FY5 × (1+g)/(WACC-g) where g={terminal_growth}. Enterprise Value = PV(FCFs) + PV(Terminal Value). Equity Value = EV + Cash - Debt.*

## NEWS-DRIVEN ANALYSIS

### Catalysts Identified ({num_catalysts})
{catalysts_detail}

### Risks to Monitor ({num_risks})
{risks_detail}

*Note: Each catalyst and risk above includes direct source links to the analyzed articles and key quotes extracted from those sources.*

## ADJUSTED VALUATION (Post-News)
{adjusted_valuation_section}

### Model Adjustments from News Analysis
{adjustment_details}

### Adjusted 5-Year Projections

**Revenue (FY1-FY5)**: {adj_revenue_projections}
- **5-Year CAGR**: {adj_revenue_cagr}
- Year-over-Year Growth: {adj_revenue_growth_rates}

**EBITDA (FY1-FY5)**: {adj_ebitda_projections}
- **Margins**: {adj_ebitda_margins}

**Free Cash Flow (FY1-FY5)**: {adj_fcf_projections}
- **FCF Margins**: {adj_fcf_margins}

---

## YOUR TASK

Generate a professional equity research report with the following structure:

# {ticker}: {company_name}

## Executive Summary
*[2-3 paragraph overview with key recommendation, price target, and investment highlights]*

## Investment Thesis
*[Detailed 3-5 paragraph thesis explaining why this is compelling investment opportunity or pass]*

## Company Overview
*[Business description, competitive position, market dynamics]*

## Financial Analysis

### Base Case Scenario
*[Analysis of original projections and assumptions]*

### News-Adjusted Scenario  
*[Discussion of catalysts/risks and their financial impact]*

### Projection Comparison
*[Side-by-side comparison showing how news changes the outlook]*

## Comprehensive News Analysis

### Overview of News Coverage
**Articles Analyzed**: {articles_analyzed}  
**Analysis Period**: {analysis_period}  
**Overall Sentiment**: {overall_sentiment}  
**Key Themes Identified**: {key_themes}

### Detailed Catalyst Analysis

**Total Catalysts Identified**: {num_catalysts}

{catalysts_detail}

### Detailed Risk Analysis

**Total Risks Identified**: {num_risks}

{risks_detail}

### Risk Mitigation Strategies

**Total Mitigations Identified**: {num_mitigations}

{mitigations_detail}

### News Analysis Summary

{news_analysis_summary}

### Source Article Index

{source_article_index}

## Valuation Summary
*[Detailed valuation methodology, key assumptions, sensitivity analysis]*

## Risk Assessment
*[Comprehensive discussion of risks and mitigations]*

## Investment Recommendation
*[Clear BUY/HOLD/SELL recommendation with rationale and price target]*

**CRITICAL - Recommendation Logic**:
- **BUY** if upside >= +15% (Price target significantly above current price)
- **HOLD** if -10% <= upside < +15% (Price near fair value)
- **SELL** if upside < -10% (Price target significantly below current price)

**Current Analysis**:
- Implied Upside/Downside: {orig_upside}
- **Recommended Action: {recommendation}**

Your recommendation MUST be consistent with the upside/downside calculation. If showing -70% downside, you MUST recommend SELL, not HOLD.

---

## IMPORTANT GUIDELINES

1. **Writing Style**: Professional, institutional investment research tone (not promotional)
2. **Data-Driven**: Use specific numbers, percentages, and CAGRs from the provided data
3. **Balanced Analysis**: Present both bullish and bearish perspectives fairly
4. **News Analysis**:
   - Synthesize the catalyst and risk summaries into narrative form
   - Explain the investment implications of each catalyst/risk
   - Note: Detailed evidence with quotes and sources is provided separately in an appendix
5. **Transparency**: 
   - Reference the specific basis point adjustments made to growth rates and margins
   - Explain how catalysts/risks translate to parameter changes
   - Show confidence scores and timelines for each catalyst/risk
6. **Structure**: Use clear headers, bullet points, and tables where appropriate
7. **Length**: Focused and impactful (target 2-4 pages, not including evidence appendix)
8. **Actionable**: End with clear BUY/HOLD/SELL recommendation with price target and timeframe
9. **Formatting**:
   - Round large market caps to trillions (e.g., $3.9T not $3,900B)
   - Use 1 decimal place for margins (e.g., 26.4% not 26.38%)
   - Show CAGRs explicitly to avoid confusion with individual year growth rates

**OPTIMIZATION NOTE**: The catalyst/risk details provided above are summaries. Write a compelling narrative analyzing these factors and their investment implications. The full detailed evidence with quotes and sources will be appended to your analysis automatically.

Generate the complete report now.
