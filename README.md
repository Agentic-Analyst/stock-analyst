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

3. **Set API keys:**

```sh
export SERPAPI_API_KEY='your_api_key_here'
export OPENAI_API_KEY='your_openai_key_here'
export ANTHROPIC_API_KEY='your_anthropic_key_here'  # Optional: for Claude models
```

On Windows:
```cmd
set SERPAPI_API_KEY=your_api_key_here
set OPENAI_API_KEY=your_openai_key_here
set ANTHROPIC_API_KEY=your_anthropic_key_here
```

## Update of `vynn_core`
```sh
pip install --upgrade --force-reinstall git+https://github.com/Agentic-Analyst/vynn-core.git
```

4. **Deploy to server:**

```sh
docker buildx build --platform linux/amd64,linux/arm64 \
-t fuzanwenn/stock-analyst:latest --push .

docker pull fuzanwenn/stock-analyst:latest
```

## Usage

1. **Scrape articles:**

```sh
python src/article_scraper.py --company "NVIDIA" --ticker NVDA --max 15
```

2. **Filter articles:**

```sh
python src/filter.py --ticker NVDA --min-score 5.0 --max-articles 8 --save-filtered --output-report
```

3. **Screen and analyze:**

```sh
python src/screener.py --ticker NVDA --min-confidence 0.7 --output-report --detailed-analysis
```

4. **Scrape financial data:**

```sh
python src/financial_scraper.py --ticker NVDA --statements modeling --save
```

5. **Generate financial models:**

```sh
python src/financial_model_generator.py --ticker NVDA --model comprehensive --save-excel
```

6. **Complete pipeline with LLM selection:**

```sh
# Default model
python main.py --ticker NVDA --company "NVIDIA" --email user@example.com --timestamp 20241003_120000

# Use specific model
python main.py --ticker NVDA --company "NVIDIA" --email user@example.com --timestamp 20241003_120000 --llm claude-3.5-sonnet

# List available models
python main.py --list-llms
```

## Multi-LLM Support

The pipeline now supports multiple LLM providers:

**Available Models:**
- `gpt-4o-mini` (OpenAI) - Fast and cost-effective
- `claude-3.5-sonnet` (Anthropic) - Balanced quality/speed  
- `claude-3.5-haiku` (Anthropic) - Fastest and cheapest
- `claude-3-opus` (Anthropic) - Most capable

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

- **Multi-LLM Support:** Choose between OpenAI GPT-4o-mini and Anthropic Claude models
- **Autonomous News Collection:** Comprehensive multi-aspect news scraping with AI-powered query generation
- **Smart Filtering:** Advanced relevance scoring based on content analysis  
- **Investment Screening:** Extracts growth catalysts, risks, and mitigation strategies
- **Financial Data Collection:** Comprehensive financial statements and market data scraping
- **LLM-Powered Financial Modeling:** Generates professional DCF models and valuation analysis
- **Professional Analyst Reports:** AI-generated comprehensive financial reports
- **Excel/CSV Export:** Professional financial models in Excel format ready for analysis
- **Structured Reports:** Generates comprehensive markdown reports and JSON data
- **Complete Pipeline:** End-to-end workflow from news analysis to financial modeling
- **Configurable:** Adjustable confidence thresholds, LLM selection, and output options