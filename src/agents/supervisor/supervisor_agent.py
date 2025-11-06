#!/usr/bin/env python3
"""
supervisor_agent.py - Supervisor Agent Entry Point

This is the main entry point for running the LLM-powered supervisor workflow
that uses the Supervisor Agent to intelligently route between task agents.

The supervisor system provides:
- LLM-powered dynamic routing (non-sequential, intelligent decisions)
- Prerequisite validation (prevents invalid routing)
- Deterministic fallback (when LLM fails or makes invalid choices)
- Complete observability (routing decisions, agent execution, results)
- State management (tracks what's completed, what's pending)
- Workflow completion detection (reaches __end__ node)

Workflow Architecture:
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

▶ Usage Examples:
    # Run LLM-powered workflow for a ticker (simplest)
    python -m src.agents.supervisor.supervisor_agent AAPL
    
    # With custom company name and email
    python -m src.agents.supervisor.supervisor_agent NVDA --company "NVIDIA Corporation" --email user@example.com
    
    # Use Claude Sonnet for routing and analysis
    python -m src.agents.supervisor.supervisor_agent AAPL --llm claude-3.5-sonnet
    
    # Limit maximum iterations (default: 10)
    python -m src.agents.supervisor.supervisor_agent MSFT --max-iterations 6
    
    # Custom timestamp for analysis folder
    python -m src.agents.supervisor.supervisor_agent TSLA --timestamp 20250102_153000
    
    # List available LLM models
    python -m src.agents.supervisor.supervisor_agent --list-llms
"""

from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed. Environment variables from .env won't be loaded.")
    print("   Install with: pip install python-dotenv")

from src.logger import setup_logger, setup_agent_logger
from src.path_utils import get_analysis_path, ensure_analysis_paths
from src.llms.config import init_llm, list_models, list_available_models
from src.session_manager import SessionManager

# Import supervisor workflow components
from src.agents.supervisor.state import FinancialState, AgentNode, PipelineStage
from src.agents.supervisor.supervisor import route_workflow_with_llm, route_workflow
from src.agents.supervisor.task_agents.financial_data_agent import financial_data_agent
from src.agents.supervisor.task_agents.news_analysis_agent import news_analysis_agent
from src.agents.supervisor.task_agents.model_generation_agent import model_generation_agent
from src.agents.supervisor.task_agents.report_generator_agent import report_generator_agent


