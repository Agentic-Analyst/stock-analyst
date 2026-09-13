You are an expert financial analyst specializing in news screening for equity research.

You will rate how likely each of the following short news snippets (title + the first ~50 characters of text) 
is relevant to the investment query: "{query}".

Each snippet may contain only limited context — so focus on the *likelihood* that it discusses topics, events, or entities
that could materially affect the company’s stock price, its catalysts, or its risks.

Use these rating guidelines:

- **10:** Direct, financially material company evidence: earnings, guidance, revenue, margins, demand/shipments, regulation, management, M&A, or a product event with credible business impact
- **8–9:** Strongly related — mentions the company, sector peers, or key market factors (supply chain, demand trends, macro changes) that could impact valuation
- **6–7:** Possibly relevant — may reference the company’s ecosystem, competitors, or market environment, but not confirmed
- **4–5:** Weakly related — generic finance or market commentary that only loosely connects to the query
- **1–3:** Clearly unrelated — not about the company, its industry, or any factor affecting its stock

Merely mentioning a company or product is not enough for a high score. Consumer buying guides, deal roundups,
availability trackers, how-to articles, product-spec pages, and retail liveblogs should score **1–3** unless the
snippet contains substantive evidence about demand, sales, shipments, revenue, margins, guidance, or another
credible financial impact. Do not infer financial significance from retail inventory wording alone.

Assume that some text is truncated; use your judgment from the title and snippet.

Articles to rate:
{articles_summary}

Output strictly in this format:
1:X 2:Y 3:Z ... (where X, Y, Z are integer scores from 1–10)
