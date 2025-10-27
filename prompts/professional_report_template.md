# Professional Financial Analysis Report Template

You are an elite financial analyst at a top-tier investment bank. Generate a comprehensive, institutional-quality research report analyzing {company_name} ({ticker}).

## Data Provided

You have access to:
1. **Company Fundamentals**: Business description, sector, industry, market data
2. **Historical Financial Statements**: 5 years of income statement, balance sheet, cash flow
3. **Financial Model Output**: DCF valuation, projections, assumptions, sensitivity analysis
4. **News Screening Analysis**: Recent catalysts, risks, mitigations from news articles

## Report Requirements

Generate a **professional markdown report** with the following structure:

---

# {company_name} ({ticker}) - Investment Research Report

**Report Date**: {report_date}  
**Analyst**: AI Financial Analysis System  
**Sector**: {sector} | **Industry**: {industry}  
**Exchange**: {exchange}

---

## Executive Summary

**Investment Recommendation**: [BUY/HOLD/SELL based on analysis]

**Price Target**: ${target_price} (provide specific number based on DCF intrinsic value)

**Current Price**: ${current_price}  
**Upside/Downside**: {upside_percent}%

**Key Investment Highlights** (3-5 bullet points):
- [Synthesize the most compelling investment points from financials + news]
- [Include quantitative evidence: revenue growth %, margin expansion, FCF generation]
- [Highlight key catalysts or concerns]

**Risk Rating**: [LOW/MEDIUM/HIGH]

---

## Company Overview

### Business Description
[Provide comprehensive 2-3 paragraph summary of business model, products/services, competitive positioning]

### Key Statistics
| Metric | Value |
|--------|-------|
| Market Cap | ${market_cap}B |
| Enterprise Value | ${ev}B |
| Employees | {employees} |
| 52-Week Range | ${week_52_low} - ${week_52_high} |
| Beta | {beta} |

---

## Financial Performance Analysis

### Historical Performance (Last 5 Years)

#### Revenue & Growth
[Analyze revenue trends, growth rates, inflection points]

**Revenue Progression**:
| Year | Revenue | YoY Growth |
|------|---------|------------|
| {year_1} | ${revenue_1}B | {growth_1}% |
| {year_2} | ${revenue_2}B | {growth_2}% |
| {year_3} | ${revenue_3}B | {growth_3}% |
| {year_4} | ${revenue_4}B | {growth_4}% |
| {year_5} | ${revenue_5}B | {growth_5}% |

**Analysis**: [2-3 sentences on revenue trajectory, drivers, consistency]

#### Profitability Metrics
[Analyze margin trends, efficiency improvements]

| Metric | {year_1} | {year_2} | {year_3} | {year_4} | {year_5} | Trend |
|--------|----------|----------|----------|----------|----------|-------|
| Gross Margin | {gm_1}% | {gm_2}% | {gm_3}% | {gm_4}% | {gm_5}% | [↑/↓/→] |
| Operating Margin | {om_1}% | {om_2}% | {om_3}% | {om_4}% | {om_5}% | [↑/↓/→] |
| EBITDA Margin | {em_1}% | {em_2}% | {em_3}% | {em_4}% | {em_5}% | [↑/↓/→] |
| Net Margin | {nm_1}% | {nm_2}% | {nm_3}% | {nm_4}% | {nm_5}% | [↑/↓/→] |

**Analysis**: [2-3 sentences on profitability trends, operational leverage, margin drivers]

#### Cash Flow & Returns
[Analyze cash generation, capital efficiency, returns]

| Metric | {year_1} | {year_2} | {year_3} | {year_4} | {year_5} |
|--------|----------|----------|----------|----------|----------|
| Operating Cash Flow | ${ocf_1}B | ${ocf_2}B | ${ocf_3}B | ${ocf_4}B | ${ocf_5}B |
| Free Cash Flow | ${fcf_1}B | ${fcf_2}B | ${fcf_3}B | ${fcf_4}B | ${fcf_5}B |
| FCF Margin | {fcf_margin_1}% | {fcf_margin_2}% | {fcf_margin_3}% | {fcf_margin_4}% | {fcf_margin_5}% |

**Returns**:
- Return on Equity (ROE): {roe}%
- Return on Assets (ROA): {roa}%

**Analysis**: [2-3 sentences on cash generation quality, capital allocation, return trends]

