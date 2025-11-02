# Company: {company_name} ({ticker})
# Sector: {sector}
# Report Date: {report_date}

---

## Analysis Data

### Catalysts Identified: {num_catalysts}
{catalysts_summary}

### Risks Identified: {num_risks}
{risks_summary}

### Mitigations Identified: {num_mitigations}
{mitigations_summary}

### Overall Sentiment: {sentiment}
### Key Themes: {themes}
### Confidence Score: {confidence}

### Articles Analyzed: {num_articles}
{articles_list}

### Peer Companies: {peer_tickers}
{peer_context}

---

## Your Task

Generate a professional **24-Hour Company News Intelligence Report** following this template structure:

# Vynn AI — 24H Company News Intelligence Report

**Company:** {company_name} ({ticker})
**Sector:** {sector}
**Date:** {report_date}
**Analyst Reading Time:** ~2 mins

---

## Price Action — Did News Move the Stock?

{price_action_data}

---

## Top Headlines — Last 24 Hours (Ranked by Materiality)

Create a table with the most material news ranked by importance.

**IMPORTANT**: Headlines should attribute source when claiming specific data:
- Good: "Industry report confirms Nvidia's 50% IC design market share"
- Good: "TrendForce data shows 40% GPU order growth from hyperscalers"
- Bad: "Growing demand for AI products" (too generic, no source)

| Rank | News Headline | Category | Sentiment | Time Horizon | Materiality Score |
| ---- | ------------- | -------- | --------- | ------------ | ----------------- |
| ...  | ...           | ...      | ...       | ...          | ...               |

**Categories**: Macro · Earnings · Guidance · Product/Tech · Partnership · M&A · Regulatory · Litigation · ESG/Labor · Management/Insider
**Sentiment**: Bullish/Neutral/Bearish
**Time Horizon**: Immediate/Short-term/Medium-term/Long-term
**Materiality Score**: 0-100% (how much this could impact stock price)

---

## Why It Matters — Quick Impact Analysis

Provide 1-2 bullet points per major story explaining the business/stock impact.
**IMPORTANT**: Include specific numbers, percentages, and quantitative data from the articles.

Examples:
* **Q1 Earnings Beat** → Revenue grew **+35% YoY to $26.0B** vs **$24.5B consensus**. Data center revenue up **+427%**, demonstrating AI demand strength.
* **Partnership Expansion** → Meta and Alphabet expanding GPU orders by **40%**, adding **$1.2B+ incremental demand** in CY26 per industry sources.

Format for this report:
* **[Catalyst/Risk Name]** → [Impact with specific numbers and data points]
* ...

> **Analyst View**: [2-3 sentence paragraph on overall stock implication]

---

## Financial Materiality Mapping

Translate news into model levers with **quantified impact estimates**:

| Catalyst/Risk | Affected Lever | Direction | Δ Assumption | Valuation Impact | Notes |
| ------------- | -------------- | --------- | ------------ | ---------------- | ----- |
| Example: Q1 Beat | Revenue | ↑ | +2.5% NTM | +$18/share (+2.8%) | Raises FY guide |
| ...           | Revenue/Margin/WACC/Multiple | ↑/↓ | +/- X% | +/-$Y/share (Z%) | Driver |

**Instructions**:
- Provide rough estimates for valuation impact (e.g., "+$15-20/share" or "+2-3%")
- Use consistent assumptions: 
  - Revenue +1% NTM ≈ +$0.70-1.00/share for mega-caps (depends on multiple)
  - Sentiment shifts: -1% to -3% impact typical for insider selling concerns
  - Margin +50bps ≈ +$3-5/share
- **Ensure math is balanced**: A -1% revenue assumption should map to proportional $/share impact
- Skip if immaterial (<5% impact on lever)
- Be conservative with estimates

---

## Market Pricing Assessment

> **Alpha Opportunity**: [Is there a gap between news and market pricing?]
> 
> **Current Market View**: [What is the market pricing in based on price action?]
> 
> **News Implication**: [What should the market be pricing based on this news?]
> 
> **Gap Analysis**: [Bullish/Bearish/Neutral] — [Explanation of potential mispricings or opportunities]

