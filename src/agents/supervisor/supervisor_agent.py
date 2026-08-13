#!/usr/bin/env python3
"""
supervisor_agent.py - Supervisor Agent for Chatbot Integration

This is the main entry point for running the LLM-powered supervisor workflow
that uses the Supervisor Agent to intelligently route between task agents.

The supervisor system provides:
- **Automatic ticker extraction** from natural language prompts
- LLM-powered dynamic routing (non-sequential, intelligent decisions)
- Session management for multi-turn chatbot conversations
- Prerequisite validation (prevents invalid routing)
- Deterministic fallback (when LLM fails or makes invalid choices)
- Complete observability (routing decisions, agent execution, results)
- State management (tracks what's completed, what's pending)
- Workflow completion detection (reaches __end__ node)

Workflow Architecture:
┌─────────────────────────────────────────────────────────────────┐
│                User Prompt (Natural Language)                   │
│        "Analyze Apple stock" or "What's NVDA's outlook?"        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌────────────────────────────────────────┐
        │      Ticker Extraction (LLM)           │
        │  - Extracts ticker symbol (AAPL, NVDA) │
        │  - Identifies company name             │
        └────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Supervisor Agent (LLM)                     │
│  - Reads current state                                          │
│  - Evaluates available data                                     │
│  - Decides next optimal agent                                   │
│  - Routes to: financial_data | model_generation |               │
│               news_analysis | report_generator | __end__        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌────────────────────────────────────────┐
        │      Task Agent Execution              │
        │  - financial_data_agent                │
        │  - model_generation_agent              │
        │  - news_analysis_agent                 │
        │  - report_generator_agent              │
        └────────────────────────────────────────┘
                              │
                              ▼
        ┌────────────────────────────────────────┐
        │      State Update & Next Iteration     │
        │  - Update FinancialState               │
        │  - Log agent completion                │
        │  - Return to supervisor                │
        └────────────────────────────────────────┘

▶ Usage (via main.py):
    # Natural language prompt - ticker auto-extracted
    python main.py --pipeline supervisor --prompt "Analyze Apple stock"
    
    # With email and timestamp
    python main.py --pipeline supervisor --prompt "What's NVDA's outlook?" --email user@example.com --timestamp 20250105_120000
    
    # Session management for chatbot continuity
    python main.py --pipeline supervisor --prompt "Tell me about Tesla" --session my_session

▶ Programmatic Usage (for chatbot):
    from src.agents.supervisor.supervisor_agent import SupervisorWorkflowRunner
    
    # First request (auto-generates session)
    runner = SupervisorWorkflowRunner(
        email="user@example.com",
        timestamp="20250105_120000",
        user_prompt="Analyze Apple stock"  # Ticker extracted automatically
    )
    results = await runner.run_workflow()
    session_id = results["session_name"]  # Save for next request
    
    # Follow-up request (reuse session)
    runner = SupervisorWorkflowRunner(
        email="user@example.com",
        timestamp="20250105_120500",
        user_prompt="What about the earnings?",
        session_name=session_id  # Resume conversation
    )
    results = await runner.run_workflow()
"""

from __future__ import annotations
import argparse
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
from src.logger import setup_logger
from src.path_utils import get_analysis_path, ensure_analysis_paths
from src.llms.config import init_llm, list_models, list_available_models
from src.session_manager import SessionManager

# Import supervisor workflow components
from src.agents.supervisor.state import FinancialState, AgentNode, PipelineStage, AnalysisObjective
from src.agents.supervisor.supervisor import route_workflow_with_llm, route_workflow
from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
from src.agents.supervisor.task_agents.news_analysis_agent import news_analysis_agent
from src.agents.supervisor.task_agents.model_generation_agent import model_generation_agent
from src.agents.supervisor.task_agents.report_generator_agent import report_generator_agent
from src.agents.supervisor.task_agents.financial_summary_agent import financial_summary_agent
from src.agents.supervisor.task_agents.news_summary_agent import news_summary_agent
from src.llms.config import get_llm
import yfinance as yf

from dotenv import load_dotenv
load_dotenv()

