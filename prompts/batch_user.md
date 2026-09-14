# Batch Analysis User Prompt

Please analyze the following {batch_size} articles for **{company_ticker}** to identify investment catalysts, risks, and mitigation strategies.

## Articles to Analyze:

{batch_content}

## Analysis Instructions:

1. **Read each article carefully** and identify key factors that could impact {company_ticker}'s stock performance
2. **For each insight you identify**, provide detailed reasoning and cite exact quotes from the articles
3. **Cross-reference information** across articles to build comprehensive insights
4. **Assess extraction confidence** based on source quality, independence, and
   clarity; do not express the probability of the predicted investment outcome
5. **Focus on actionable insights** that would matter to investors

## Key Focus Areas:

- **Growth Catalysts**: New products, market expansion, partnerships, technological advances, strong financials, and etc
- **Investment Risks**: Competitive threats, regulatory challenges, market headwinds, operational issues, and etc
- **Risk Mitigations**: Company strategies, market positions, defensive measures, management actions, and etc

Exclude shopping/availability guides, price momentum, technical buy points, and
generic market attention unless the article gives a concrete, quantified path to
the company's revenue, margins, cash flow, capital needs, or legal exposure.
Only call something a mitigation when the source documents that the company is
actually taking the action.

## Citation Requirements:

For every catalyst, risk, and mitigation:
- Provide the exact quote that supports your analysis
- Specify which article the quote comes from using the **article title** and **source URL** provided in the batch
- Explain your reasoning for why this matters
- Include your confidence assessment
- Use the article titles and URLs from the batch content, not the filename references

**Important**: When referencing articles, always use the actual article titles and source URLs provided in the batch content above, not the filename or article numbers.

Please respond with the complete JSON structure as specified in the system prompt.
