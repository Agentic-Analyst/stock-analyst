**STOCK ANALYST**

## Environment Setup

1. **Create and activate conda environment:**

```sh
conda create -n stock-analyst python=3.11 -y
conda activate stock-analyst
```

2. **Install dependencies:**

```sh
pip install -r requirements.txt
```

Or install individually:
```sh
pip install pyyaml python-slugify newspaper3k google-search-results lxml_html_clean
```

3. **Set API key (required for scraper):**

```sh
export SERPAPI_API_KEY='your_api_key_here'
```

On Windows:
```cmd
set SERPAPI_API_KEY=your_api_key_here
```

## Usage

1. **Scrape articles:**

```sh
python src/scraper.py --company "NVIDIA" --ticker NVDA --max 15
```

2. **Filter articles:**

```sh
python src/filter.py --ticker NVDA --min-score 5.0 --max-articles 8 --save-filtered --output-report
```

3. **Screen and analyze:**

```sh
python src/screener.py --ticker NVDA --min-confidence 0.7 --output-report --detailed-analysis
```

## Filter Logic

**Balanced Weighting:** Clear distribution of score components:
- Ticker mentions: up to 30%
- Relevance keywords: up to 40%
- Quality indicators: up to 20%
- Penalties: up to 30% deduction

**Score Distribution:**
- 0-3: Low relevance articles
- 3-5: Medium relevance articles  
- 5-7: High relevance articles
- 7-10: Extremely relevant articles

## Features

- **Autonomous News Collection:** Scrapes news and blog articles for any stock ticker
- **Smart Filtering:** Advanced relevance scoring based on content analysis
- **Investment Screening:** Extracts growth catalysts, risks, and mitigation strategies
- **Structured Reports:** Generates comprehensive markdown reports and JSON data
- **Configurable:** Adjustable confidence thresholds and output options