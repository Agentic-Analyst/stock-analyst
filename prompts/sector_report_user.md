# Sector Report Generation - User Prompt

## Report Generation Request

Generate a **professional daily sector intelligence report** for the **{sector} sector**.

## Input Data

### Sector Overview
- **Sector**: {sector}
- **Companies Monitored**: {num_companies}
- **Articles Analyzed**: {num_articles}
- **Date**: {date}

### Price Action Summary
```
{price_summary}
```

### Top Material Catalysts (Ranked by Materiality)
```
{catalysts_summary}
```

## Your Task

Generate a **complete, professional sector intelligence report** following the structure below:

---

# 📈 {sector} Sector — 24H News Intelligence Report

**Coverage Universe:** {num_companies} companies
**Date:** {date}
**Analyst Reading Time:** ~3 mins

---

## 0️⃣ Sector Price Action — What Moved?

[Create table with: Metric, Value, Δ vs Market]
- Sector 1-Day Move
- Top Gainer (ticker, %, driver)
- Top Laggard (ticker, %, driver)
- Sentiment (Bullish/Neutral/Bearish)
- Rotation Trend (Money Flow In/Out/Neutral)

**IMPORTANT**: If individual stock moves don't align with sector move, add 1-2 sentences explaining macro/market context:
- Example: "Broader risk-off market tone kept sector gains muted despite positive individual catalysts"
- Example: "Fed hawkishness and rising rates pressured sector despite strong company fundamentals"

---

## 1️⃣ Most Material Sector Catalysts — Last 24 Hours

[Create ranked table with top 5 catalysts]
Columns: Rank, Headline, Sub-Sector, Driver Type, Sentiment, Materiality %

---

## 2️⃣ Sector Impact — What Changed Financially?

[Create table analyzing financial levers]
Columns: Lever Affected, Direction, Magnitude, Commentary

Levers to analyze:
- Revenue Growth Outlook
- Margin Profile (only if news directly impacts margins)
- Regulatory Risk
- Cost of Capital / WACC
- **Valuation Multiples** (CRITICAL for sentiment-driven moves)

**IMPORTANT**: If price moved but fundamentals unchanged → cite valuation compression/expansion, not margin speculation.

**TL;DR:** [1-2 sentence summary of how sector fundamentals shifted]

---

## 3️⃣ Company-Level Movers & Drivers

[Create table showing top movers]
Columns: Ticker, 1-Day Move, Key News Catalyst, Sentiment, Actionability

**Actionability - Use institutional language**:
- NOT "Buy/Sell/Hold" 
- USE "Add/Reduce/Neutral", "Overweight/Underweight", "Accumulate/Take profit"
- Add nuance: "Underweight near-term; better entry later", "Bullish with China risk discount"

**Insights:**
- [Who led the rally/sell-off and why]
- [Competitive shifts inside sector]
- [Where alpha opportunities lie]

---

## 4️⃣ Thematic & Competitive Landscape Signals

[Create table showing key themes]
Columns: Theme, Signal Today, Thesis Impact, Watchpoint

Examples: AI Capex, Pricing Power, Regulation, Labor Costs

---

## 5️⃣ TL;DR: Sector Takeaways

> 1️⃣ [Most important signal/shift - SYNTHESIZE competing signals into coherent story]
> 2️⃣ [Where the rotation opportunities are - connect price action to positioning]
> 3️⃣ [Where major risk build-up is - forward-looking concerns]

**CRITICAL**: Tie together offsetting forces into unified sector narrative.
Example: "Apple strength offsets NVDA weakness, but China risk and valuation pressure keep Tech neutral overall"

🧠 **Sector Recommendation:** [Overweight / Neutral / Underweight]
🎯 **Highest Conviction Theme Today:** [Theme]
📍 **Where to Position:** [Sub-sector / Top tickers]

---

## Quality Standards for Your Report

✅ **Must Have:**
- Specific percentages, basis points, dollar amounts
- Clear cause-effect relationships (news → price action → fundamentals)
- Actionable investment recommendations
- Evidence from articles (specific quotes or data)
- Forward-looking insights (not just recaps)

✅ **Tone:**
- Professional sell-side analyst quality
- Confident but evidence-based
- Concise and scannable
- Action-oriented

❌ **Avoid:**
- Generic summaries without specifics
- Speculation without evidence
- Overly lengthy explanations
- Missing investment implications
- Unclear or vague language

## Additional Context

Use the price action data and catalyst analysis provided above to:
1. Connect news catalysts to price movements
2. Explain which catalysts are driving sector sentiment
3. Identify companies best/worst positioned
4. Provide clear sector rotation recommendations
5. Highlight emerging themes and risks

Generate the complete report now, formatted in clean markdown with tables and clear sections.