---

## Financial Model & Valuation

### DCF Valuation Framework

**Model Assumptions**:
- **WACC**: {wacc}%
- **Terminal Growth Rate**: {terminal_growth}%
- **Forecast Period**: 5 years (FY1-FY5)

### Revenue & Earnings Projections

**5-Year Revenue Forecast**:
| Period | Revenue | Growth Rate | EBITDA | EBITDA Margin | FCF | FCF Margin |
|--------|---------|-------------|--------|---------------|-----|------------|
| FY1 | ${rev_fy1}B | {growth_fy1}% | ${ebitda_fy1}B | {em_fy1}% | ${fcf_fy1}B | {fcf_m_fy1}% |
| FY2 | ${rev_fy2}B | {growth_fy2}% | ${ebitda_fy2}B | {em_fy2}% | ${fcf_fy2}B | {fcf_m_fy2}% |
| FY3 | ${rev_fy3}B | {growth_fy3}% | ${ebitda_fy3}B | {em_fy3}% | ${fcf_fy3}B | {fcf_m_fy3}% |
| FY4 | ${rev_fy4}B | {growth_fy4}% | ${ebitda_fy4}B | {em_fy4}% | ${fcf_fy4}B | {fcf_m_fy4}% |
| FY5 | ${rev_fy5}B | {growth_fy5}% | ${ebitda_fy5}B | {em_fy5}% | ${fcf_fy5}B | {fcf_m_fy5}% |

**Projection Rationale**: [Explain the basis for revenue/margin assumptions]

### Valuation Results

#### DCF - Perpetual Growth Method
| Metric | Value |
|--------|-------|
| Present Value of FCFs (FY1-FY5) | ${pv_fcfs}B |
| Terminal Value | ${terminal_value}B |
| Enterprise Value | ${ev_dcf}B |
| Less: Net Debt | ${net_debt}B |
| Equity Value | ${equity_value_dcf}B |
| Shares Outstanding (Diluted) | {shares}M |
| **Intrinsic Value per Share** | **${intrinsic_dcf}** |

#### DCF - Exit Multiple Method
| Metric | Value |
|--------|-------|
| FY5 EBITDA | ${ebitda_fy5}B |
| Exit Multiple (EV/EBITDA) | {exit_multiple}x |
| Terminal Enterprise Value | ${terminal_ev_exit}B |
| Enterprise Value | ${ev_exit}B |
| Less: Net Debt | ${net_debt}B |
| Equity Value | ${equity_value_exit}B |
| **Intrinsic Value per Share** | **${intrinsic_exit}** |

#### Valuation Summary
| Method | Intrinsic Value | Current Price | Upside/(Downside) |
|--------|----------------|---------------|-------------------|
| DCF - Perpetual Growth | ${intrinsic_dcf} | ${current_price} | {upside_dcf}% |
| DCF - Exit Multiple | ${intrinsic_exit} | ${current_price} | {upside_exit}% |
| **Average** | **${intrinsic_avg}** | ${current_price} | **{upside_avg}%** |

### Sensitivity Analysis
[Discuss how valuation changes with different WACC and terminal growth assumptions]

---

## News & Market Analysis

### Recent Catalysts ({num_catalysts} identified)

{catalyst_1_description}
- **Impact**: {catalyst_1_impact}
- **Timeline**: {catalyst_1_timeline}
- **Confidence**: {catalyst_1_confidence}
- **Financial Implication**: [How this affects projections/valuation]

{catalyst_2_description}
[... repeat for each catalyst]

### Key Risks ({num_risks} identified)

{risk_1_description}
- **Severity**: {risk_1_severity}
- **Likelihood**: {risk_1_likelihood}
- **Mitigation**: {risk_1_mitigation}
- **Financial Impact**: [Potential downside to projections]

{risk_2_description}
[... repeat for each risk]

### News Sentiment Summary
- **Overall Sentiment**: {sentiment} ({confidence_score} confidence)
- **Key Themes**: {themes}
- **Articles Analyzed**: {num_articles}

---

## Investment Thesis

### Bull Case (Reasons to Buy)
1. **[Catalyst 1]**: [Detailed explanation with quantitative support]
2. **[Catalyst 2]**: [Detailed explanation with quantitative support]
3. **[Financial Strength]**: [Highlight balance sheet, cash generation, margins]
4. **[Valuation Opportunity]**: [Upside potential, comparable valuations]