class SupervisorWorkflowRunner:
    """
    Orchestrates the LLM-powered agentic workflow with supervisor routing.
    """
    
    def __init__(self,
                 email: str,
                 timestamp: str,
                 user_prompt: str,
                 session_id: Optional[str] = None,
                 max_iterations: int = 10):
        """
        Initialize the supervisor workflow runner.
        
        Args:
            email: User's email for data organization
            timestamp: Timestamp for this analysis run (YYYYMMDD_HHMMSS)
            user_prompt: User's query/instructions (e.g., "Analyze Apple stock")
            session_id: Session ID for persistent conversation (optional)
                         If None, auto-generates unique session ID: {ticker}_{timestamp}
            max_iterations: Maximum workflow iterations to prevent infinite loops
        """
        self.email = email.lower()
        self.max_iterations = max_iterations
        self.user_prompt = user_prompt
        self.timestamp = timestamp
        self.session_name = session_id
        
        # Ticker and company will be extracted in first supervisor routing call
        # These will be set by _initialize_after_ticker_extraction()
        self.ticker = None
        self.company_name = None
        self.analysis_path = None
        self.logger = None
        self.state = None
        self.session_manager = None
        self.is_simple_query = False  # Track if this is a simple query vs comprehensive analysis
        self._answer_emitted = False  # Whether a user-facing answer has already been produced
        self._llm_objective = None  # Objective chosen by the iteration-1 triage LLM (if any)
        
        # Workflow statistics
        self.stats = {
            "start_time": datetime.now(),
            "iterations": 0,
            "agents_executed": [],
            "routing_decisions": [],
            "completion_status": "not_started"
        }
        
        # Track current conversation index for progressive saving
        self.current_conversation_index = None

    async def _run_model_and_news_concurrently(self, iteration: int) -> bool:
        """
        Run model_generation ∥ news_analysis concurrently (comprehensive fast-path).

        Precondition (checked by caller): financial data is collected and both the
        model and news are still pending. These two agents are independent — model
        reads the financials file and produces state.financial_model; news reads the
        ticker and produces state.news_analysis.

        Concurrency model: news_analysis is genuinely async (it awaits the parallel
        screener), while model_generation has no await points (CPU/IO-bound), so we
        run the model on a SHALLOW COPY of the state inside a worker thread and
        merge just its outputs back afterward. That keeps the two from racing on
        shared scalar fields (current_stage, total_llm_cost) — each writes its own
        copy — while still overlapping ~60s of modelling with ~44s of news.

        Returns True if it ran (both agents attempted); False to fall back to the
        normal single-agent dispatch (on any setup error).
        """
        import copy as _copy
        try:
            self.logger.info("")
            self.logger.info("[SUPERVISOR] ⚡ CONCURRENT: running model_generation ∥ news_analysis")
            self.logger.info("")

            start = datetime.now()
            model_state = _copy.copy(self.state)  # shallow: model only sets financial_model
            cost_before = self.state.total_llm_cost

            async def run_model():
                # model_generation_agent is async but blocking; drive it in a thread
                # so it doesn't stall the event loop while news awaits concurrently.
                def _drive():
                    return asyncio.run(model_generation_agent(model_state))
                return await asyncio.to_thread(_drive)

            async def run_news():
                return await news_analysis_agent(self.state)

            model_result, news_result = await asyncio.gather(
                run_model(), run_news(), return_exceptions=True
            )

            # Merge model outputs back onto the primary state.
            if isinstance(model_result, FinancialState):
                self.state.financial_model = model_result.financial_model
                # account for the model's LLM spend (it ran on the copy)
                self.state.total_llm_cost += max(0.0, model_result.total_llm_cost - cost_before)
                if model_result.last_error and not self.state.last_error:
                    self.state.last_error = model_result.last_error
            elif isinstance(model_result, Exception):
                self.logger.error(f"[SUPERVISOR] ❌ concurrent model_generation failed: {model_result}")
            # news_result already mutated self.state in place; surface exceptions.
            if isinstance(news_result, Exception):
                self.logger.error(f"[SUPERVISOR] ❌ concurrent news_analysis failed: {news_result}")

            # Reconcile stage: if both produced their artifact, we're past both.
            if self.state.is_model_generated() and self.state.is_news_analyzed():
                self.state.current_stage = PipelineStage.NEWS_ANALYSIS_COMPLETED

            dur = (datetime.now() - start).total_seconds()
            self.logger.info(
                f"[SUPERVISOR] ✅ Concurrent model+news done in {dur:.1f}s "
                f"(model={self.state.is_model_generated()}, news={self.state.is_news_analyzed()})"
            )
            # Record both in agent history for the summary/session.
            for name in ("model_generation_agent", "news_analysis_agent"):
                self.stats["agents_executed"].append({
                    "agent": name, "iteration": iteration,
                    "duration": dur, "timestamp": datetime.now().isoformat(),
                    "concurrent": True,
                })
            return True
        except Exception as e:
            self.logger.warning(
                f"[SUPERVISOR] ⚠️  Concurrent model+news path errored ({e}); "
                f"falling back to sequential."
            )
            return False

    def _resolve_objective(self, llm_objective):
        """
        Map the iteration-1 triage LLM's objective string to an AnalysisObjective.

        The LLM sees the full query, so its classification is the primary signal.
        We validate it against the enum; anything missing/invalid falls back to the
        deterministic keyword detector so a malformed LLM response can never leave
        us without an objective. Accepts common synonyms the model might emit.
        """
        from src.agents.supervisor.supervisor import _detect_user_intent

        if llm_objective:
            key = str(llm_objective).strip().lower().replace("-", "_")
            # Synonyms → canonical objective values.
            synonyms = {
                "comprehensive": AnalysisObjective.COMPREHENSIVE,
                "full": AnalysisObjective.COMPREHENSIVE,
                "full_analysis": AnalysisObjective.COMPREHENSIVE,
                "deep": AnalysisObjective.COMPREHENSIVE,
                "report": AnalysisObjective.COMPREHENSIVE,
                "model_only": AnalysisObjective.MODEL_ONLY,
                "model": AnalysisObjective.MODEL_ONLY,
                "financial_model": AnalysisObjective.MODEL_ONLY,
                "valuation": AnalysisObjective.MODEL_ONLY,
                "quick_news": AnalysisObjective.QUICK_NEWS,
                "news": AnalysisObjective.QUICK_NEWS,
                "news_only": AnalysisObjective.QUICK_NEWS,
                "sentiment": AnalysisObjective.QUICK_NEWS,
                "custom": AnalysisObjective.CUSTOM,
                "data": AnalysisObjective.CUSTOM,
                "data_only": AnalysisObjective.CUSTOM,
                "financial_data": AnalysisObjective.CUSTOM,
                "quote": AnalysisObjective.CUSTOM,
                "price": AnalysisObjective.CUSTOM,
            }
            if key in synonyms:
                return synonyms[key]
            # Also accept an exact enum value string.
            try:
                return AnalysisObjective(key)
            except ValueError:
                pass  # fall through to keyword detection

        return _detect_user_intent(self.user_prompt)

    def _initialize_after_ticker_extraction(self, ticker: str, company_name: str = None):
        """
        Complete initialization after ticker is extracted from first supervisor call.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')
            company_name: Company name (optional - will be fetched from yfinance if not provided)
        """
        self.ticker = ticker.upper()
        
        # Fetch company name from yfinance if not provided
        if company_name is None:
            try:
                stock = yf.Ticker(self.ticker)
                info = stock.info
                self.company_name = info.get('longName') or info.get('shortName') or self.ticker
                print(f"✅ Fetched company name from yfinance: {self.company_name}")
            except Exception as e:
                print(f"⚠️  Failed to fetch company name from yfinance: {e}")
                self.company_name = self.ticker
        else:
            self.company_name = company_name
        
        # Auto-generate session name if not provided (for chatbot continuity)
        if self.session_name is None:
            # Generate unique session ID using the timestamp: ticker_timestamp
            self.session_name = f"{self.ticker.lower()}_{self.timestamp}"
        
        # Initialize session manager (always enabled for chatbot support)
        # Sessions stored under user's email: data/{email}/sessions/{ticker}/{session_name}.json
        self.session_manager = SessionManager(email=self.email, ticker=self.ticker, session_name=self.session_name)
        
        # Generate analysis path
        self.analysis_path = get_analysis_path(self.email, self.ticker, self.timestamp)
        ensure_analysis_paths(self.analysis_path)
        
        # Setup logging - single info.log with session tracking
        self.logger = setup_logger(self.ticker, base_path=self.analysis_path, session_name=self.session_name)
        
        # 🔥 DETECT USER INTENT (triage). Prefer the LLM's classification from the
        # iteration-1 call — it reads the whole query, so it handles paraphrases and
        # ambiguity far better than substring matching, and it stops ambiguous
        # questions from silently defaulting to the full 6-minute comprehensive run.
        # Fall back to the keyword detector if the LLM didn't return a valid one.
        detected_objective = self._resolve_objective(self._llm_objective)
        
        # Initialize state (FinancialState requires: user_prompt, ticker, company_name, email)
        self.state = FinancialState(
            user_query=self.user_prompt,
            ticker=self.ticker,
            company_name=self.company_name,
            email=self.email,
            analysis_path=str(self.analysis_path),
            timestamp=self.timestamp,
            objective=detected_objective  # 🔥 Set objective based on user intent
        )
        
        self.logger.info("=" * 80)
        self.logger.info(f"[SUPERVISOR] 🎯 SUPERVISOR WORKFLOW INITIALIZED")
        self.logger.info("=" * 80)
        self.logger.info(f"[SUPERVISOR]    Ticker: {self.ticker}")
        self.logger.info(f"[SUPERVISOR]    Company: {self.company_name}")
        self.logger.info(f"[SUPERVISOR]    Objective: {detected_objective.value} {'🎯' if detected_objective.value != 'comprehensive' else '📊'}")
        self.logger.info(f"[SUPERVISOR]    Analysis Path: {self.analysis_path}")
        self.logger.info(f"[SUPERVISOR]    Max Iterations: {self.max_iterations}")
        self.logger.info(f"[SUPERVISOR]    Timestamp: {self.timestamp}")
        self.logger.info(f"[SUPERVISOR]    Session: {self.session_name}")
        conversation_count = len(self.session_manager.session_data.get("conversation_history", []))
        if conversation_count > 0:
            self.logger.info(f"[SUPERVISOR]    📚 Resuming session with {conversation_count} previous conversations")
        else:
            self.logger.info(f"[SUPERVISOR]    🆕 New session created")
        self.logger.info("=" * 80)
        
        # Start a new conversation immediately - saves user query even if program crashes
        self.current_conversation_index = self.session_manager.start_conversation(
            user_query=self.user_prompt,
            company_name=self.company_name
        )
        self.logger.info(f"[SUPERVISOR] 💾 Session conversation started (will be saved progressively)")
        self.logger.info("")
    
    def _check_for_immediate_answer(self, completed_agent: str) -> Optional[str]:
        """
        Check if we can provide an immediate answer to a simple query after an agent completes.
        
        Args:
            completed_agent: The agent that just completed
            
        Returns:
            Answer string if available, None otherwise
        """
        # Build context from available data
        context_parts = []
        
        # Add financial data if available
        if self.state.is_financial_data_collected() and self.state.financial_data:
            try:
                basic_info = self.state.financial_data.key_metrics.get("basic_info", {})
                market_data = self.state.financial_data.key_metrics.get("market_data", {})
                raw_data = self.state.financial_data.raw_data  # Full comprehensive data
                
                context_parts.append(f"**Financial Data for {self.ticker}:**")
                
                # Current market data
                if market_data.get("current_price"):
                    context_parts.append(f"- Current Stock Price: ${market_data['current_price']:.2f}")
                if market_data.get("market_cap"):
                    context_parts.append(f"- Market Cap: ${market_data['market_cap']:,.0f}")
                if market_data.get("trailing_pe"):
                    context_parts.append(f"- P/E Ratio: {market_data['trailing_pe']:.2f}")
                if market_data.get("forward_pe"):
                    context_parts.append(f"- Forward P/E: {market_data['forward_pe']:.2f}")
                if market_data.get("revenue"):
                    context_parts.append(f"- Revenue (TTM): ${market_data['revenue']:,.0f}")
                if basic_info.get("sector"):
                    context_parts.append(f"- Sector: {basic_info['sector']}")
                if basic_info.get("industry"):
                    context_parts.append(f"- Industry: {basic_info['industry']}")
                
                # Historical price data from raw_data (for price change calculations)
                historical_prices = raw_data.get("market_data", {}).get("historical_prices", {})
                
                # The structure is: historical_prices["prices"] = {"2020-11-09": {"close": 113.34, ...}, ...}
                if historical_prices and "prices" in historical_prices:
                    prices_dict = historical_prices["prices"]
                    if prices_dict and isinstance(prices_dict, dict):
                        # Convert dict to sorted list of (date, price_data) tuples
                        sorted_prices = sorted(prices_dict.items(), key=lambda x: x[0])
                        
                        if sorted_prices:
                            context_parts.append(f"\n**Historical Price Data (Available for calculations):**")
                            context_parts.append(f"- Total data points: {len(sorted_prices)}")
                            context_parts.append(f"- Date range: {sorted_prices[0][0]} to {sorted_prices[-1][0]}")
                            context_parts.append(f"- Price at start: ${sorted_prices[0][1]['close']:.2f}")
                            context_parts.append(f"- Price at end (current): ${sorted_prices[-1][1]['close']:.2f}")
                            
                            # Calculate key price changes
                            try:
                                from datetime import datetime, timedelta
                                current_date_str = sorted_prices[-1][0]
                                current_price = sorted_prices[-1][1]['close']
                                current_date = datetime.strptime(current_date_str, '%Y-%m-%d')
                                
                                # Find prices for different time periods
                                prices_by_period = {}
                                
                                for period_name, days_back in [("1 month", 30), ("3 months", 90), ("6 months", 180), ("1 year", 365)]:
                                    target_date = current_date - timedelta(days=days_back)
                                    # Find closest date in prices_dict
                                    closest_date = None
                                    min_diff = float('inf')
                                    
                                    for date_str in prices_dict.keys():
                                        price_date = datetime.strptime(date_str, '%Y-%m-%d')
                                        diff = abs((price_date - target_date).days)
                                        if diff < min_diff:
                                            min_diff = diff
                                            closest_date = date_str
                                    
                                    if closest_date and closest_date in prices_dict:
                                        past_price = prices_dict[closest_date]['close']
                                        change_dollar = current_price - past_price
                                        change_pct = (change_dollar / past_price) * 100
                                        prices_by_period[period_name] = {
                                            "date": closest_date,
                                            "price": past_price,
                                            "change_pct": change_pct,
                                            "change_dollar": change_dollar
                                        }
                                
                                if prices_by_period:
                                    context_parts.append(f"\n**Price Changes:**")
                                    for period, data in prices_by_period.items():
                                        context_parts.append(
                                            f"- Past {period}: ${data['change_dollar']:+.2f} ({data['change_pct']:+.2f}%) "
                                            f"from ${data['price']:.2f} on {data['date']}"
                                        )
                            except Exception as calc_error:
                                self.logger.warning(f"[SUPERVISOR] ⚠️  Could not calculate price changes: {calc_error}")
                                import traceback
                                self.logger.warning(f"[SUPERVISOR] {traceback.format_exc()}")
                    
                context_parts.append("")
            except Exception as e:
                self.logger.warning(f"[SUPERVISOR] ⚠️  Error extracting financial data: {e}")
        
        # Add news data if available
        if self.state.is_news_analyzed() and self.state.news_analysis:
            try:
                context_parts.append(f"**News Analysis for {self.ticker}:**")
                context_parts.append(f"- Articles Analyzed: {self.state.news_analysis.articles_count}")
                context_parts.append(f"- Overall Sentiment: {self.state.news_analysis.overall_sentiment}")
                if self.state.news_analysis.catalysts:
                    context_parts.append(f"- Top Catalysts:")
                    for catalyst in self.state.news_analysis.catalysts[:3]:
                        catalyst_text = catalyst if isinstance(catalyst, str) else catalyst.get("description", str(catalyst))
                        context_parts.append(f"  • {catalyst_text}")
                if self.state.news_analysis.risks:
                    context_parts.append(f"- Top Risks:")
                    for risk in self.state.news_analysis.risks[:3]:
                        risk_text = risk if isinstance(risk, str) else risk.get("description", str(risk))
                        context_parts.append(f"  • {risk_text}")
                context_parts.append("")
            except Exception as e:
                self.logger.warning(f"[SUPERVISOR] ⚠️  Error extracting news data: {e}")
        
        # Add valuation if available
        if self.state.is_model_generated() and self.state.financial_model:
            try:
                context_parts.append(f"**Valuation for {self.ticker}:**")
                context_parts.append(f"- Model Type: {self.state.financial_model.model_type}")
                
                val_metrics = self.state.financial_model.valuation_metrics
                if val_metrics.get("average_price"):
                    context_parts.append(f"- Fair Value: ${val_metrics['average_price']:.2f}")
                if val_metrics.get("upside_vs_market"):
                    context_parts.append(f"- Upside/Downside: {val_metrics['upside_vs_market']:+.2f}%")
                    
                context_parts.append("")
            except Exception as e:
                self.logger.warning(f"[SUPERVISOR] ⚠️  Error extracting valuation data: {e}")
        
        if not context_parts:
            return None
        
        # Build prompt for LLM to answer the simple query
        context_str = "\n".join(context_parts)
        
        prompt = f"""You are answering a specific question about {self.ticker}.

**User's Question:** {self.user_prompt}

**Available Data:**
{context_str}

**Instructions:**
- Answer the user's question DIRECTLY using the data above
- Provide the specific information requested along with relevant context
- If asking for stock price, include the price AND add 1-2 relevant metrics (P/E, market cap, or sector)
- If asking for a metric, provide it with brief context
- Be informative but concise (2-4 sentences)
- Be precise and data-driven - use actual numbers from the data
- If the specific data requested is not available, say so honestly

**Example Response Styles:**
- Stock price query: "NVDA is currently trading at $195.21. The company has a market cap of $4.8T and operates in the Semiconductors industry with a P/E ratio of 45.2."
- Metric query: "NVDA's P/E ratio is 45.2, which is higher than the industry average, reflecting strong growth expectations in the AI and semiconductor markets."

Provide a helpful, informative answer:"""

        try:
            response, cost = get_llm()([
                {"role": "system", "content": "You are a helpful financial assistant. Provide informative yet concise answers using data."},
                {"role": "user", "content": prompt}
            ], temperature=0.3)
            
            self.state.total_llm_cost += cost
            return response.strip()
            
        except Exception as e:
            self.logger.error(f"[SUPERVISOR] ⚠️  Failed to generate immediate answer: {e}")
            return None
    
    def _extract_ticker_and_route(self, user_prompt: str, conversation_context: Optional[str] = None) -> tuple[str, Optional[str], str, str, Optional[str], bool]:
        """
        First supervisor call: Extract ticker from prompt AND decide first routing.
        
        Args:
            user_prompt: User's natural language query
            conversation_context: Previous conversation history (optional)
            
        Returns:
            Tuple of (ticker, company_name, next_agent, reasoning, direct_answer, is_simple_query)
            Note: company_name will be None - fetched from yfinance in initialization
                  direct_answer will be populated if next_agent is __end__
                  is_simple_query indicates if this is a simple data request vs full analysis
        """
        
        # Load combined prompt for ticker extraction + routing
        prompt_file = Path("prompts/ticker_extraction_and_routing.md")
        prompt_template = prompt_file.read_text()
        
        # Format prompt
        prompt = prompt_template.format(
            user_prompt=user_prompt,
            conversation_context=conversation_context or "No previous conversation"
        )
        
        # Call LLM to extract ticker AND decide first agent
        response, cost = get_llm()([
            {"role": "system", "content": "You are a financial analysis supervisor. Extract ticker and decide first routing."},
            {"role": "user", "content": prompt}
        ], temperature=0)
        
        try:
            # Try to extract JSON from response (LLM might wrap it in markdown code blocks)
            response_text = response.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]  # Remove ```json
            if response_text.startswith("```"):
                response_text = response_text[3:]  # Remove ```
            if response_text.endswith("```"):
                response_text = response_text[:-3]  # Remove trailing ```
            
            response_text = response_text.strip()
            
            # Additional cleanup: Find the first '{' and last '}' to extract pure JSON
            # This handles cases where LLM adds extra text before/after JSON
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                response_text = response_text[start_idx:end_idx+1]
            
            # Parse JSON response
            result = json.loads(response_text)
            
            # Validate response - ticker and next_agent required
            if "ticker" not in result or "next_agent" not in result:
                raise ValueError("LLM response missing required fields (ticker, next_agent)")
            
            # Extract reasoning and direct_answer (will be logged after logger is initialized)
            reasoning = result.get("reasoning", "No reasoning provided")
            direct_answer = result.get("direct_answer", None)
            is_simple_query = result.get("is_simple_query", False)
            # LLM-chosen objective (the triage decision). Validated + mapped by the
            # caller; None here means "LLM didn't classify → fall back to keywords".
            objective = result.get("objective", None)

            # Return ticker, next_agent, reasoning, direct_answer, is_simple_query, objective
            return result["ticker"], None, result["next_agent"], reasoning, direct_answer, is_simple_query, objective
            
        except json.JSONDecodeError as e:
            # Log the raw response for debugging
            print(f"[SUPERVISOR] ❌ JSON DECODE ERROR: {e}")
            print(f"[SUPERVISOR] ❌ Raw LLM response (first 500 chars): {response[:500]}")
            print(f"[SUPERVISOR] ❌ Cleaned response text (first 500 chars): {response_text[:500]}")
            raise ValueError(
                f"Failed to parse LLM response as JSON. "
                f"Error: {e}. "
                f"Raw response: {response[:500]}"
            )
        except Exception as e:
            raise ValueError(
                f"Failed to extract ticker and route from prompt: '{user_prompt}'. "
                f"Error: {e}. "
                f"Please provide a clearer query mentioning the company name or ticker symbol."
            )
    
    async def run_workflow(self) -> Dict:
        """
        Run the complete LLM-powered agentic workflow.
        
        The workflow:
        1. Supervisor evaluates current state
        2. LLM decides next optimal agent
        3. Execute chosen agent
        4. Update state
        5. Repeat until __end__ or max iterations
        
        Returns:
            Dictionary with workflow results including:
            - ticker: Stock ticker symbol
            - company_name: Company name
            - session_name: Session ID for chatbot continuity (frontend should save this)
            - statistics: Workflow execution statistics
            - final_state: Completion status of all pipeline stages
        """
        print(f"🔍 Starting workflow with prompt: '{self.user_prompt}'")
        
        iteration = 0
        next_agent = None
        
        while iteration < self.max_iterations:
            iteration += 1
            self.stats["iterations"] = iteration
            
            # FIRST ITERATION: Extract ticker + route in one LLM call
            if iteration == 1:
                # Print before logger is initialized (logger not available yet)
                print("[SUPERVISOR] 📍 ITERATION 1: Extracting ticker and determining first agent...")
                
                try:
                    # Load conversation context BEFORE ticker extraction
                    # This allows LLM to infer ticker from previous conversations
                    conversation_context = None
                    if self.session_name:
                        try:
                            # Extract ticker from session_id to load the session file
                            # Format: ticker_timestamp (e.g., nvda_112)
                            parts = self.session_name.split('_')
                            if len(parts) >= 2:
                                temp_ticker = parts[0].upper()
                                # Create temporary session manager to load history
                                from src.session_manager import SessionManager
                                temp_session = SessionManager(
                                    email=self.email,
                                    ticker=temp_ticker,
                                    session_name=self.session_name
                                )
                                conversation_context = temp_session.get_conversation_summary(limit=3)
                                print(f"[SUPERVISOR] 📚 Loaded conversation context from session '{self.session_name}'")
                                print(f"[SUPERVISOR] 🔍 DEBUG - Conversation context preview:")
                                print(f"[SUPERVISOR] {conversation_context[:500]}...")  # Print first 500 chars
                        except Exception as e:
                            print(f"[SUPERVISOR] ⚠️  Could not load session context: {e}")
                    
                    # Combined ticker extraction + routing + intent triage.
                    # The LLM (which already reads the query) also picks the
                    # objective, replacing brittle keyword matching.
                    ticker, company_name, next_agent, reasoning, direct_answer, is_simple_query, llm_objective = self._extract_ticker_and_route(
                        self.user_prompt,
                        conversation_context
                    )

                    # Store the query type
                    self.is_simple_query = is_simple_query
                    # Stash the LLM's triage objective so initialization can use it.
                    self._llm_objective = llm_objective

                    # Validate ticker
                    if not ticker or ticker.strip() == "":
                        raise ValueError(
                            "Unable to determine ticker. "
                            "For follow-up questions, ensure you're using the same session-id and the session contains previous analysis."
                        )
                    
                    print(f"[SUPERVISOR] ✅ Identified ticker: {ticker}")

                    # 🆕 SPECIAL HANDLING FOR CONVERSATIONAL QUERIES
                    # If ticker is "CHAT", this is a conversational query (e.g., "hi", "what can you do?")
                    if ticker and ticker.upper() == "CHAT":
                        print(f"[SUPERVISOR] 💬 Conversational query detected")
                        print(f"[SUPERVISOR] 🤖 Providing introduction and guidance")
                        
                        # Initialize with CHAT ticker for logging purposes
                        self._initialize_after_ticker_extraction("CHAT", "Conversational Mode")
                        
                        # Log the conversation
                        self.logger.info("[SUPERVISOR] 💬 CONVERSATIONAL QUERY:")
                        self.logger.info(f"[SUPERVISOR]    \"{self.user_prompt}\"")
                        self.logger.info("")
                        self.logger.info("[SUPERVISOR] 🤖 INTRODUCTION & GUIDANCE:")
                        if not direct_answer:
                            # Never log the header and then... nothing.
                            direct_answer = (
                                "Hello! I can analyze stocks, build valuation "
                                "models, screen news, and answer market "
                                "questions. What would you like to look at?"
                            )
                        self._emit_answer(direct_answer)
                        self._answer_emitted = True
                        self.stats["completion_status"] = "conversational"

                        # FINALIZE before returning. This branch used to return
                        # with no session update and no terminal markers — every
                        # conversational run from Jul 24-Aug 1 hung the frontend
                        # on ANALYZING and left its session "in_progress".
                        try:
                            if self.session_manager is not None and \
                               self.current_conversation_index is not None:
                                self.session_manager.update_conversation(
                                    conversation_index=self.current_conversation_index,
                                    completion_status="completed",
                                    key_findings=(direct_answer or "")[:800],
                                )
                        except Exception as sess_err:
                            self.logger.error(
                                f"[SUPERVISOR] ⚠️ Conversational session save failed: {sess_err}"
                            )
                        if hasattr(self.logger, "program_end"):
                            self.logger.program_end()

                        # Return the conversational response
                        return {
                            "status": "conversational",
                            "message": direct_answer,
                            "ticker": "CHAT",
                            "company_name": "Conversational Mode",
                            "session_name": self.session_name,
                            "statistics": self.stats
                        }
                    
                    # Initialize everything now that we have ticker
                    # Note: company_name is None, will be fetched from yfinance
                    print(f"[SUPERVISOR] ✅ First agent: {next_agent}")
                    
                    self._initialize_after_ticker_extraction(ticker, company_name)
                    
                    # Now logger is available - log system messages and LLM reasoning
                    self.logger.info("[SUPERVISOR] ▶ STARTING AGENTIC WORKFLOW")
                    self.logger.info("")
                    self.logger.info("[SUPERVISOR] 💬 USER QUERY:")
                    self.logger.info(f"[SUPERVISOR]    \"{self.user_prompt}\"")
                    self.logger.info("")
                    self.logger.info("[SUPERVISOR] 🧠 Initial Analysis & Routing Decision:")
                    self.logger.info(f"[LLM] {reasoning}")
                    self.logger.info(f"[SUPERVISOR] → Routing to: {next_agent}")
                    self.logger.info("")
                    
                    # If this is a direct answer (follow-up question), emit it on the
                    # structured channel and end. Setting _answer_emitted prevents the
                    # final synthesis step from producing a second, redundant answer.
                    if next_agent == "__end__" and direct_answer:
                        self.logger.info("")
                        self.logger.info("[SUPERVISOR] 💡 DIRECT RESPONSE (from conversation context):")
                        self._emit_answer(direct_answer)
                        self._answer_emitted = True
                        self.stats["completion_status"] = "completed"
                        # Mark this as completed immediately - no agents needed
                        break
                    
                    # 🔥 CRITICAL FIX: Apply dependency resolution to first iteration too!
                    # The LLM might suggest model_generation_agent without realizing financial_data is needed
                    from src.agents.supervisor.supervisor import _resolve_dependencies
                    actual_next_agent, was_redirected, resolution_explanation = _resolve_dependencies(
                        self.state, next_agent, self.logger
                    )
                    
                    if was_redirected:
                        self.logger.warning(f"[DEPENDENCY RESOLVER] ⚠️  Initial LLM routing required correction")
                        self.logger.info(f"[DEPENDENCY RESOLVER] 🎯 LLM wanted: {next_agent}")
                        self.logger.info(f"[DEPENDENCY RESOLVER] ✅ Auto-corrected to: {actual_next_agent}")
                        self.logger.info(f"[DEPENDENCY RESOLVER] 📝 Reason: {resolution_explanation}")
                        self.logger.info("")
                        next_agent = actual_next_agent
                    
                except Exception as e:
                    print(f"[SUPERVISOR] ❌ Failed to extract ticker: {e}")
                    raise
                    
            else:
                # SUBSEQUENT ITERATIONS: Normal routing
                self.logger.info("─" * 80)
                self.logger.info(f"[SUPERVISOR] 📍 ITERATION {iteration}/{self.max_iterations}")
                self.logger.info("─" * 80)
                
                # Step 1: Supervisor routing decision (system log)
                self.logger.info("[SUPERVISOR] 🧠 Supervisor evaluating current state...")
                self.logger.info(f"[SUPERVISOR] Current state: financial_data={self.state.is_financial_data_collected()}, model={self.state.is_model_generated()}, news={self.state.is_news_analyzed()}, report={self.state.is_report_generated()}")
                
                try:
                    # Use LLM-powered routing (will log [LLM] messages internally)
                    # Pass conversation history if in a session
                    conversation_context = None
                    if self.session_manager:
                        conversation_context = self.session_manager.get_conversation_summary(limit=3)
                    
                    next_agent = route_workflow_with_llm(
                        self.state, 
                        logger=self.logger,
                        conversation_history=conversation_context
                    )
                    
                    routing_decision = {
                        "iteration": iteration,
                        "next_agent": next_agent,
                        "timestamp": datetime.now().isoformat()
                    }
                    self.stats["routing_decisions"].append(routing_decision)
                    
                except Exception as e:
                    self.logger.warning(f"[SUPERVISOR] ⚠️  LLM routing failed: {e}")
                    self.logger.info("[SUPERVISOR] 🔄 Falling back to deterministic routing...")
                    
                    # Fallback to deterministic routing
                    next_agent = route_workflow(self.state, logger=self.logger)
                    
                    routing_decision = {
                        "iteration": iteration,
                        "next_agent": next_agent,
                        "fallback": True,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    }
                    self.stats["routing_decisions"].append(routing_decision)
                    
                    self.logger.info(f"[SUPERVISOR] 📌 Fallback routing to: {next_agent}")
            
            # Step 2: Check for workflow completion
            if next_agent == "__end__":
                self.logger.info("")
                self.logger.info("[SUPERVISOR] " + "=" * 80)
                self.logger.info("[SUPERVISOR] 🎉 WORKFLOW COMPLETED SUCCESSFULLY")
                self.logger.info("[SUPERVISOR] " + "=" * 80)
                self.stats["completion_status"] = "completed"
                break
            
            # Step 2.5: CONCURRENT FAST-PATH (comprehensive runs).
            # Once financial data is collected, model_generation and news_analysis
            # are fully independent — model reads the financials file and writes
            # state.financial_model; news reads the ticker and writes
            # state.news_analysis. If the router picks either one while BOTH are
            # still pending (the normal comprehensive case), run them together so
            # ~60s of modelling overlaps ~44s of news instead of summing.
            if (
                next_agent in ("model_generation_agent", "news_analysis_agent")
                and self.state.objective == AnalysisObjective.COMPREHENSIVE
                and self.state.is_financial_data_collected()
                and not self.state.is_model_generated()
                and not self.state.is_news_analyzed()
            ):
                ran = await self._run_model_and_news_concurrently(iteration)
                if ran:
                    # Both agents accounted for; continue to next routing decision.
                    self.logger.info("")
                    continue

            # Step 3: Execute chosen agent
            self.logger.info("")
            self.logger.info(f"[SUPERVISOR] ▶ EXECUTING AGENT: {next_agent}")
            self.logger.info("")

            try:
                # Map agent names to agent functions (no separate loggers - all use main logger)
                agent_map = {
                    "financial_data_agent": financial_data_agent,
                    "news_analysis_agent": news_analysis_agent,
                    "model_generation_agent": model_generation_agent,
                    "report_generator_agent": report_generator_agent,
                    "financial_summary_agent": financial_summary_agent,
                    "news_summary_agent": news_summary_agent
                }

                agent_func = agent_map.get(next_agent)
                
                if agent_func is None:
                    self.logger.error(f"[SUPERVISOR] ❌ Unknown agent: {next_agent}")
                    self.stats["completion_status"] = "failed"
                    break
                
                # Log agent start (system log)
                self.logger.info(f"[SUPERVISOR] 🚀 Starting {next_agent} (iteration {iteration})")
                
                # Execute agent (async)
                agent_start = datetime.now()
                prev_state = self.state
                returned = await agent_func(self.state)
                agent_duration = (datetime.now() - agent_start).total_seconds()

                # Defensive: an agent MUST return a FinancialState. If it returns
                # a dict / None / anything else (a bug in that agent), keep the
                # prior state and record the error instead of crashing the whole
                # run with "'dict' object has no attribute 'last_error'" downstream.
                if isinstance(returned, FinancialState):
                    self.state = returned
                else:
                    self.logger.error(
                        f"[SUPERVISOR] ❌ {next_agent} returned {type(returned).__name__}, "
                        f"expected FinancialState — keeping prior state and marking failed."
                    )
                    self.state = prev_state
                    self.state.current_stage = PipelineStage.FAILED
                    self.state.last_error = (
                        f"{next_agent} returned an invalid state ({type(returned).__name__})"
                    )
                
                self.stats["agents_executed"].append({
                    "agent": next_agent,
                    "iteration": iteration,
                    "duration": agent_duration,
                    "timestamp": datetime.now().isoformat()
                })
                
                self.logger.info("")
                self.logger.info(f"[SUPERVISOR] ✅ Agent {next_agent} completed in {agent_duration:.2f}s")
                
                # Log state after agent execution (system logs)
                self.logger.info(f"[SUPERVISOR] 📊 State after {next_agent}:")
                self.logger.info(f"[SUPERVISOR]    - Financial data collected: {self.state.is_financial_data_collected()}")
                self.logger.info(f"[SUPERVISOR]    - Model generated: {self.state.is_model_generated()}")
                self.logger.info(f"[SUPERVISOR]    - News analyzed: {self.state.is_news_analyzed()}")
                self.logger.info(f"[SUPERVISOR]    - Report generated: {self.state.is_report_generated()}")
                self.logger.info(f"[SUPERVISOR]    - Current stage: {self.state.current_stage.value}")
                
                # Update session with progress after each agent completes
                routing_decisions = [agent["agent"] for agent in self.stats["agents_executed"]]
                self.session_manager.update_conversation(
                    conversation_index=self.current_conversation_index,
                    routing_decisions=routing_decisions,
                    completion_status="in_progress",
                    statistics={
                        "iterations": self.stats["iterations"],
                        "agents_count": len(self.stats["agents_executed"])
                    }
                )
                
                # Check if this is a simple query and we can answer immediately
                if self.is_simple_query:
                    immediate_answer = self._check_for_immediate_answer(next_agent)
                    if immediate_answer:
                        # Emit on the same structured channel as full-run synthesis
                        # so the frontend renders it identically (and it persists to
                        # answer.md). No separate final synthesis will run for this
                        # query — the immediate answer IS the answer.
                        self._emit_answer(immediate_answer)
                        self._answer_emitted = True
                        self.stats["completion_status"] = "completed"
                        # Mark as completed and end workflow
                        break
                
                # 🔥 ERROR RECOVERY: Check for errors and attempt recovery
                if self.state.last_error:
                    self.logger.error(f"[SUPERVISOR] ⚠️  Agent reported error: {self.state.last_error}")
                
                if self.state.current_stage == PipelineStage.FAILED:
                    # 🚀 SMART ERROR RECOVERY: Detect prerequisite failures and auto-fix
                    error_msg = self.state.last_error or ""
                    
                    # Pattern 1: Missing financial data for model generation
                    if "financial_data not collected" in error_msg.lower() and next_agent == "model_generation_agent":
                        self.logger.warning(f"[ERROR RECOVERY] 🔧 Detected missing prerequisite for {next_agent}")
                        self.logger.info(f"[ERROR RECOVERY] ✅ Auto-routing to financial_data_agent first")
                        self.logger.info("")
                        
                        # Reset the FAILED state - we're recovering
                        self.state.current_stage = PipelineStage.INITIALIZED
                        self.state.last_error = None
                        
                        # Force next iteration to go to financial_data_agent
                        # We'll continue the loop and let normal routing handle it
                        continue
                    
                    # Pattern 2: Missing financial data for news (though news can work without it for QUICK_NEWS)
                    elif "financial_data not collected" in error_msg.lower() and next_agent == "news_analysis_agent":
                        # Check if this is a QUICK_NEWS objective - if so, this shouldn't have failed
                        if self.state.objective == AnalysisObjective.QUICK_NEWS:
                            self.logger.error(f"[ERROR RECOVERY] ❌ news_analysis_agent failed for QUICK_NEWS (should not require financial_data!)")
                            self.logger.error(f"[ERROR RECOVERY] This is a bug - news analysis should work without financial data for QUICK_NEWS")
                        else:
                            # For other objectives, route to financial_data_agent first
                            self.logger.warning(f"[ERROR RECOVERY] 🔧 Detected missing prerequisite for {next_agent}")
                            self.logger.info(f"[ERROR RECOVERY] ✅ Auto-routing to financial_data_agent first")
                            self.logger.info("")
                            
                            self.state.current_stage = PipelineStage.INITIALIZED
                            self.state.last_error = None
                            continue
                    
                    # Pattern 3: Missing model for report generation
                    elif "model not generated" in error_msg.lower() and next_agent == "report_generator_agent":
                        self.logger.warning(f"[ERROR RECOVERY] 🔧 Detected missing prerequisite for {next_agent}")
                        self.logger.info(f"[ERROR RECOVERY] ✅ Will route to model_generation_agent (which will cascade to financial_data if needed)")
                        self.logger.info("")
                        
                        self.state.current_stage = PipelineStage.INITIALIZED
                        self.state.last_error = None
                        continue
                    
                    # If no recovery pattern matched, this is an unrecoverable error
                    self.logger.error(f"[SUPERVISOR] ❌ Workflow failed during {next_agent} (no recovery available)")
                    self.stats["completion_status"] = "failed"
                    
                    # Save session with failure state
                    if self.session_manager and self.current_conversation_index is not None:
                        routing_decisions = [agent["agent"] for agent in self.stats["agents_executed"]]
                        self.session_manager.update_conversation(
                            conversation_index=self.current_conversation_index,
                            routing_decisions=routing_decisions,
                            completion_status="failed",
                            error_message=self.state.last_error or f"Workflow failed during {next_agent}",
                            statistics={
                                "iterations": self.stats["iterations"],
                                "agents_count": len(self.stats["agents_executed"])
                            }
                        )
                    break
                
                self.logger.info("")
                
            except Exception as e:
                self.logger.error(f"[SUPERVISOR] ❌ Agent execution failed: {e}")
                self.logger.error(f"[SUPERVISOR]    Agent: {next_agent}")
                import traceback
                self.logger.error(f"[SUPERVISOR] {traceback.format_exc()}")
                self.stats["completion_status"] = "failed"
                
                # Save session with error state
                if self.session_manager and self.current_conversation_index is not None:
                    routing_decisions = [agent["agent"] for agent in self.stats["agents_executed"]]
                    self.session_manager.update_conversation(
                        conversation_index=self.current_conversation_index,
                        routing_decisions=routing_decisions,
                        completion_status="failed",
                        error_message=f"Agent {next_agent} execution failed: {str(e)}",
                        statistics={
                            "iterations": self.stats["iterations"],
                            "agents_count": len(self.stats["agents_executed"])
                        }
                    )
                break
        
        # Check if we hit max iterations
        if iteration >= self.max_iterations and next_agent != "__end__":
            self.logger.warning("")
            self.logger.warning("=" * 80)
            self.logger.warning(f"[SUPERVISOR] ⚠️  WORKFLOW STOPPED: Reached max iterations ({self.max_iterations})")
            self.logger.warning("=" * 80)
            self.stats["completion_status"] = "max_iterations_reached"
        
        # Calculate final statistics
        self.stats["end_time"] = datetime.now()
        self.stats["total_duration"] = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        # Finalize session data with completion status
        if self.session_manager and self.current_conversation_index is not None:
            # Extract routing decisions from stats
            routing_decisions = [agent["agent"] for agent in self.stats["agents_executed"]]
            
            # Generate key findings summary (brief)
            key_findings = None
            error_message = None
            analysis_results = None
            
            if self.stats["completion_status"] == "completed":
                key_findings = f"Completed analysis in {len(routing_decisions)} steps. "
                if self.state.is_report_generated():
                    key_findings += "Generated comprehensive report. "
                if self.state.is_news_analyzed():
                    key_findings += f"Analyzed {self.state.news_analysis.articles_count if self.state.news_analysis else 0} articles."
                
                # Extract rich context for LLM continuation
                analysis_results = {
                    "data_collected": {
                        "financial_data": self.state.is_financial_data_collected(),
                        "model_generated": self.state.is_model_generated(),
                        "news_analyzed": self.state.is_news_analyzed(),
                        "report_generated": self.state.is_report_generated()
                    }
                }
                
                # Add financial model details if available
                if self.state.financial_model:
                    valuation_metrics = self.state.financial_model.valuation_metrics
                    if valuation_metrics:
                        analysis_results["valuation"] = {
                            "model_type": self.state.financial_model.model_type,
                            "fair_value": valuation_metrics.get("fair_value"),
                            "current_price": valuation_metrics.get("current_price"),
                            "upside_downside": valuation_metrics.get("upside_vs_market")
                        }
                    else:
                        # Model generated but metrics not yet extracted
                        analysis_results["valuation"] = {
                            "model_type": self.state.financial_model.model_type,
                            "excel_path": self.state.financial_model.excel_path
                        }
                
                # Add news analysis summary if available
                if self.state.news_analysis:
                    analysis_results["news_summary"] = {
                        "articles_analyzed": self.state.news_analysis.articles_count,
                        "overall_sentiment": self.state.news_analysis.overall_sentiment,
                        "catalysts_count": len(self.state.news_analysis.catalysts) if self.state.news_analysis.catalysts else 0,
                        "risks_count": len(self.state.news_analysis.risks) if self.state.news_analysis.risks else 0,
                        "top_catalysts": self.state.news_analysis.catalysts[:3] if self.state.news_analysis.catalysts else [],
                        "top_risks": self.state.news_analysis.risks[:3] if self.state.news_analysis.risks else []
                    }
                
                # Add report details if available
                if self.state.report:
                    analysis_results["report"] = {
                        "report_type": self.state.report.report_type,
                        "report_path": self.state.report.report_path,
                        "generated_at": self.state.report.generated_at.isoformat() if self.state.report.generated_at else None,
                        "content_length": len(self.state.report.content) if self.state.report.content else 0
                    }
                
            elif self.stats["completion_status"] == "failed":
                error_message = self.state.last_error or "Workflow failed during execution"
                key_findings = f"Failed after {len(routing_decisions)} steps"
            
            # Update the conversation with final state
            self.session_manager.update_conversation(
                conversation_index=self.current_conversation_index,
                routing_decisions=routing_decisions,
                completion_status=self.stats["completion_status"],
                key_findings=key_findings,
                error_message=error_message,
                analysis_results=analysis_results,
                statistics={
                    "iterations": self.stats["iterations"],
                    "duration": self.stats["total_duration"],
                    "agents_count": len(self.stats["agents_executed"])
                }
            )
            
            conversation_count = len(self.session_manager.session_data.get("conversation_history", []))
            self.logger.info(f"💾 Session '{self.session_name}' saved with {conversation_count} total conversations")
        
        # Synthesize the final user-facing answer if the workflow completed, at
        # least one agent ran, and we haven't ALREADY produced an answer (simple
        # queries answer inline via _check_for_immediate_answer). This now covers
        # every completed multi-agent run — comprehensive, MODEL_ONLY, QUICK_NEWS,
        # CUSTOM — so the user always gets a direct reply, not just artifacts.
        if (self.stats["completion_status"] == "completed" and
                len(self.stats["agents_executed"]) > 0 and
                not self._answer_emitted):
            self._generate_performance_summary()
        
        # Log final summary
        self._log_workflow_summary()
        
        # Signal program completion with session ID for frontend
        self.logger.program_end()
        
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "session_name": self.session_name,  # Return session ID for frontend tracking
            "statistics": self.stats,
            "final_state": {
                "financial_data_collected": self.state.is_financial_data_collected(),
                "model_generated": self.state.is_model_generated(),
                "news_analyzed": self.state.is_news_analyzed(),
                "report_generated": self.state.is_report_generated()
            }
        }
    
    def _generate_performance_summary(self):
        """
        Synthesize a DIRECT answer to the user's question from the gathered data.

        This is the run's final, user-facing reply. It replaces the old
        "here's what I did" performance narration: instead of describing the
        process, it answers the literal question ({user_query}) grounded in the
        financial data / model / news that was collected, and emits it on a
        structured channel the frontend reads as the primary assistant message
        (wrapped in [ANSWER]…[/ANSWER], also persisted to answer.md).
        """
        try:
            # Load the answer-synthesis prompt (falls back to the legacy summary
            # prompt if the new one is somehow missing, so a partial deploy is safe).
            prompt_file = Path("prompts/answer_synthesis.md")
            if not prompt_file.exists():
                prompt_file = Path("prompts/supervisor_performance_summary.md")
            prompt_template = prompt_file.read_text()
            
            # Build list of completed agents for context
            completed_agents_list = [agent["agent"] for agent in self.stats["agents_executed"]]
            completed_agents_str = ", ".join(completed_agents_list) if completed_agents_list else "None"
            
            # ==================== FINANCIAL DATA SUMMARY ====================
            financial_data_summary = "Not collected"
            if self.state.is_financial_data_collected() and self.state.financial_data:
                try:
                    basic_info = self.state.financial_data.key_metrics.get("basic_info", {})
                    market_data = self.state.financial_data.key_metrics.get("market_data", {})
                    
                    parts = []
                    if basic_info.get("sector"):
                        parts.append(f"Sector: {basic_info['sector']}")
                    if basic_info.get("industry"):
                        parts.append(f"Industry: {basic_info['industry']}")
                    if market_data.get("market_cap"):
                        parts.append(f"Market Cap: ${market_data['market_cap']:,.0f}")
                    if market_data.get("current_price"):
                        parts.append(f"Current Price: ${market_data['current_price']:.2f}")
                    if market_data.get("trailing_pe"):
                        parts.append(f"P/E: {market_data['trailing_pe']:.2f}")
                    
                    if parts:
                        financial_data_summary = "Collected financial data. " + ", ".join(parts)
                    else:
                        financial_data_summary = "Collected financial data (basic metrics available)"
                except Exception as e:
                    self.logger.warning(f"[SUPERVISOR] Could not format financial data summary: {e}")
                    financial_data_summary = "Collected financial data"
            
            # ==================== FINANCIAL MODEL SUMMARY ====================
            financial_model_summary = "Not completed"
            if self.state.is_model_generated():
                try:
                    parts = []
                    valuation_metrics = self.state.financial_model.valuation_metrics
                    assumptions = self.state.financial_model.assumptions
                    
                    # Core valuation results
                    if valuation_metrics and valuation_metrics.get("fair_value"):
                        fair_value = valuation_metrics["fair_value"]
                        current_price = valuation_metrics.get("current_price")
                        upside_pct = valuation_metrics.get("upside_vs_market", 0) * 100
                        
                        parts.append(f"Generated {self.state.financial_model.model_type} valuation model")
                        parts.append(f"Fair Value: ${fair_value:.2f}")
                        
                        if current_price:
                            parts.append(f"Current Price: ${current_price:.2f}")
                            if abs(upside_pct) > 0.1:  # Only mention if significant
                                direction = "upside" if upside_pct > 0 else "downside"
                                parts.append(f"{abs(upside_pct):.1f}% {direction}")
                        
                        # Key model assumptions
                        if assumptions:
                            assumption_parts = []
                            if "wacc" in assumptions and assumptions["wacc"] is not None:
                                assumption_parts.append(f"WACC: {assumptions['wacc']*100:.2f}%")
                            if "terminal_growth" in assumptions and assumptions["terminal_growth"] is not None:
                                assumption_parts.append(f"Terminal Growth: {assumptions['terminal_growth']*100:.2f}%")
                            if "exit_multiple" in assumptions and assumptions["exit_multiple"] is not None:
                                assumption_parts.append(f"Exit Multiple: {assumptions['exit_multiple']:.1f}x")
                            
                            # Add revenue growth rates if available
                            if "revenue_growth_rates" in assumptions and assumptions["revenue_growth_rates"]:
                                growth_rates = assumptions["revenue_growth_rates"]
                                # Format as percentages
                                growth_str = ", ".join([f"{rate*100:.1f}%" for rate in growth_rates[:5]])  # FY1-FY5
                                assumption_parts.append(f"Revenue Growth (FY1-FY5): {growth_str}")
                            
                            if assumption_parts:
                                parts.append("Key assumptions: " + ", ".join(assumption_parts))
                        
                        financial_model_summary = ". ".join(parts)
                    else:
                        # Model generated but metrics not extracted
                        financial_model_summary = (
                            f"Generated {self.state.financial_model.model_type} valuation model "
                            f"(valuation metrics extraction pending)"
                        )
                except Exception as e:
                    self.logger.warning(f"[SUPERVISOR] Could not format financial model summary: {e}")
                    financial_model_summary = f"Generated {self.state.financial_model.model_type} valuation model"
            
            # ==================== NEWS ANALYSIS SUMMARY ====================
            news_analysis_summary = "Not completed"
            if self.state.is_news_analyzed() and self.state.news_analysis:
                try:
                    parts = []
                    
                    # Basic counts and sentiment
                    parts.append(f"Analyzed {self.state.news_analysis.articles_count} articles")
                    parts.append(f"Overall sentiment: {self.state.news_analysis.overall_sentiment}")
                    
                    # Detailed catalyst information
                    if self.state.news_analysis.catalysts:
                        parts.append(f"Identified {len(self.state.news_analysis.catalysts)} growth catalysts")
                        
                        # Extract top 3 catalysts with full details
                        for i, catalyst in enumerate(self.state.news_analysis.catalysts[:3], 1):
                            if isinstance(catalyst, dict):
                                cat_type = catalyst.get("type", "unknown")
                                cat_desc = catalyst.get("description", "")
                                cat_timeline = catalyst.get("timeline", "")
                                cat_confidence = catalyst.get("confidence", 0.0)
                                cat_impact = catalyst.get("potential_impact", "")
                                
                                catalyst_detail = f"Catalyst #{i}: {cat_type.upper()}"
                                if cat_desc:
                                    catalyst_detail += f" - {cat_desc[:150]}"
                                if cat_timeline:
                                    catalyst_detail += f" (Timeline: {cat_timeline})"
                                if cat_confidence > 0:
                                    catalyst_detail += f" [Confidence: {cat_confidence:.0%}]"
                                if cat_impact:
                                    catalyst_detail += f" (Impact: {cat_impact[:100]})"
                                
                                parts.append(catalyst_detail)
                    
                    # Detailed risk information
                    if self.state.news_analysis.risks:
                        parts.append(f"Identified {len(self.state.news_analysis.risks)} risks")
                        
                        # Extract top 3 risks with full details
                        for i, risk in enumerate(self.state.news_analysis.risks[:3], 1):
                            if isinstance(risk, dict):
                                risk_type = risk.get("type", "unknown")
                                risk_desc = risk.get("description", "")
                                risk_severity = risk.get("severity", "unknown")
                                risk_confidence = risk.get("confidence", 0.0)
                                risk_impact = risk.get("potential_impact", "")
                                
                                risk_detail = f"Risk #{i}: {risk_type.upper()}"
                                if risk_desc:
                                    risk_detail += f" - {risk_desc[:150]}"
                                if risk_severity:
                                    risk_detail += f" (Severity: {risk_severity})"
                                if risk_confidence > 0:
                                    risk_detail += f" [Confidence: {risk_confidence:.0%}]"
                                if risk_impact:
                                    risk_detail += f" (Impact: {risk_impact[:100]})"
                                
                                parts.append(risk_detail)
                    
                    # Add mitigation count if available
                    if self.state.news_analysis.mitigations:
                        parts.append(f"Found {len(self.state.news_analysis.mitigations)} mitigation strategies")
                    
                    # Include screening data path if available
                    if self.state.news_analysis.screening_data_path:
                        screening_path = Path(self.state.news_analysis.screening_data_path)
                        if screening_path.exists():
                            parts.append(f"Screening data saved to: {screening_path.name}")
                    
                    news_analysis_summary = ". ".join(parts) + "."
                    
                except Exception as e:
                    self.logger.warning(f"[SUPERVISOR] Could not format news analysis summary: {e}")
                    news_analysis_summary = (
                        f"Analyzed {self.state.news_analysis.articles_count} articles - "
                        f"Overall sentiment: {self.state.news_analysis.overall_sentiment}"
                    )
            
            # ==================== REPORT SUMMARY ====================
            report_summary = "Not completed"
            if self.state.is_report_generated() and self.state.report:
                try:
                    parts = ["Generated comprehensive analyst report"]
                    
                    if self.state.report.content:
                        content_length = len(self.state.report.content)
                        parts.append(f"{content_length:,} characters")
                    
                    if self.state.report.report_path:
                        report_path = Path(self.state.report.report_path)
                        parts.append(f"Saved to: {report_path.name}")
                    
                    if self.state.report.generated_at:
                        parts.append(f"Generated at: {self.state.report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    report_summary = ". ".join(parts)
                    
                except Exception as e:
                    self.logger.warning(f"[SUPERVISOR] Could not format report summary: {e}")
                    report_summary = "Generated comprehensive analyst report with investment recommendation"
            
            # Build summary prompt with state information
            summary_prompt = prompt_template.format(
                ticker=self.ticker,
                company_name=self.company_name,
                user_query=self.user_prompt,
                completed_agents=completed_agents_str,
                financial_data_summary=financial_data_summary,
                financial_model_summary=financial_model_summary,
                news_analysis_summary=news_analysis_summary,
                report_summary=report_summary
            )

            # Call LLM to synthesize the direct answer.
            summary_response, summary_cost = get_llm()([
                {"role": "system", "content": "You are a senior equity research analyst answering the user's question directly, grounded in the data provided."},
                {"role": "user", "content": summary_prompt}
            ], temperature=0.6)
            self.state.total_llm_cost += summary_cost
            answer_text = summary_response.strip()

            # Persist + emit the answer. It is emitted on a STRUCTURED channel:
            #   * [ANSWER]…[/ANSWER] markers so the frontend can render it as the
            #     primary assistant reply (not scraped from routing narration), and
            #   * still on the [LLM] line inside the markers for backward-compat
            #     with the existing extractNLContent() path during rollout.
            self._emit_answer(answer_text)
            self._answer_emitted = True
            self.logger.info(f"[SUPERVISOR] 📁 Full analysis saved to: {self.state.analysis_path}")
            self.logger.info(f"[SUPERVISOR] 💰 Total LLM cost: ${self.state.total_llm_cost:.4f}")
            self.logger.info("")

        except Exception as e:
            # If synthesis fails, log error but don't crash the run.
            self.logger.error(f"Failed to synthesize answer: {str(e)}")

    def _emit_answer(self, answer_text: str):
        """
        Emit the final user-facing answer on the structured channel and persist it.

        Writes ``answer.md`` into the run directory (durable, read by the admin
        run-detail view and any future API) and logs the answer bracketed by
        [ANSWER]…[/ANSWER] markers, with the text also on an [LLM] line so the
        existing frontend keeps working during the transition.
        """
        if not answer_text:
            return
        # Persist to answer.md (best-effort — never break the run on I/O error).
        try:
            answer_path = Path(self.state.analysis_path) / "answer.md"
            answer_path.parent.mkdir(parents=True, exist_ok=True)
            answer_path.write_text(answer_text, encoding="utf-8")
        except Exception as e:
            self.logger.warning(f"[SUPERVISOR] Could not write answer.md: {e}")

        self.logger.info("")
        self.logger.info("[ANSWER_BEGIN]")
        # Emit each line under [LLM] so multi-line answers survive log-line parsing.
        for line in answer_text.split("\n"):
            self.logger.info(f"[LLM] {line}")
        self.logger.info("[ANSWER_END]")
        self.logger.info("")
    
    def _log_workflow_summary(self):
        """Log a comprehensive workflow summary."""
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("📊 WORKFLOW SUMMARY")
        self.logger.info("=" * 80)
        self.logger.info(f"   Ticker: {self.ticker} ({self.company_name})")
        self.logger.info(f"   Status: {self.stats['completion_status']}")
        self.logger.info(f"   Total Duration: {self.stats['total_duration']:.2f}s")
        self.logger.info(f"   Iterations: {self.stats['iterations']}")
        self.logger.info(f"   Agents Executed: {len(self.stats['agents_executed'])}")
        self.logger.info("")
        self.logger.info("   Completed Stages:")
        self.logger.info(f"      ✓ Financial Data: {self.state.is_financial_data_collected()}")
        self.logger.info(f"      ✓ Financial Model: {self.state.is_model_generated()}")
        self.logger.info(f"      ✓ News Analysis: {self.state.is_news_analyzed()}")
        self.logger.info(f"      ✓ Report Generated: {self.state.is_report_generated()}")
        self.logger.info("")
        
        if self.stats["agents_executed"]:
            self.logger.info("   Agent Execution History:")
            for i, agent_exec in enumerate(self.stats["agents_executed"], 1):
                self.logger.info(f"      {i}. {agent_exec['agent']} ({agent_exec['duration']:.2f}s)")
        
        self.logger.info("=" * 80)
        self.logger.info("")