class SupervisorWorkflowRunner:
    """
    Orchestrates the LLM-powered agentic workflow with supervisor routing.
    """
    
    def __init__(self, 
                 ticker: str, 
                 company_name: str, 
                 email: str,
                 user_query: Optional[str] = None,
                 session_name: Optional[str] = None,
                 timestamp: Optional[str] = None,
                 max_iterations: int = 10):
        """
        Initialize the supervisor workflow runner.
        
        Args:
            ticker: Stock ticker symbol (e.g., 'NVDA')
            company_name: Full company name (e.g., 'NVIDIA')
            email: User's email for data organization
            user_query: Custom user query/instructions for the supervisor (optional)
            session_name: Session name for persistent conversation (optional)
            timestamp: Optional custom timestamp (YYYYMMDD_HHMMSS)
            max_iterations: Maximum workflow iterations to prevent infinite loops
        """
        self.ticker = ticker.upper()
        self.company_name = company_name
        self.email = email.lower()
        self.max_iterations = max_iterations
        self.user_query = user_query or f"Analyze {self.ticker} ({self.company_name})"
        self.session_name = session_name
        
        # Initialize session manager if session provided
        self.session_manager = None
        if session_name:
            self.session_manager = SessionManager(ticker=self.ticker, session_name=session_name)
        
        # Use provided timestamp or generate new one
        if timestamp:
            self.timestamp = timestamp
        else:
            self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Generate analysis path
        self.analysis_path = get_analysis_path(self.email, self.ticker, self.timestamp)
        ensure_analysis_paths(self.analysis_path)
        
        # Setup logging - single info.log with prefixes
        self.logger = setup_logger(self.ticker, base_path=self.analysis_path)
        
        # No separate agent loggers - everything goes to info.log with prefixes
        # self.supervisor_logger = setup_agent_logger("supervisor")
        # self.financial_data_logger = setup_agent_logger("financial_data_agent")
        # self.news_analysis_logger = setup_agent_logger("news_analysis_agent")
        # self.model_generation_logger = setup_agent_logger("model_generation_agent")
        # self.report_generator_logger = setup_agent_logger("report_generator_agent")
        
        self.logger.info(f"✅ Using unified logging to info.log with [supervisor] and [logs] prefixes")
        
        # Initialize state (FinancialState requires: user_query, ticker, company_name, email)
        self.state = FinancialState(
            user_query=self.user_query,
            ticker=self.ticker,
            company_name=self.company_name,
            email=self.email,
            analysis_path=str(self.analysis_path),
            timestamp=self.timestamp
        )
        
        # Workflow statistics
        self.stats = {
            "start_time": datetime.now(),
            "iterations": 0,
            "agents_executed": [],
            "routing_decisions": [],
            "completion_status": "not_started"
        }
        
        self.logger.info("=" * 80)
        self.logger.info(f"🎯 SUPERVISOR WORKFLOW INITIALIZED")
        self.logger.info("=" * 80)
        self.logger.info(f"   Ticker: {self.ticker}")
        self.logger.info(f"   Company: {self.company_name}")
        self.logger.info(f"   Analysis Path: {self.analysis_path}")
        self.logger.info(f"   Max Iterations: {self.max_iterations}")
        self.logger.info(f"   Timestamp: {self.timestamp}")
        if self.session_name:
            self.logger.info(f"   Session: {self.session_name}")
            conversation_count = len(self.session_manager.session_data.get("conversation_history", []))
            self.logger.info(f"   Previous Conversations: {conversation_count}")
        self.logger.info("=" * 80)
    
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
            Dictionary with workflow results and statistics
        """
        self.logger.info("▶ STARTING AGENTIC WORKFLOW")
        self.logger.info("")
        
        # Show conversation history if in a session
        if self.session_manager:
            history_summary = self.session_manager.get_conversation_summary(limit=3)
            if "No previous" not in history_summary:
                self.logger.info("📚 CONTINUING FROM PREVIOUS CONVERSATION:")
                for line in history_summary.split('\n'):
                    if line.strip():
                        self.logger.info(f"   {line}")
                self.logger.info("")
        
        # Log user query if custom
        if self.user_query != f"Analyze {self.ticker} ({self.company_name})":
            self.logger.info("💬 USER QUERY:")
            self.logger.info(f"   \"{self.user_query}\"")
            self.logger.info("")
        
        iteration = 0
        
        while iteration < self.max_iterations:
            iteration += 1
            self.stats["iterations"] = iteration
            
            self.logger.info("─" * 80)
            self.logger.info(f"📍 ITERATION {iteration}/{self.max_iterations}")
            self.logger.info("─" * 80)
            
            # Step 1: Supervisor routing decision
            self.logger.info("[logs] 🧠 Supervisor evaluating current state...")
            self.logger.info(f"[logs] 📍 ITERATION {iteration}/{self.max_iterations}")
            self.logger.info(f"[logs] Current state: financial_data={self.state.is_financial_data_collected()}, model={self.state.is_model_generated()}, news={self.state.is_news_analyzed()}, report={self.state.is_report_generated()}")
            
            try:
                # Use LLM-powered routing
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
                
                self.logger.info(f"[logs] 📌 Routing to: {next_agent}")
                
            except Exception as e:
                self.logger.warning(f"[logs] ⚠️  LLM routing failed: {e}")
                self.logger.info("[logs] 🔄 Falling back to deterministic routing...")
                
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
                
                self.logger.info(f"[logs] 📌 Fallback routing to: {next_agent}")
            
            # Step 2: Check for workflow completion
            if next_agent == "__end__":
                self.logger.info("")
                self.logger.info("[logs] " + "=" * 80)
                self.logger.info("[logs] 🎉 WORKFLOW COMPLETED SUCCESSFULLY")
                self.logger.info("[logs] " + "=" * 80)
                self.stats["completion_status"] = "completed"
                break
            
            # Step 3: Execute chosen agent
            self.logger.info("")
            self.logger.info(f"[logs] ▶ EXECUTING AGENT: {next_agent}")
            self.logger.info("")
            
            try:
                # Map agent names to agent functions (no separate loggers - all use main logger)
                agent_map = {
                    "financial_data_agent": financial_data_agent,
                    "news_analysis_agent": news_analysis_agent,
                    "model_generation_agent": model_generation_agent,
                    "report_generator_agent": report_generator_agent
                }
                
                agent_func = agent_map.get(next_agent)
                
                if agent_func is None:
                    self.logger.error(f"[logs] ❌ Unknown agent: {next_agent}")
                    self.stats["completion_status"] = "failed"
                    break
                
                # Log agent start
                self.logger.info(f"[logs] 🚀 Starting {next_agent} (iteration {iteration})")
                
                # Execute agent (async)
                agent_start = datetime.now()
                self.state = await agent_func(self.state)
                agent_duration = (datetime.now() - agent_start).total_seconds()
                
                self.stats["agents_executed"].append({
                    "agent": next_agent,
                    "iteration": iteration,
                    "duration": agent_duration,
                    "timestamp": datetime.now().isoformat()
                })
                
                self.logger.info("")
                self.logger.info(f"[logs] ✅ Agent {next_agent} completed in {agent_duration:.2f}s")
                
                # Log state after agent execution
                self.logger.info(f"[logs] 📊 State after {next_agent}:")
                self.logger.info(f"[logs]    - Financial data collected: {self.state.is_financial_data_collected()}")
                self.logger.info(f"[logs]    - Model generated: {self.state.is_model_generated()}")
                self.logger.info(f"[logs]    - News analyzed: {self.state.is_news_analyzed()}")
                self.logger.info(f"[logs]    - Report generated: {self.state.is_report_generated()}")
                self.logger.info(f"[logs]    - Current stage: {self.state.current_stage.value}")
                
                # Check for errors in state
                if self.state.last_error:
                    self.logger.error(f"[logs] ⚠️  Agent reported error: {self.state.last_error}")
                
                if self.state.current_stage == PipelineStage.FAILED:
                    self.logger.error(f"[logs] ❌ Workflow failed during {next_agent}")
                    self.stats["completion_status"] = "failed"
                    break
                
                self.logger.info("")
                
            except Exception as e:
                self.logger.error(f"❌ Agent execution failed: {e}")
                self.logger.error(f"   Agent: {next_agent}")
                import traceback
                self.logger.error(traceback.format_exc())
                self.stats["completion_status"] = "failed"
                break
        
        # Check if we hit max iterations
        if iteration >= self.max_iterations and next_agent != "__end__":
            self.logger.warning("")
            self.logger.warning("=" * 80)
            self.logger.warning(f"⚠️  WORKFLOW STOPPED: Reached max iterations ({self.max_iterations})")
            self.logger.warning("=" * 80)
            self.stats["completion_status"] = "max_iterations_reached"
        
        # Calculate final statistics
        self.stats["end_time"] = datetime.now()
        self.stats["total_duration"] = (self.stats["end_time"] - self.stats["start_time"]).total_seconds()
        
        # Save session data if using sessions
        if self.session_manager:
            # Extract routing decisions from stats
            routing_decisions = [agent["agent"] for agent in self.stats["agents_executed"]]
            
            # Generate key findings summary (brief)
            key_findings = None
            if self.stats["completion_status"] == "completed":
                key_findings = f"Completed analysis in {len(routing_decisions)} steps. "
                if self.state.is_report_generated():
                    key_findings += "Generated comprehensive report. "
                if self.state.is_news_analyzed():
                    key_findings += f"Analyzed {self.state.news_analysis.articles_count if self.state.news_analysis else 0} articles."
            
            # Add to session history
            self.session_manager.add_conversation(
                user_query=self.user_query,
                company_name=self.company_name,
                routing_decisions=routing_decisions,
                completion_status=self.stats["completion_status"],
                key_findings=key_findings,
                statistics={
                    "iterations": self.stats["iterations"],
                    "duration": self.stats["total_duration"],
                    "agents_count": len(self.stats["agents_executed"])
                }
            )
            
            self.logger.info(f"💾 Session '{self.session_name}' saved with conversation history")
        
        # Generate LLM-powered performance summary if workflow completed successfully
        if self.stats["completion_status"] == "completed":
            self._generate_performance_summary()
        
        # Log final summary
        self._log_workflow_summary()
        
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "statistics": self.stats,
            "final_state": {
                "financial_data_collected": self.state.is_financial_data_collected(),
                "model_generated": self.state.is_model_generated(),
                "news_analyzed": self.state.is_news_analyzed(),
                "report_generated": self.state.is_report_generated()
            }
        }
    
    def _generate_performance_summary(self):
        """Generate LLM-powered stock performance summary."""
        try:
            from src.llms.config import get_llm
            
            # Build summary prompt with state information
            summary_prompt = f"""You are a senior financial analyst who just completed a comprehensive analysis of {self.ticker} ({self.company_name}).

