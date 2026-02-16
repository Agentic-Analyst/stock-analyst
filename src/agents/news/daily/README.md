# Company Daily News Intelligence Report

Professional 24-hour news analysis and report generation system for institutional investors.

## Overview

This system automatically generates concise, actionable daily reports analyzing the last 24 hours of news for any company. Designed for busy analysts who need quick intelligence each morning before market open.

## Features

### Core Capabilities
- ✅ **24-Hour News Screening**: Automatically fetches last 24h news from database
- ✅ **Batch LLM Analysis**: Identifies catalysts, risks, and mitigations
- ✅ **Peer Company Context**: Compares news flow to direct competitors
- ✅ **Materiality Ranking**: Ranks news by potential stock price impact
- ✅ **Financial Model Mapping**: Links news to revenue/margin/WACC levers
- ✅ **Professional Format**: Institutional-quality markdown reports

### Intelligence Extraction
- **Catalysts**: Product launches, partnerships, market expansion, financial beats
- **Risks**: Competitive threats, regulatory issues, operational problems
- **Mitigations**: Company actions to address risks
- **Sentiment Analysis**: Overall bullish/neutral/bearish assessment
- **Key Themes**: Recurring topics across multiple articles

### Report Sections
1. **Top Headlines** - Ranked by materiality with sentiment
2. **Impact Analysis** - "Why it matters" for each story
3. **Financial Materiality Mapping** - News → model levers
4. **Peer & Market Context** - Competitive positioning
5. **Risks & Watch Items** - New or escalating concerns
6. **Forward Watch** - What to monitor next
7. **TL;DR** - 3 key takeaways

## Usage

### Basic Usage
```bash
# Generate daily report for Apple
python src/agents/news/daily/company_daily_report.py --ticker AAPL

# Specify custom output directory
python src/agents/news/daily/company_daily_report.py --ticker NVDA --output reports/daily/

# Include company metadata
python src/agents/news/daily/company_daily_report.py \
    --ticker TSLA \
    --company-name "Tesla Inc" \
    --sector "Automotive"
```

### Programmatic Usage
```python
from src.agents.news.daily.company_daily_report import CompanyDailyReportGenerator
from pathlib import Path

# Create generator
generator = CompanyDailyReportGenerator(
    ticker="AAPL",
    output_dir=Path("reports/daily")
)

# Provide company info (optional but recommended)
company_info = {
    'company_name': 'Apple Inc',
    'sector': 'Technology',
    'industry': 'Consumer Electronics',
    'market_cap': '3.5T'
}

# Generate report
report_text = generator.generate_daily_report(company_info)

# Report is automatically saved to:
# reports/daily/AAPL_daily_report_YYYYMMDD.md
```

## Architecture

### Data Flow
```
1. Database (MongoDB) → Fetch last 24h news via vynn-core
2. Articles → Batch LLM analysis → Extract catalysts/risks/mitigations
3. LLM → Identify peer companies
4. Database → Fetch peer news for context
5. All data → LLM report generation → Professional markdown report
```

### LLM Workflow
```
┌─────────────────────────────────────────┐
│  Step 1: News Analysis (Batch)         │
│  - Input: All 24h articles              │
│  - Output: Catalysts, risks, mitigations│
│  - Prompt: daily_catalyst_analysis.md   │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  Step 2: Peer Identification            │
│  - Input: Company ticker/sector         │
│  - Output: List of 3-5 peer tickers     │
│  - Prompt: peer_identification.md       │
└─────────────────────────────────────────┘
                   ↓
┌─────────────────────────────────────────┐
│  Step 3: Report Generation              │
│  - Input: Analysis + peer context       │
│  - Output: Professional markdown report │
│  - Prompt: daily_report_generation.md   │
└─────────────────────────────────────────┘
```

## Database Schema

### Articles Collection (per ticker)
Collection name: `{TICKER}` (e.g., "AAPL", "NVDA")

```javascript
{
  "title": "Article headline",
  "url": "https://...",
  "source": "Bloomberg",
  "publish_date": "2025-10-30T04:23:15",  // ISO 8601 timestamp
  "text": "Full article text...",
  "summary": "Brief summary...",
  "entities": {
    "tickers": ["AAPL"],
    "keywords": ["iPhone", "earnings"]
  },
  "quality": {
    "llmScore": 8.5,
    "reason": "High relevance"
  }
}
```

