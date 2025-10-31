# Sector Catalyst Analysis - User Prompt

## Analysis Request

Analyze the following **{sector} sector news** from the last 24 hours to identify **material sector-wide catalysts**.

## Sector Context

- **Sector**: {sector}
- **Companies Monitored**: {num_companies}
- **Total Articles**: {num_articles}
- **Analysis Period**: Last 24 hours

## Price Action Context

```
{price_data_summary}
```

## News Articles

{articles_content}

## Your Task

1. **Identify Top Sector Catalysts** (materiality score ≥ 50)
   - Focus on events affecting multiple companies or the entire sector
   - Rank by financial impact (materiality score 0-100)
   - **CRITICAL**: Include BOTH positive AND negative catalysts
   - If sector moved down, identify bearish catalysts (macro, regulation, valuation)
   - If sector moved up, identify bullish catalysts (earnings, demand, innovation)
   - Limit to top 10 most material catalysts

2. **For Each Catalyst, Provide:**
   - Clear headline summarizing the catalyst
   - Sub-sector affected (e.g., "Cloud", "Semiconductors", "Biotech")
   - Driver type (demand, earnings, regulation, technology, macro)
   - Sentiment (positive, neutral, negative)
   - Materiality score (0-100)
   - List of affected company tickers
   - Impact description explaining financial implications
   - Supporting article titles as evidence

3. **Ensure Narrative Coherence:**
   - Match catalyst sentiment mix to actual price action
   - If price action is negative but news is positive, identify macro/valuation headwinds
   - If price action is positive but news is negative, identify rotation/oversold dynamics
   - Explain contradictions explicitly

4. **Sector Summary:**
   - Overall sector sentiment (bullish, neutral, bearish)
   - Top 3-5 key themes emerging from the news
   - Number of articles and companies analyzed

## Output Format

Return ONLY a valid JSON object matching this structure:

```json
{{
  "catalysts": [
    {{
      "headline": "string",
      "sub_sector": "string",
      "driver_type": "demand|earnings|regulation|technology|macro",
      "sentiment": "positive|neutral|negative",
      "materiality_score": 0-100,
      "affected_companies": ["TICKER1", "TICKER2"],
      "impact_description": "string",
      "supporting_articles": ["article title 1", "article title 2"]
    }}
  ],
  "sector_summary": {{
    "overall_sentiment": "bullish|neutral|bearish",
    "key_themes": ["theme1", "theme2", "theme3"],
    "articles_analyzed": {{num_articles}},
    "companies_covered": {{num_companies}}
  }}
}}
```

## Quality Standards

✅ **Do:**
- Focus on sector-wide or multi-company catalysts
- Quantify financial impact when possible
- Use specific evidence from articles
- Explain investment implications clearly
- Connect price action to news catalysts

❌ **Don't:**
- Include company-specific news with no sector spillover
- Speculate without evidence
- Repeat similar catalysts
- Include materiality scores below 50
- Use vague or unclear impact descriptions

Now analyze the {sector} sector news and return your analysis in the JSON format specified above.
