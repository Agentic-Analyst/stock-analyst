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
