**STOCK ANALYST**

1. Set up:

```sh
conda run -n base pip install google-search-results
conda run -n base pip install lxml_html_clean
conda run -n base pip install newspaper3k
```

```sh
$env:SERPAPI_API_KEY='your_api_key_here'
```

2. Usage: 

```sh
conda run -n base python src/scraper.py --company "NVIDIA" --ticker NVDA --max 15
```

3. Filter logic:

Balanced Weighting: Clear distribution of score components:
Ticker mentions: up to 30%
Relevance keywords: up to 40%
Quality indicators: up to 20%
Penalties: up to 30% deduction

Score Distribution:
0-3: Low relevance articles
3-5: Medium relevance articles
5-7: High relevance articles
7-10: Extremely relevant articles