Examples:
- "Upside from AI demand growth not fully priced — 2026 revenue estimates likely conservative. Positioning opportunity."
- "CEO stock sale concerns overblown — normal diversification. Price weakness creates entry point."
- "Earnings beat already priced in — stock up 8% in anticipation. Limited near-term upside."

---

## Peer & Market Sentiment Context

**Include peer price movements if available in peer_context data.**

Example format:
* **Peer Price Action**: AMD: -1.1% | TSMC: -0.4% | INTC: -0.8% — NVDA underperformed peers, suggesting insider selling concerns weighted heavily
* **Peer Impact**: [Which competitors are affected? How?]
* **Sector Reaction**: [Bullish/Neutral/Bearish - why?]
* **Relative Positioning**: [Is this company gaining or losing vs peers?]

---

## Risks & Watch Items (Last 24 Hours)

Include **multiple risks** when identified in the analysis. Categories:
- Insider selling / management concerns
- Regulatory / antitrust risks
- Competitive threats
- Operational / execution risks
- Valuation / sentiment risks

| Risk Trigger | Probability | Downside Potential | Current Status |
| ------------ | ----------- | ------------------ | -------------- |
| ...          | %           | Impact             | Watching/Escalating/Latent |

| Risk Trigger | Probability | Downside Potential | Current Status |
| ------------ | ----------- | ------------------ | -------------- |
| ...          | %           | Impact             | Watching/Escalating |

---

## Forward Watch — What to Monitor Next

| Trigger Event | Expected Timing | Signal to Watch | Potential Action |
| ------------- | --------------- | --------------- | ---------------- |
| ...           | Date/Timeline   | Metric/Event    | Hedge/Adjust model/Position |

---

### TL;DR: Key Takeaways

> 1. [Most important insight]
> 2. [Second most important insight]
> 3. [Third most important insight]

**Actionability Rating:** High/Medium/Low
**Is the market pricing this?** Yes/No — [Why]

---

## Guidelines for Report Generation

1. **Use ONLY the catalyst/risk data provided** - Don't make up news or extrapolate beyond what's given
2. **Verify consistency** - Check that all numbers are consistent (don't mix Q1/Q2 data)
3. **Cite specific articles** - Reference actual news sources with URLs when available
4. **Be quantitative** - Include specific numbers, percentages, timelines from articles
5. **Extract financial data** - Revenue figures, growth rates, margin data, dollar amounts
6. **Avoid generic statements** - Every claim should be traceable to specific news with data
7. **Calculate valuation impact** - Provide rough estimates of stock price impact
8. **Assess market pricing** - Is the news already priced in or is there alpha?
9. **Make it actionable** - Clear implications for investors
10. **Keep it concise** - Use bullets and tables, not long paragraphs
11. **Rank by materiality** - Most important news first
12. **Focus on what changed** - What's new in the last 24 hours
13. **Add analyst perspective** - Professional interpretation with conviction

**CRITICAL Quality Standards**:
- ❌ BAD: "Growing demand for AI products expected to boost revenue"
- ✅ GOOD: "Hyperscaler capex increasing 30% in 2026 ($75B→$97B), with NVDA GPU share at 85%, implies +$18B incremental revenue opportunity"

- ❌ BAD: "Strong earnings results"  
- ✅ GOOD: "Q1 revenue $26.0B (+35% YoY) vs $24.5B consensus, driven by data center segment at $22.6B (+427% YoY)"

- ❌ BAD: "Concerns over potential revenue misses" (speculative without source)
- ✅ GOOD: "Morgan Stanley analyst downgraded to Neutral citing order slowdown concerns" (specific source)

**ANTI-HALLUCINATION CHECKS**:
- ✅ Verify all numbers match the catalyst/risk data provided
- ✅ Check for consistency: Don't report both Q1 $26B and Q2 $46B unless articles explain
- ✅ Only include headlines that have supporting evidence in the articles list
- ✅ If a catalyst mentions "Q1 FY26", use exactly that - don't call it "Q2"
- ✅ Every financial figure MUST be traceable to the provided catalyst/risk/article data

Generate the complete report now.
