# Batch Analysis User Prompt

Please analyze the following {batch_size} articles for **{company_ticker}** to identify investment catalysts, risks, and mitigation strategies.

## Articles to Analyze:

{batch_content}

## Analysis Instructions:

1. **Read each article carefully** and identify key factors that could impact {company_ticker}'s stock performance
2. **For each insight you identify**, provide detailed reasoning and cite exact quotes from the articles
3. **Cross-reference information** across articles to build comprehensive insights
4. **Assess confidence levels** based on the strength and clarity of the evidence
5. **Focus on actionable insights** that would matter to investors

## Key Focus Areas:

- **Growth Catalysts**: New products, market expansion, partnerships, technological advances, strong financials, and etc
- **Investment Risks**: Competitive threats, regulatory challenges, market headwinds, operational issues, and etc
- **Risk Mitigations**: Company strategies, market positions, defensive measures, management actions, and etc

## Citation Requirements:

For every catalyst, risk, and mitigation:
- Provide the exact quote that supports your analysis
- Specify which article the quote comes from using the **article title** and **source URL** provided in the batch
- Explain your reasoning for why this matters
- Include your confidence assessment
- Use the article titles and URLs from the batch content, not the filename references

**Important**: When referencing articles, always use the actual article titles and source URLs provided in the batch content above, not the filename or article numbers.

Please respond with the complete JSON structure as specified in the system prompt.