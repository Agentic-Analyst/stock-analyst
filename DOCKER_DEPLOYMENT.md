# 🐳 Docker Deployment Guide

## ✅ Successfully Built and Pushed!

The stock-analyst Docker image has been successfully built and pushed to Docker Hub:

**Docker Hub Repository:** `fuzanwenn/stock-analyst`

**Available Tags:**
- `fuzanwenn/stock-analyst:latest` - Latest stable version
- `fuzanwenn/stock-analyst:2025-08-25` - Dated release version

**Image Size:** ~975MB
**Base Image:** python:3.11-slim

---

## 🚀 Usage Options

### 1. Direct Docker Run
```bash
# Quick help
docker run --rm fuzanwenn/stock-analyst:latest --help

# Run comprehensive analysis
docker run --rm \
  -v $(pwd)/data:/data \
  -e SERPAPI_API_KEY=your_key_here \
  -e OPENAI_API_KEY=your_key_here \
  fuzanwenn/stock-analyst:latest \
  --ticker NVDA --company "NVIDIA" --pipeline comprehensive
```

### 2. Docker Compose (Recommended)
```bash
# Set environment variables
export SERPAPI_API_KEY="your_serpapi_key"
export OPENAI_API_KEY="your_openai_key"

# Run with docker-compose
docker-compose run --rm stock-analyst --ticker AAPL --company "Apple Inc" --pipeline comprehensive
```

### 3. Development Mode
```bash
# Interactive development container
docker-compose run --rm stock-analyst-dev
```

---

## 📁 Volume Mapping

The container uses `/data` as the working directory for all outputs:
- Financial data: `/data/{TICKER}/financials/`
- News articles: `/data/{TICKER}/searched/`
- Filtered articles: `/data/{TICKER}/filtered/`
- Analysis reports: `/data/{TICKER}/`
- Financial models: `/data/{TICKER}/models/`
- Explanation reports: `/data/{TICKER}/models/price_adjustment_explanation_*.md`

**Local Mapping:** `./data:/data` (as configured in docker-compose.yml)

---

## 🔑 Required Environment Variables

- `SERPAPI_API_KEY` - For Google News scraping
- `OPENAI_API_KEY` - For LLM-powered analysis and explanation reports

---

## 🎯 Pipeline Features Included

✅ **Always Enabled Features:**
- Deterministic event→parameter mapping
- LLM scenario generation  
- Comprehensive explanation reports
- Excel model exports
- Real-time logging

✅ **Available Pipelines:**
- `comprehensive` - Full 6-step analysis (default)
- `financial-only` - Financial scraping + model generation
- `model-only` - Generate financial model only
- `news-only` - News analysis only
- `model-to-price` - Model generation through price adjustment
- `news-to-price` - News analysis through price adjustment

---

## 📊 Example Commands

```bash
# Full analysis with custom parameters
docker run --rm -v $(pwd)/data:/data \
  -e SERPAPI_API_KEY=$SERPAPI_API_KEY \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  fuzanwenn/stock-analyst:latest \
  --ticker TSLA --company "Tesla" \
  --pipeline comprehensive \
  --model dcf --years 5 \
  --scaling 0.12 --adjustment-cap 0.25

# Financial model only
docker run --rm -v $(pwd)/data:/data \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  fuzanwenn/stock-analyst:latest \
  --ticker AAPL --company "Apple Inc" \
  --pipeline financial-only --model comparable

# Check existing data status
docker run --rm -v $(pwd)/data:/data \
  fuzanwenn/stock-analyst:latest \
  --ticker NVDA --company "NVIDIA" --stats
```

---

## 🔄 Updating the Image

To pull the latest version:
```bash
docker pull fuzanwenn/stock-analyst:latest
```

To use a specific dated version:
```bash
docker pull fuzanwenn/stock-analyst:2025-08-25
```

---

## ✨ What's New in This Version

- ✅ Cleaned up CLI parameters (removed redundant flags)
- ✅ LLM-powered explanation reports always enabled
- ✅ Deterministic event mapping always enabled  
- ✅ Streamlined parameter structure
- ✅ Enhanced financial model exports
- ✅ Comprehensive logging and audit trails
- ✅ Production-ready Docker configuration

---

**Ready for production use! 🎉**
