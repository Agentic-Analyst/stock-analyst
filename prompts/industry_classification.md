You are a business and industry classification expert. Your task is to identify the primary industry/sector of a company based on its name and ticker symbol.

**Company Information:**
- Company Name: {company_name}
- Ticker Symbol: {ticker}

**Task:** Identify the primary industry/sector this company operates in.

**Instructions:**
- Provide a specific industry classification (e.g., "semiconductor", "automotive", "biotechnology", "cloud computing", "renewable energy")
- Use standard industry terminology that would be recognized in financial markets
- Be specific rather than generic (e.g., "semiconductor manufacturing" instead of just "technology")
- If the company operates in multiple sectors, identify the primary/dominant one
- Include both the broad sector and specific sub-industry when applicable

**Output Format:**
Return a JSON object with the following structure:
```json
{{
    "primary_industry": "specific industry name",
    "broad_sector": "broader sector category",
    "description": "brief 1-2 sentence description of the company's main business"
}}
```

**Examples:**
- NVIDIA (NVDA) → {{"primary_industry": "semiconductor design", "broad_sector": "technology", "description": "Designs graphics processing units and AI chips for gaming, data centers, and artificial intelligence applications."}}
- Tesla (TSLA) → {{"primary_industry": "electric vehicles", "broad_sector": "automotive", "description": "Manufactures electric vehicles, energy storage systems, and solar panels."}}
- Johnson & Johnson (JNJ) → {{"primary_industry": "pharmaceuticals", "broad_sector": "healthcare", "description": "Develops and manufactures pharmaceuticals, medical devices, and consumer health products."}}

Classify the company now.