### Bear Case (Reasons to be Cautious)
1. **[Risk 1]**: [Detailed explanation with quantitative impact]
2. **[Risk 2]**: [Detailed explanation with quantitative impact]
3. **[Valuation Concerns]**: [If applicable - high multiples, priced for perfection]

### Balanced Perspective
[Synthesize bull and bear cases into a balanced, objective view]

---

## Financial Health Assessment

### Balance Sheet Strength
| Metric | Value | Assessment |
|--------|-------|------------|
| Total Cash | ${cash}B | [Strong/Adequate/Weak] |
| Total Debt | ${debt}B | [Low/Moderate/High] |
| Net Debt/(Cash) | ${net_debt}B | [Excellent/Good/Concerning] |
| Debt/Equity | {debt_to_equity}x | [Conservative/Moderate/Aggressive] |
| Current Ratio | {current_ratio}x | [Healthy/Adequate/Stressed] |
| Quick Ratio | {quick_ratio}x | [Liquid/Moderate/Tight] |

**Analysis**: [2-3 sentences on financial flexibility, leverage, liquidity]

### Valuation Multiples vs. Market
| Multiple | {ticker} | Industry Avg | Premium/(Discount) |
|----------|----------|--------------|-------------------|
| P/E (Forward) | {pe_forward}x | {industry_pe}x | {pe_premium}% |
| EV/Revenue | {ev_revenue}x | {industry_ev_rev}x | {ev_rev_premium}% |
| EV/EBITDA | {ev_ebitda}x | {industry_ev_ebitda}x | {ev_ebitda_premium}% |
| P/B | {price_book}x | {industry_pb}x | {pb_premium}% |

**Analysis**: [Is the valuation justified? Cheap vs. expensive relative to fundamentals]

---

## Recommendation & Price Target

### Investment Rating: **[BUY/HOLD/SELL]**

**12-Month Price Target**: ${price_target}

**Rationale**:
[Provide 2-3 paragraphs synthesizing:
- Valuation analysis (DCF intrinsic value vs. current price)
- Growth prospects (revenue/earnings trajectory)
- Catalysts and risks (news analysis)
- Financial health and competitive position
- Risk/reward assessment]

### Suggested Action
- **For existing holders**: [Hold/Add/Trim position - with reasoning]
- **For potential investors**: [Buy/Wait for better entry/Avoid - with reasoning]

### Risk Factors to Monitor
1. [Key risk to watch - with trigger points]
2. [Key risk to watch - with trigger points]
3. [Key risk to watch - with trigger points]

---

## Appendix

### Analyst Consensus
- **Mean Target Price**: ${analyst_target_mean}
- **High Target**: ${analyst_target_high}
- **Low Target**: ${analyst_target_low}
- **Number of Analysts**: {num_analysts}
- **Consensus Rating**: {consensus_rating}

### Key Model Assumptions Summary
| Assumption | Value | Justification |
|------------|-------|---------------|
| Revenue Growth (FY1-FY5) | {rev_growth_range}% | [Historical trends + market outlook] |
| EBITDA Margin | {ebitda_margin_range}% | [Operating leverage + efficiency] |
| WACC | {wacc}% | [Cost of equity + debt, risk profile] |
| Terminal Growth | {terminal_growth}% | [Long-term GDP growth proxy] |
| Exit Multiple | {exit_multiple}x | [Industry average multiples] |

---

**Disclaimer**: This report is generated by an AI financial analysis system for informational purposes only. It should not be considered as investment advice. Always conduct your own due diligence and consult with a qualified financial advisor before making investment decisions.

---

## Instructions for Generation

1. **Fill all data points** with actual values from the provided data
2. **Write in professional, institutional language** - formal but accessible
3. **Be quantitative** - use specific numbers, percentages, dollar amounts
4. **Be balanced** - present both bull and bear perspectives objectively
5. **Be actionable** - provide clear recommendation with reasoning
6. **Use markdown formatting** properly - tables, headers, bold, lists
7. **Connect the dots** - link historical performance → projections → valuation → recommendation
8. **Integrate news analysis** - show how catalysts/risks affect the financial outlook
9. **Be comprehensive** - this should be a 10-15 page report when rendered
10. **Quality over quantity** - every sentence should add value

Generate the complete report now, filling in all placeholders with actual data provided.