### Key Database Functions (vynn-core)
- `get_last_24_hours_news(collection_name: str)` - Fetches articles from last 24h
- Uses UTC timestamps for accurate time filtering
- Automatically sorted by publish_date descending

## Prompts

All prompts are externalized in `prompts/` folder for easy customization:

### 1. `daily_catalyst_analysis.md`
**Purpose**: Extract catalysts, risks, and mitigations from news batch
**Input Variables**: `{company_ticker}`, `{num_articles}`, `{articles_content}`
**Output**: JSON with structured catalyst/risk/mitigation data

### 2. `daily_catalyst_user.md`
**Purpose**: User message for catalyst analysis
**Input Variables**: Same as above
**Output**: Analysis request with context

### 3. `peer_identification.md`
**Purpose**: Identify competitor companies for context
**Input Variables**: `{ticker}`, `{company_name}`, `{sector}`, `{industry}`, `{market_cap}`
**Output**: JSON with peer ticker list and reasoning

### 4. `daily_report_generation.md`
**Purpose**: System prompt for professional report writing style
**Output**: Sets tone, style, and structure guidelines

### 5. `daily_report_user.md`
**Purpose**: Generate final markdown report from analysis data
**Input Variables**: All analysis results, company info, peer context
**Output**: Complete professional markdown report

## Output Format

### Report File Naming
`{TICKER}_daily_report_{YYYYMMDD}.md`

Example: `AAPL_daily_report_20251030.md`

### Report Structure
```markdown
# 🗞️ Vynn AI — 24H Company News Intelligence Report

**Company:** Apple Inc (AAPL)
**Sector:** Technology
**Date:** 2025-10-30
**Analyst Reading Time:** ~2 mins

## 1️⃣ Top Headlines — Last 24 Hours
[Ranked table with materiality scores]

## 2️⃣ Why It Matters — Quick Impact Analysis
[Bullet points explaining business impact]

## 3️⃣ Financial Materiality Mapping
[Table linking news to model levers]

## 4️⃣ Peer & Market Sentiment Context
[Competitive positioning analysis]

## 5️⃣ Risks & Watch Items
[New/escalating risk table]

## 6️⃣ Forward Watch
[What to monitor next]

### 📌 TL;DR: Key Takeaways
[3 most important insights]
```

## Data Classes

### Catalyst
```python
@dataclass
class Catalyst:
    type: str                          # product|market|partnership|etc
    description: str                   # Clear catalyst description
    confidence: float                  # 0.0-1.0
    supporting_evidence: List[str]     # Quotes from articles
    timeline: str                      # immediate|short|medium|long
    potential_impact: str              # Expected stock/business impact
    reasoning: str                     # LLM's detailed reasoning
    direct_quotes: List[DirectQuote]   # Full quote objects
    source_articles: List[ArticleReference]  # Article references
```

### Risk
```python
@dataclass
class Risk:
    type: str                          # market|competitive|regulatory|etc
    description: str                   # Clear risk description
    severity: str                      # low|medium|high|critical
    confidence: float                  # 0.0-1.0
    supporting_evidence: List[str]     # Quotes from articles
    potential_impact: str              # Potential negative impact
    likelihood: str                    # low|medium|high
    reasoning: str                     # LLM's risk assessment
    direct_quotes: List[DirectQuote]   # Full quote objects
    source_articles: List[ArticleReference]  # Article references
```

### Mitigation
```python
@dataclass
class Mitigation:
    risk_addressed: str                # Which risk this addresses
    strategy: str                      # Mitigation strategy
    confidence: float                  # 0.0-1.0
    supporting_evidence: List[str]     # Supporting quotes
    effectiveness: str                 # low|medium|high
    company_action: str                # What company is doing
    implementation_timeline: str       # When mitigation expected
    reasoning: str                     # Why mitigation is effective
    direct_quotes: List[DirectQuote]   # Full quote objects
    source_articles: List[ArticleReference]  # Article references
```

## Cost Tracking

The system tracks LLM costs for each operation:

```python
# Typical costs (GPT-4o-mini)
- Catalyst analysis: ~$0.01-0.05 per batch
- Peer identification: ~$0.001-0.005
- Report generation: ~$0.02-0.10
# Total per report: ~$0.03-0.15
```