Based on the analysis results:

**Financial Model:**
{f"Generated {self.state.financial_model.model_type} valuation model" if self.state.is_model_generated() else "Not available"}

**News Analysis:**
{f"Analyzed {self.state.news_analysis.articles_count} articles - Overall sentiment: {self.state.news_analysis.overall_sentiment}. Found {len(self.state.news_analysis.catalysts)} catalysts and {len(self.state.news_analysis.risks)} risks." if self.state.is_news_analyzed() else "Not available"}

**Report:**
{f"Generated comprehensive analyst report with investment recommendation" if self.state.is_report_generated() else "Not available"}

Write a 5-6 sentence summary about how {self.ticker} is performing based on this analysis. Focus on:
1. The investment outlook (positive/negative/mixed)
2. Key drivers or concerns from the news
3. Valuation insights
4. Risk factors
5. Overall investment recommendation

Be direct and professional. Respond with ONLY the performance summary, no JSON or formatting."""

            # Call LLM to generate summary
            summary_response, summary_cost = get_llm()([
                {"role": "system", "content": "You are a senior financial analyst providing a professional summary."},
                {"role": "user", "content": summary_prompt}
            ], temperature=0.7)
            self.state.total_llm_cost += summary_cost
            
            # Log the performance summary with [supervisor] prefix
            self.logger.info("")
            self.logger.info("[supervisor] " + "="*60)
            self.logger.info("[supervisor] 🎉 ANALYSIS COMPLETE")
            self.logger.info("[supervisor] " + "="*60)
            self.logger.info("")
            self.logger.info(f"[supervisor] 📊 {self.ticker} Performance Summary:")
            self.logger.info(f"[supervisor] {summary_response.strip()}")
            self.logger.info("")
            self.logger.info(f"[supervisor] 📁 Full analysis saved to: {self.state.analysis_path}")
            self.logger.info(f"[supervisor] 💰 Total LLM cost: ${self.state.total_llm_cost:.4f}")
            self.logger.info("")
            
        except Exception as e:
            # If LLM summary fails, log error but don't crash
            self.logger.error(f"Failed to generate LLM performance summary: {str(e)}")
    
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


def main():
    """Main entry point for supervisor workflow."""
    parser = argparse.ArgumentParser(
        description="Supervisor Agent - LLM-Powered Agentic Workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run LLM-powered workflow for Apple
  python supervisor_main.py AAPL
  
  # With custom user query/instructions
  python supervisor_main.py AAPL --query "Focus on AI capabilities and competitive analysis"
  
  # Start or continue a conversation session
  python supervisor_main.py AAPL --session deep-dive
  python supervisor_main.py AAPL -s quarterly-review --query "How did Q4 earnings impact valuation?"
  
  # List all sessions for a ticker
  python supervisor_main.py --list-sessions AAPL
  
  # View session information
  python supervisor_main.py --session-info AAPL:deep-dive
  
  # Clear session history (keep session but remove conversations)
  python supervisor_main.py --clear-session AAPL:deep-dive
  
  # Delete a session permanently
  python supervisor_main.py --delete-session AAPL:old-session
  
  # With custom company name and email
  python supervisor_main.py NVDA --company "NVIDIA Corporation" --email user@example.com
  
  # Use Claude Sonnet for routing and analysis
  python supervisor_main.py AAPL --llm claude-3.5-sonnet
  
  # Complex query example
  python supervisor_main.py TSLA --query "I want to understand Tesla's valuation and whether it's overpriced. Focus on comparing to traditional automakers."
  
  # Limit workflow iterations
  python supervisor_main.py MSFT --max-iterations 6
  
  # List available LLM models
  python supervisor_main.py --list-llms
        """
    )
    
    # Positional argument for ticker (optional for --list-llms)
    parser.add_argument("ticker", nargs="?", help="Stock ticker symbol (e.g., AAPL, NVDA, TSLA)")
    
    # Optional arguments with defaults
    parser.add_argument("--company", help="Company name (defaults to ticker if not provided)")
    parser.add_argument("--email", default="default@analyst.com", 
                       help="User email for data organization (default: default@analyst.com)")
    parser.add_argument("--query", "-q", 
                       help="Custom query or instructions for the supervisor (e.g., 'Focus on AI capabilities and valuation')")
    
    # Session management
    parser.add_argument("--session", "-s",
                       help="Session name for persistent conversation (e.g., 'deep-dive', 'quarterly-review')")
    parser.add_argument("--list-sessions", 
                       help="List all sessions for a ticker (provide ticker)")
    parser.add_argument("--session-info",
                       help="Show information about a specific session (format: TICKER:SESSION_NAME)")
    parser.add_argument("--clear-session",
                       help="Clear conversation history in a session (format: TICKER:SESSION_NAME)")
    parser.add_argument("--delete-session",
                       help="Delete a session permanently (format: TICKER:SESSION_NAME)")
    
    # Optional arguments
    parser.add_argument("--timestamp", help="Custom timestamp for analysis folder (YYYYMMDD_HHMMSS)")
    parser.add_argument("--max-iterations", type=int, default=10, 
                       help="Maximum workflow iterations (default: 10)")
    
    # LLM selection
    parser.add_argument("--llm", 
                       choices=["gpt-4o-mini", "claude-3.5-sonnet", "claude-3.5-haiku", "claude-3-opus"], 
                       default="gpt-4o-mini", 
                       help="LLM model to use for routing and analysis (default: gpt-4o-mini)")
    parser.add_argument("--list-llms", action="store_true", 
                       help="List available LLM models and exit")
    
    args = parser.parse_args()
    
    # Handle session management commands
    if args.list_sessions:
        from session_manager import SessionManager
        sessions = SessionManager.list_sessions(args.list_sessions)
        
        if not sessions:
            print(f"No sessions found for {args.list_sessions}")
        else:
            print(f"\n📚 Sessions for {args.list_sessions}:")
            for session_name in sessions:
                info = SessionManager.get_session_info(args.list_sessions, session_name)
                if info:
                    conv_count = info.get("conversation_count", 0)
                    last_updated = info.get("last_updated", "Unknown")
                    print(f"  • {session_name} ({conv_count} conversations, last: {last_updated})")
                else:
                    print(f"  • {session_name}")
        print()
        return 0
    
    if args.session_info:
        from session_manager import SessionManager
        try:
            ticker, session_name = args.session_info.split(":")
            info = SessionManager.get_session_info(ticker, session_name)
            
            if not info:
                print(f"❌ Session not found: {args.session_info}")
                return 1
            
            print(f"\n📊 Session Information:")
            print(f"  Ticker: {info.get('ticker')}")
            print(f"  Company: {info.get('company_name')}")
            print(f"  Session Name: {info.get('session_name')}")
            print(f"  Created: {info.get('created_at')}")
            print(f"  Last Updated: {info.get('last_updated')}")
            print(f"  Conversations: {info.get('conversation_count')}")
            print()
            return 0
        except ValueError:
            print("❌ Invalid format. Use TICKER:SESSION_NAME (e.g., AAPL:deep-dive)")
            return 1
    
    if args.clear_session:
        from session_manager import SessionManager
        try:
            ticker, session_name = args.clear_session.split(":")
            session_mgr = SessionManager(ticker, session_name)
            session_mgr.clear_history()
            print(f"✅ Cleared conversation history for session '{session_name}' ({ticker})")
            return 0
        except ValueError:
            print("❌ Invalid format. Use TICKER:SESSION_NAME (e.g., AAPL:deep-dive)")
            return 1
        except Exception as e:
            print(f"❌ Failed to clear session: {e}")
            return 1
    
    if args.delete_session:
        from session_manager import SessionManager
        try:
            ticker, session_name = args.delete_session.split(":")
            session_mgr = SessionManager(ticker, session_name)
            if session_mgr.delete_session():
                print(f"✅ Deleted session '{session_name}' ({ticker})")
                return 0
            else:
                print(f"❌ Session not found: {args.delete_session}")
                return 1
        except ValueError:
            print("❌ Invalid format. Use TICKER:SESSION_NAME (e.g., AAPL:deep-dive)")
            return 1
        except Exception as e:
            print(f"❌ Failed to delete session: {e}")
            return 1
    
    # Handle --list-llms flag
    if args.list_llms:
        all_models = list_models()
        available_models = list_available_models()
        
        print("Available LLM models:")
        for model in all_models:
            if model in available_models:
                print(f"  ✅ {model}")
            else:
                print(f"  ❌ {model} (API key missing)")
        
        if not available_models:
            print("\nNo models available. Set OPENAI_API_KEY or ANTHROPIC_API_KEY environment variables.")
        
        return 0
    
    # Validate required ticker argument
    if not args.ticker:
        parser.error("ticker is required (e.g., python supervisor_main.py AAPL)")
    
    # Use ticker as company name if not provided
    company_name = args.company if args.company else args.ticker
    
    try:
        # Initialize LLM
        init_llm(args.llm)
        
        # Initialize workflow runner
        runner = SupervisorWorkflowRunner(
            ticker=args.ticker,
            company_name=company_name,
            email=args.email,
            user_query=args.query,
            session_name=args.session,
            timestamp=args.timestamp,
            max_iterations=args.max_iterations
        )
        
        # Run workflow (async)
        results = asyncio.run(runner.run_workflow())
        
        # Exit with appropriate status
        if results["statistics"]["completion_status"] == "completed":
            print("\n✅ Workflow completed successfully")
            return 0
        elif results["statistics"]["completion_status"] == "max_iterations_reached":
            print("\n⚠️  Workflow stopped: Max iterations reached")
            return 1
        else:
            print("\n❌ Workflow failed")
            return 1
            
    except KeyboardInterrupt:
        print("\n⏹️  Workflow interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Workflow failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