All costs are logged and accumulated in `generator.total_llm_cost`

## Logging

Uses `StockAnalystLogger` for structured logging:

```python
# Log levels
- INFO: Progress updates, results
- WARNING: Missing data, fallbacks
- ERROR: Exceptions, failures

# Log location
logs/{TICKER}/daily_report_{timestamp}.log
```

## Error Handling

### Graceful Degradation
- No articles found → Returns message, doesn't crash
- LLM parse errors → Returns empty lists, logs warning
- Database errors → Logs error, returns empty data
- Peer fetch failures → Continues without peer context

### Validation
- JSON response validation with fallbacks
- Token counting to prevent rate limits
- Article format validation
- Safe dataclass parsing with try/except

## Customization

### Modify Analysis Criteria
Edit `prompts/daily_catalyst_analysis.md`:
- Add new catalyst categories
- Change severity levels
- Adjust confidence thresholds
- Add industry-specific analysis

### Change Report Format
Edit `prompts/daily_report_user.md`:
- Modify section order
- Add custom sections
- Change table formats
- Adjust tone/style

### Adjust Peer Selection
Edit `prompts/peer_identification.md`:
- Change peer count (3-5 default)
- Modify selection criteria
- Add geographic filters
- Weight market cap differently

## Production Deployment

### Daily Automation
```bash
# Cron job example (runs at 7 AM daily)
0 7 * * * cd /path/to/stock-analyst && \
  python src/agents/news/daily/company_daily_report.py --ticker AAPL

# Multi-company batch
for ticker in AAPL NVDA TSLA MSFT; do
  python src/agents/news/daily/company_daily_report.py --ticker $ticker
done
```

### Integration with Pipeline
```python
# In your main pipeline
from src.agents.news.daily.company_daily_report import CompanyDailyReportGenerator

def generate_daily_reports_for_watchlist(tickers: List[str]):
    for ticker in tickers:
        generator = CompanyDailyReportGenerator(ticker=ticker)
        generator.generate_daily_report()
```

## Comparison to Existing Systems

### vs `article_screener.py`
- **Daily Report**: Focuses on last 24h, time-sensitive intelligence
- **Screener**: Analyzes arbitrary article sets, more comprehensive

### vs `report_agent.py`
- **Daily Report**: News-only, quick daily intelligence
- **Full Report**: Combines financials + models + news, comprehensive

### Complementary Use
```
1. Daily Report (Morning) → Quick news update
2. Full Report (Quarterly) → Complete analysis with financials
3. Screener (Ad-hoc) → Deep dive on specific news events
```

## Best Practices

### For Analysts
1. **Read TL;DR first** - Get main insights in 30 seconds
2. **Check materiality scores** - Focus on high-impact news
3. **Review peer context** - Understand competitive positioning
4. **Monitor forward watch** - Prepare for upcoming events

### For Developers
1. **Customize prompts** - Tailor to your specific needs
2. **Monitor costs** - Track LLM usage per ticker
3. **Cache peer lists** - Reuse peer identification across days
4. **Batch process** - Generate reports for multiple tickers together

## Future Enhancements

Potential additions:
- [ ] Historical trend comparison (7-day, 30-day)
- [ ] Sentiment score tracking over time
- [ ] Automatic email distribution
- [ ] PDF export for presentations
- [ ] Integration with Slack/Teams
- [ ] Custom alert triggers (high-severity risks)
- [ ] Multi-language support
- [ ] Chart generation (news volume, sentiment trends)

## Troubleshooting

### No articles found
```
Problem: "No articles found for {TICKER} in the last 24 hours"
Solution: 
- Verify ticker exists in database
- Check if news scraping is running
- Ensure publish_date timestamps are correct
```

### LLM JSON parse errors
```
Problem: "JSON decode error in catalyst_analysis"
Solution:
- Check LLM response format
- Verify prompt includes JSON schema
- Try with fewer articles (reduce batch size)
```

### High LLM costs
```
Problem: Report generation costs > $0.20
Solution:
- Reduce article count (filter by quality score)
- Use cheaper model (gpt-4o-mini)
- Batch multiple companies together
```

## License

Same as parent project.

---

**Status**: ✅ Production Ready
**Last Updated**: 2025-10-30
**Maintainer**: Vynn AI Team
