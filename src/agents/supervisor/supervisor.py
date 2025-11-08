"""
supervisor.py - Supervisor Agent for Workflow Routing

The Supervisor Agent reads the current FinancialState and uses LLM-powered
flexible routing to determine the next node in the workflow.

The LLM can choose ANY agent based on what makes sense for the analysis,
not just sequential execution. This enables dynamic, intelligent routing.
"""

from typing import Literal
import json
from datetime import datetime
from pathlib import Path

from src.agents.supervisor.state import (
    FinancialState, 
    AgentNode, 
    PipelineStage,
    AnalysisObjective
)
from src.llms.config import get_llm
from src.logger import get_logger


# Load routing prompt from prompts folder
def _load_routing_prompt():
    """Load the workflow routing prompt from prompts folder."""
    prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / "workflow_routing.md"
    with open(prompt_path, 'r') as f:
        content = f.read()
    # Replace format string markers to avoid conflicts with markdown
    content = content.replace("```markdown\n", "").replace("```", "")
    return content


def _load_completion_summary_prompt():
    """Load the workflow completion summary prompt from prompts folder."""
    prompt_path = Path(__file__).parent.parent.parent.parent / "prompts" / "workflow_completion_summary.md"
    with open(prompt_path, 'r') as f:
        return f.read()


ROUTING_PROMPT_TEMPLATE = _load_routing_prompt()
COMPLETION_SUMMARY_TEMPLATE = _load_completion_summary_prompt()


def load_routing_prompt():
    """Public function to load and display the routing prompt."""
    return ROUTING_PROMPT_TEMPLATE


def _detect_user_intent(user_query: str) -> AnalysisObjective:
    """
    Detect what the user actually wants from their natural language query.
    
    This prevents the system from doing more work than requested.
    For example, if user says "generate a financial model", we should stop
    after model_generation_agent, not continue to news_analysis and report.
    
    Args:
        user_query: User's natural language request
        
    Returns:
        AnalysisObjective enum indicating what the user wants
    """
    if not user_query:
        return AnalysisObjective.COMPREHENSIVE
    
    query_lower = user_query.lower()
    
    # Check for model-only requests
    model_keywords = [
        "financial model", "build a model", "generate a model", "create a model",
        "dcf model", "valuation model", "build model", "create model"
    ]
    if any(keyword in query_lower for keyword in model_keywords):
        # Check if they ALSO want news/report
        if "news" in query_lower or "report" in query_lower or "analysis" in query_lower:
            return AnalysisObjective.COMPREHENSIVE
        return AnalysisObjective.MODEL_ONLY
    
    # Check for news-only requests
    news_keywords = [
        "news", "latest news", "recent news", "articles", "headlines",
        "sentiment", "catalysts", "risks"
    ]
    if any(keyword in query_lower for keyword in news_keywords):
        # Check if they ALSO want model/report
        if "model" in query_lower or "report" in query_lower:
            return AnalysisObjective.COMPREHENSIVE
        return AnalysisObjective.QUICK_NEWS
    
    # Check for data-only requests
    data_keywords = [
        "financial data", "get data", "fetch data", "collect data",
        "financial statements", "financials"
    ]
    if any(keyword in query_lower for keyword in data_keywords):
        if "model" not in query_lower and "news" not in query_lower and "report" not in query_lower:
            # They just want data - set to MODEL_ONLY but we'll stop after data collection
            return AnalysisObjective.CUSTOM
    
    # Default to comprehensive if unclear
    return AnalysisObjective.COMPREHENSIVE


def _is_objective_achieved(state: FinancialState) -> bool:
    """
    Check if the user's objective has been achieved.
    
    This is critical for stopping the workflow at the right point.
    For example, if objective is MODEL_ONLY, stop after model_generation_agent.
    
    Args:
        state: Current FinancialState with objective
        
    Returns:
        True if objective achieved and workflow should end
    """
    objective = state.objective
    
    if objective == AnalysisObjective.COMPREHENSIVE:
        # Need everything: data, model, news, report
        return (
            state.is_financial_data_collected() and
            state.is_model_generated() and
            state.is_news_analyzed() and
            state.is_report_generated()
        )
    
    elif objective == AnalysisObjective.MODEL_ONLY:
        # Only need financial data + model
        return state.is_financial_data_collected() and state.is_model_generated()
    
    elif objective == AnalysisObjective.QUICK_NEWS:
        # Only need news analysis (financial data is optional - ArticleScraper can work without it)
        return state.is_news_analyzed()
    
    elif objective == AnalysisObjective.CUSTOM:
        # Just financial data
        return state.is_financial_data_collected()
    
    # Default: not achieved
    return False


def _resolve_dependencies(state: FinancialState, target_node: str, logger=None) -> tuple[str, bool, str]:
    """
    Intelligent dependency resolution - determines the optimal path to reach target node.
    
    This function implements "path planning" - given a desired destination (target_node),
    it checks if all prerequisites are met. If not, it returns the next required step
    in the dependency chain to eventually reach the target.
    
    🔥 KEY FEATURE: Respects user's objective!
    - If objective is MODEL_ONLY, stops after model generation (no news/report)
    - If objective is QUICK_NEWS, stops after news analysis (no report)
    - If objective is COMPREHENSIVE, completes full workflow
    
    Dependency Chain:
    1. financial_data_agent (must run first - nothing else works without data)
    2. model_generation_agent (requires financial_data)
    3. news_analysis_agent (can run after financial_data)
    4. report_generator_agent (requires all three above)
    
    Args:
        state: Current FinancialState
        target_node: The node that LLM wants to route to
        logger: Optional logger for messages
        
    Returns:
        tuple of (actual_next_node, was_redirected, explanation)
        - actual_next_node: The node to actually route to (may differ from target)
        - was_redirected: True if we had to redirect due to missing prerequisites
        - explanation: Human-readable explanation of the routing decision
    """
    main_logger = logger or get_logger()
    
    # 🔥 CHECK IF OBJECTIVE ALREADY ACHIEVED
    if _is_objective_achieved(state):
        explanation = f"✅ User's objective ({state.objective.value}) has been achieved. Ending workflow."
        if main_logger:
            main_logger.info(f"[DEPENDENCY RESOLVER] {explanation}")
        return "__end__", True if target_node != "__end__" else False, explanation
    
    # If target is __end__, check if objective is achieved
    if target_node == "__end__":
        if not _is_objective_achieved(state):
            # Objective not achieved - determine what's still needed
            if state.objective == AnalysisObjective.MODEL_ONLY:
                if not state.is_financial_data_collected():
                    explanation = f"Cannot end - MODEL_ONLY objective requires financial data + model. Routing to financial_data_agent."
                    return "financial_data_agent", True, explanation
                elif not state.is_model_generated():
                    explanation = f"Cannot end - MODEL_ONLY objective requires model generation. Routing to model_generation_agent."
                    return "model_generation_agent", True, explanation
            
            elif state.objective == AnalysisObjective.QUICK_NEWS:
                if not state.is_news_analyzed():
                    explanation = f"Cannot end - QUICK_NEWS objective requires news analysis. Routing to news_analysis_agent."
                    return "news_analysis_agent", True, explanation
            
            elif state.objective == AnalysisObjective.COMPREHENSIVE:
                # Use existing logic for comprehensive
                missing = []
                if not state.is_financial_data_collected():
                    missing.append("financial data")
                if not state.is_model_generated():
                    missing.append("financial model")
                if not state.is_news_analyzed():
                    missing.append("news analysis")
                if not state.is_report_generated():
                    missing.append("final report")
                
                if missing:
                    if not state.is_financial_data_collected():
                        explanation = f"Cannot end workflow yet - missing {', '.join(missing)}. Routing to financial_data_agent first."
                        return "financial_data_agent", True, explanation
                    elif not state.is_model_generated():
                        explanation = f"Cannot end workflow yet - missing {', '.join(missing)}. Routing to model_generation_agent next."
                        return "model_generation_agent", True, explanation
                    elif not state.is_news_analyzed():
                        explanation = f"Cannot end workflow yet - missing {', '.join(missing)}. Routing to news_analysis_agent next."
                        return "news_analysis_agent", True, explanation
                    else:
                        explanation = f"Cannot end workflow yet - missing {', '.join(missing)}. Routing to report_generator_agent to finish."
                        return "report_generator_agent", True, explanation
        
        return "__end__", False, "Objective achieved - workflow can end."
    
    # 🔥 RESPECT OBJECTIVE: Don't route to agents not needed for objective
    if state.objective == AnalysisObjective.MODEL_ONLY:
        # For MODEL_ONLY, reject news_analysis and report_generator
        if target_node == "news_analysis_agent":
            explanation = f"MODEL_ONLY objective: User asked only for financial model, not news analysis. Ending workflow."
            if main_logger:
                main_logger.info(f"[DEPENDENCY RESOLVER] 🎯 {explanation}")
            return "__end__", True, explanation
        
        if target_node == "report_generator_agent":
            explanation = f"MODEL_ONLY objective: User asked only for financial model, not a report. Ending workflow."
            if main_logger:
                main_logger.info(f"[DEPENDENCY RESOLVER] 🎯 {explanation}")
            return "__end__", True, explanation
    
    elif state.objective == AnalysisObjective.QUICK_NEWS:
        # For QUICK_NEWS, reject model and report
        if target_node == "model_generation_agent":
            if state.is_financial_data_collected() and not state.is_news_analyzed():
                explanation = f"QUICK_NEWS objective: User asked for news analysis, not model. Routing to news_analysis_agent."
                if main_logger:
                    main_logger.info(f"[DEPENDENCY RESOLVER] 🎯 {explanation}")
                return "news_analysis_agent", True, explanation
        
        if target_node == "report_generator_agent":
            explanation = f"QUICK_NEWS objective: User asked for news analysis, not a report. Ending workflow."
            if main_logger:
                main_logger.info(f"[DEPENDENCY RESOLVER] 🎯 {explanation}")
            return "__end__", True, explanation
    
    elif state.objective == AnalysisObjective.CUSTOM:
        # For CUSTOM, reject everything except financial_data
        if target_node in ["model_generation_agent", "news_analysis_agent", "report_generator_agent"]:
            explanation = f"CUSTOM objective: User only requested financial data. Ending workflow."
            if main_logger:
                main_logger.info(f"[DEPENDENCY RESOLVER] 🎯 {explanation}")
            return "__end__", True, explanation
    
    # Check if target work is already done
    if target_node == "financial_data_agent" and state.is_financial_data_collected():
        explanation = "Financial data already collected - no need to run again."
        # Route to next logical step
        if not state.is_model_generated():
            return "model_generation_agent", True, explanation + " Routing to model_generation_agent instead."
        elif not state.is_news_analyzed():
            return "news_analysis_agent", True, explanation + " Routing to news_analysis_agent instead."
        elif not state.is_report_generated():
            return "report_generator_agent", True, explanation + " Routing to report_generator_agent instead."
        else:
            return "__end__", True, explanation + " All work complete."
    
    if target_node == "model_generation_agent" and state.is_model_generated():
        explanation = "Financial model already generated - no need to run again."
        if not state.is_news_analyzed():
            return "news_analysis_agent", True, explanation + " Routing to news_analysis_agent instead."
        elif not state.is_report_generated():
            return "report_generator_agent", True, explanation + " Routing to report_generator_agent instead."
        else:
            return "__end__", True, explanation + " All work complete."
    
    if target_node == "news_analysis_agent" and state.is_news_analyzed():
        explanation = "News analysis already complete - no need to run again."
        if not state.is_model_generated():
            return "model_generation_agent", True, explanation + " Routing to model_generation_agent instead."
        elif not state.is_report_generated():
            return "report_generator_agent", True, explanation + " Routing to report_generator_agent instead."
        else:
            return "__end__", True, explanation + " All work complete."
    
    if target_node == "report_generator_agent" and state.is_report_generated():
        explanation = "Report already generated - workflow complete."
        return "__end__", True, explanation
    
    # Check prerequisites for target node
    if target_node == "model_generation_agent":
        if not state.is_financial_data_collected():
            explanation = "Cannot generate financial model without data. Routing to financial_data_agent first (mandatory prerequisite)."
            if main_logger:
                main_logger.warning(f"[DEPENDENCY RESOLVER] 🔀 LLM wanted to route to model_generation_agent, but financial data not collected yet.")
                main_logger.info(f"[DEPENDENCY RESOLVER] ✅ Auto-correcting: financial_data_agent → model_generation_agent")
            return "financial_data_agent", True, explanation
    
    if target_node == "report_generator_agent":
        # Report requires ALL three: financial data, model, news
        missing = []
        if not state.is_financial_data_collected():
            missing.append("financial data")
        if not state.is_model_generated():
            missing.append("financial model")
        if not state.is_news_analyzed():
            missing.append("news analysis")
        
        if missing:
            # Route to first missing prerequisite
            if not state.is_financial_data_collected():
                explanation = f"Cannot generate report - missing {', '.join(missing)}. Routing to financial_data_agent first."
                if main_logger:
                    main_logger.warning(f"[DEPENDENCY RESOLVER] 🔀 LLM wanted to route to report_generator_agent, but missing: {', '.join(missing)}")
                    main_logger.info(f"[DEPENDENCY RESOLVER] ✅ Auto-correcting path: financial_data_agent → model_generation_agent → news_analysis_agent → report_generator_agent")
                return "financial_data_agent", True, explanation
            elif not state.is_model_generated():
                explanation = f"Cannot generate report - missing {', '.join(missing)}. Routing to model_generation_agent next."
                if main_logger:
                    main_logger.warning(f"[DEPENDENCY RESOLVER] 🔀 LLM wanted to route to report_generator_agent, but missing: {', '.join(missing)}")
                    main_logger.info(f"[DEPENDENCY RESOLVER] ✅ Auto-correcting path: model_generation_agent → news_analysis_agent → report_generator_agent")
                return "model_generation_agent", True, explanation
            else:  # News analysis missing
                explanation = f"Cannot generate report - missing {', '.join(missing)}. Routing to news_analysis_agent next."
                if main_logger:
                    main_logger.warning(f"[DEPENDENCY RESOLVER] 🔀 LLM wanted to route to report_generator_agent, but missing: {', '.join(missing)}")
                    main_logger.info(f"[DEPENDENCY RESOLVER] ✅ Auto-correcting path: news_analysis_agent → report_generator_agent")
                return "news_analysis_agent", True, explanation
    
    # Target node prerequisites are satisfied - can proceed
    return target_node, False, f"All prerequisites satisfied for {target_node}."


def _log_workflow_completion(state: FinancialState, logger=None):
    """
    Log workflow completion with LLM-generated summary.
    
    Args:
        state: Current FinancialState (all work complete)
        logger: Optional logger to use (falls back to get_logger())
    """
    try:
        main_logger = logger or get_logger()
        if not main_logger:
            return
            
        # Build status messages
        financial_data_status = (
            f"✅ Collected comprehensive financial data including {len(state.financial_data.raw_data) if state.financial_data and state.financial_data.raw_data else 0} data points"
            if state.is_financial_data_collected() else "⏭️ Skipped"
        )
        
        model_status = (
            f"✅ Generated {state.financial_model.model_type} model saved to {state.financial_model.excel_path}"
            if state.is_model_generated() else "⏭️ Skipped"
        )
        
        news_status = (
            f"✅ Analyzed {state.news_analysis.articles_count} articles, found {len(state.news_analysis.catalysts)} catalysts, {len(state.news_analysis.risks)} risks. Overall sentiment: {state.news_analysis.overall_sentiment}"
            if state.is_news_analyzed() else "⏭️ Skipped"
        )
        
        report_status = (
            f"✅ Generated comprehensive analyst report ({len(state.report.content):,} characters) saved to {state.report.report_path}"
            if state.is_report_generated() and state.report.content else "⏭️ Skipped"
        )
        
        # Format the completion summary prompt
        summary_prompt = COMPLETION_SUMMARY_TEMPLATE.format(
            ticker=state.ticker,
            company_name=state.company_name,
            financial_data_status=financial_data_status,
            model_status=model_status,
            news_status=news_status,
            report_status=report_status,
            analysis_path=state.analysis_path,
            total_llm_cost=f"{state.total_llm_cost:.4f}"
        )
        
        try:
            # Generate LLM-powered summary
            summary_response, summary_cost = get_llm()([
                {"role": "system", "content": "You are a senior financial analyst providing a professional summary."},
                {"role": "user", "content": summary_prompt}
            ], temperature=0.7)
            state.total_llm_cost += summary_cost
            
            # Log the completion message
            main_logger.info("")
            main_logger.info(f"[LLM] {summary_response.strip()}")
            main_logger.info("")
            main_logger.info(f"[SUPERVISOR] 📁 Analysis saved to: {state.analysis_path}")
            main_logger.info(f"[SUPERVISOR] 💰 Total LLM cost: ${state.total_llm_cost:.4f}")
            main_logger.info("")
            
        except Exception:
            # Fallback to simple summary if LLM fails
            main_logger.info("")
            main_logger.info(f"[SUPERVISOR] 🎉 Perfect! I've finished the analysis for {state.ticker}!")
            main_logger.info(f"[SUPERVISOR] 📊 Summary of what we completed:")
            main_logger.info(f"[SUPERVISOR]    {'✅' if state.is_financial_data_collected() else '⏭️'} Financial data collection")
            main_logger.info(f"[SUPERVISOR]    {'✅' if state.is_news_analyzed() else '⏭️'} News analysis")
            main_logger.info(f"[SUPERVISOR]    {'✅' if state.is_model_generated() else '⏭️'} Financial model generation")
            main_logger.info(f"[SUPERVISOR]    {'✅' if state.is_report_generated() else '⏭️'} Professional analyst report")
            main_logger.info(f"[SUPERVISOR] 💼 Your comprehensive stock analysis is ready!")
            main_logger.info("")
        
        # Force flush
        for handler in main_logger.logger.handlers:
            handler.flush()
            
    except Exception:
        pass


def route_workflow(state: FinancialState, config: dict = None, logger=None) -> Literal[
    "financial_data_agent",
    "news_analysis_agent", 
    "model_generation_agent",
    "report_generator_agent",
    "__end__"
]:
    """
    Deterministic fallback routing function (not used by default).
    
    Kept for backward compatibility and fallback scenarios.
    
    Args:
        state: Current FinancialState
        config: Optional configuration dict (unused, for LangGraph compatibility)
        
    Returns:
        String name of the next agent node or "__end__"
    """
    
    # Fallback to simple sequential logic if no analysis has been done
    main_logger = logger or get_logger()
    
    # Add state summary for deterministic routing
    if main_logger:
        main_logger.info("")
        main_logger.info("[SUPERVISOR] 📊 Current State Summary (Deterministic Mode):")
        main_logger.info(f"[SUPERVISOR]    • Financial Data: {'✅ Collected' if state.is_financial_data_collected() else '⏳ Pending'}")
        main_logger.info(f"[SUPERVISOR]    • Financial Model: {'✅ Generated' if state.is_model_generated() else '⏳ Pending'}")
        main_logger.info(f"[SUPERVISOR]    • News Analysis: {'✅ Completed' if state.is_news_analyzed() else '⏳ Pending'}")
        main_logger.info(f"[SUPERVISOR]    • Analyst Report: {'✅ Generated' if state.is_report_generated() else '⏳ Pending'}")
        main_logger.info("")
    
    if not state.is_financial_data_collected():
        state.log_action(
            agent="supervisor_fallback",
            action="route_decision",
            details={"reason": "financial_data not collected", "next": "financial_data_agent"}
        )
        state.next_agent = AgentNode.FINANCIAL_DATA_AGENT
        if main_logger:
            main_logger.info(f"[SUPERVISOR] Alright, let's get started! First things first - I need to gather the fundamental financial data for {state.ticker}. This will give us the foundation for everything else.")
            main_logger.info(f"[SUPERVISOR] → Next action: financial_data_agent")
        return "financial_data_agent"
    
    if not state.is_model_generated():
        state.log_action(
            agent="supervisor_fallback",
            action="route_decision",
            details={"reason": "model not generated", "next": "model_generation_agent"}
        )
        state.next_agent = AgentNode.MODEL_GENERATION_AGENT
        if main_logger:
            main_logger.info(f"[SUPERVISOR] Great! Now that we have the financial data, let me build a comprehensive DCF model. This will help us understand the intrinsic value and future projections.")
            main_logger.info(f"[SUPERVISOR] → Next action: model_generation_agent")
        return "model_generation_agent"
    
    # CRITICAL: Force news_analysis to run before report generation
    if not state.is_news_analyzed():
        state.log_action(
            agent="supervisor_fallback",
            action="route_decision",
            details={"reason": "news analysis not completed", "next": "news_analysis_agent"}
        )
        state.next_agent = AgentNode.NEWS_ANALYSIS_AGENT
        if main_logger:
            main_logger.info(f"[SUPERVISOR] Perfect timing! With the financials and model ready, I should analyze recent news and market sentiment. This will give us crucial context for the final report.")
            main_logger.info(f"[SUPERVISOR] → Next action: news_analysis_agent")
        return "news_analysis_agent"
    
    if not state.is_report_generated():
        state.log_action(
            agent="supervisor_fallback",
            action="route_decision",
            details={"reason": "report not generated", "next": "report_generator_agent"}
        )
        state.next_agent = AgentNode.REPORT_GENERATOR_AGENT
        if main_logger:
            main_logger.info(f"[SUPERVISOR] Excellent! I've gathered all the pieces - financial data, valuation model, and news insights. Time to synthesize everything into a comprehensive analyst report!")
            main_logger.info(f"[SUPERVISOR] → Next action: report_generator_agent")
        return "report_generator_agent"
    
    state.log_action(
        agent="supervisor_fallback",
        action="route_decision",
        details={"reason": "all stages complete", "next": "__end__"}
    )
    state.current_stage = PipelineStage.COMPLETED
    state.next_agent = AgentNode.END
    
    # Log workflow completion
    _log_workflow_completion(state, logger)
    
    return "__end__"


def route_workflow_with_llm(state: FinancialState, config: dict = None, logger=None, conversation_history: str = None) -> Literal[
    "financial_data_agent",
    "news_analysis_agent",
    "model_generation_agent",
    "report_generator_agent",
    "__end__"
]:
    """
    LLM-powered flexible routing that allows intelligent decision-making.
    
    The LLM can choose ANY agent based on what makes sense for the analysis,
    not just sequential execution. This enables dynamic routing decisions.
    
    Args:
        state: Current FinancialState
        config: Optional configuration dict
        logger: Optional logger
        conversation_history: Optional formatted conversation history from previous sessions
        
    Returns:
        String name of the next agent node or "__end__"
    """
    
    try:
        # 🔥 CRITICAL FIX: Check if objective is already achieved BEFORE asking LLM
        # This prevents the LLM from suggesting to continue when user's goal is met
        main_logger = logger or get_logger()
        
        if _is_objective_achieved(state):
            explanation = f"✅ User's objective ({state.objective.value}) has been achieved. Ending workflow."
            if main_logger:
                main_logger.info("")
                main_logger.info("[SUPERVISOR] " + "=" * 80)
                main_logger.info(f"[SUPERVISOR] 🎯 OBJECTIVE ACHIEVED: {state.objective.value}")
                main_logger.info("[SUPERVISOR] " + "=" * 80)
                main_logger.info(f"[SUPERVISOR] {explanation}")
                
                # Show what was completed
                if state.objective == AnalysisObjective.MODEL_ONLY:
                    main_logger.info(f"[SUPERVISOR]    ✅ Financial data collected")
                    main_logger.info(f"[SUPERVISOR]    ✅ Financial model generated")
                    main_logger.info(f"[SUPERVISOR]    ⏭️  News analysis skipped (not requested)")
                    main_logger.info(f"[SUPERVISOR]    ⏭️  Report generation skipped (not requested)")
                elif state.objective == AnalysisObjective.QUICK_NEWS:
                    main_logger.info(f"[SUPERVISOR]    ✅ Financial data collected")
                    main_logger.info(f"[SUPERVISOR]    ✅ News analysis completed")
                    main_logger.info(f"[SUPERVISOR]    ⏭️  Financial model skipped (not requested)")
                    main_logger.info(f"[SUPERVISOR]    ⏭️  Report generation skipped (not requested)")
                elif state.objective == AnalysisObjective.CUSTOM:
                    main_logger.info(f"[SUPERVISOR]    ✅ Financial data collected")
                    main_logger.info(f"[SUPERVISOR]    ⏭️  Other tasks skipped (not requested)")
                
                main_logger.info("[SUPERVISOR] " + "=" * 80)
                main_logger.info("")
            
            # Log workflow completion
            _log_workflow_completion(state, logger)
            
            return "__end__"
        
        # Build prompt with current state
        completed_stages_str = "\n".join([f"  - {stage.value}" for stage in state.completed_stages]) or "  (none yet)"
        
        # Determine what analysis is still pending
        pending = []
        if not state.is_financial_data_collected():
            pending.append("Financial data collection")
        if not state.is_news_analyzed():
            pending.append("News analysis")
        if not state.is_model_generated():
            pending.append("Financial model generation")
        if not state.is_report_generated():
            pending.append("Report generation")
        pending_analysis_str = "\n".join([f"  - {p}" for p in pending]) or "  (all analysis complete)"
        
        # Available data summary
        available = []
        if state.is_financial_data_collected():
            available.append("Financial data")
        if state.is_news_analyzed():
            available.append("News analysis results")
        if state.is_model_generated():
            available.append("Financial models")
        available_data_str = "\n".join([f"  - {a}" for a in available]) or "  (no data collected yet)"
        
        prompt = ROUTING_PROMPT_TEMPLATE.format(
            ticker=state.ticker,
            company_name=state.company_name,
            objective=state.objective.value,
            current_stage=state.current_stage.value,
            completed_stages=completed_stages_str,
            has_financial_data=state.is_financial_data_collected(),
            has_news_analysis=state.is_news_analyzed(),
            has_model_generated=state.is_model_generated(),
            has_report_generated=state.is_report_generated(),
            pending_analysis=pending_analysis_str,
            available_data=available_data_str
        )
        
        # Add conversation history from previous sessions if available
        if conversation_history and "No previous" not in conversation_history:
            prompt = f"""{conversation_history}

---

{prompt}"""
        
        # Add user query context if provided
        if state.user_query and state.user_query != f"Analyze {state.ticker} ({state.company_name})":
            prompt = f"""## USER'S CUSTOM REQUEST

**User Query:** {state.user_query}

⚠️  IMPORTANT: The user has provided specific instructions above. Your routing decisions should align with their request while still following the mandatory workflow rules (financial data → model → news → report).

{prompt}"""
        
        # Build conversation history for context
        messages = [
            {"role": "system", "content": "You are a workflow supervisor. Respond with valid JSON only. You have complete freedom to route to any available agent."}
        ]
        
        # Add previous routing decisions as conversation history for context
        for i, routing in enumerate(state.routing_history[-3:], 1):  # Last 3 decisions
            # Add what the supervisor decided previously
            messages.append({
                "role": "assistant",
                "content": json.dumps({
                    "iteration": routing.get("iteration", i),
                    "next_node": routing.get("next_node"),
                    "reasoning": routing.get("reasoning", ""),
                    "supervisor_message": routing.get("supervisor_message", "")
                })
            })
            # Add a user message showing the result
            result_msg = f"Iteration {routing.get('iteration', i)} completed. Agent {routing.get('next_node')} finished."
            if routing.get("result"):
                result_msg += f" Result: {routing.get('result')}"
            messages.append({
                "role": "user",
                "content": result_msg
            })
        
        # Add current state prompt
        messages.append({"role": "user", "content": prompt})
        
        response, cost = get_llm()(messages, temperature=0.7)  # Increased temperature for more creative/conversational supervisor messages
        state.total_llm_cost += cost
        
        # Parse JSON response
        try:
            # Clean up the response - remove markdown code blocks if present
            cleaned_response = response.strip()
            if cleaned_response.startswith('```json'):
                cleaned_response = cleaned_response[7:]  # Remove ```json
            if cleaned_response.startswith('```'):
                cleaned_response = cleaned_response[3:]  # Remove ```
            if cleaned_response.endswith('```'):
                cleaned_response = cleaned_response[:-3]  # Remove trailing ```
            cleaned_response = cleaned_response.strip()
            
            response_data = json.loads(cleaned_response)
            next_node = response_data.get("next_node")
            reasoning = response_data.get("reasoning", "")
            confidence = response_data.get("confidence", 0.5)
            supervisor_message = response_data.get("supervisor_message", "")
            
            # Validate next_node
            valid_nodes = [
                AgentNode.FINANCIAL_DATA_AGENT.value,
                AgentNode.NEWS_ANALYSIS_AGENT.value,
                AgentNode.MODEL_GENERATION_AGENT.value,
                AgentNode.REPORT_GENERATOR_AGENT.value,
                AgentNode.END.value
            ]
            
            if next_node not in valid_nodes:
                raise ValueError(f"Invalid next_node from LLM: {next_node}")
            
            # 🔥 FIX #1: INTELLIGENT DEPENDENCY RESOLUTION
            # Instead of rejecting bad routing decisions, auto-correct them with path planning
            main_logger = logger or get_logger()
            actual_next_node, was_redirected, resolution_explanation = _resolve_dependencies(state, next_node, logger)
            
            if was_redirected:
                # LLM made a bad routing decision - we auto-corrected it
                state.log_action(
                    agent="supervisor_dependency_resolver",
                    action="auto_correct_routing",
                    details={
                        "llm_wanted": next_node,
                        "actual_route": actual_next_node,
                        "reason": resolution_explanation,
                        "llm_reasoning": reasoning
                    }
                )
                if main_logger:
                    main_logger.warning(f"[DEPENDENCY RESOLVER] ⚠️  LLM routing required correction")
                    main_logger.info(f"[DEPENDENCY RESOLVER] 🎯 LLM wanted: {next_node}")
                    main_logger.info(f"[DEPENDENCY RESOLVER] ✅ Auto-corrected to: {actual_next_node}")
                    main_logger.info(f"[DEPENDENCY RESOLVER] 📝 Reason: {resolution_explanation}")
                
                # Use the corrected node
                next_node = actual_next_node
                # Update reasoning to reflect the correction
                reasoning = f"[AUTO-CORRECTED] {resolution_explanation} (Original LLM reasoning: {reasoning})"
            
            # Write the LLM's conversational message to the main info.log
            try:
                main_logger = logger or get_logger()
                if main_logger:
                    # Add current state summary with [SUPERVISOR] prefix (technical info)
                    main_logger.info("")
                    main_logger.info("[SUPERVISOR] 📊 Current State Summary:")
                    main_logger.info(f"[SUPERVISOR]    • Financial Data: {'✅ Collected' if state.is_financial_data_collected() else '❌ Not collected'}")
                    main_logger.info(f"[SUPERVISOR]    • Financial Model: {'✅ Generated' if state.is_model_generated() else '❌ Not generated (REQUIRED for report)'}")
                    main_logger.info(f"[SUPERVISOR]    • News Analysis: {'✅ Completed' if state.is_news_analyzed() else '❌ Not completed (REQUIRED for report)'}")
                    main_logger.info(f"[SUPERVISOR]    • Analyst Report: {'✅ Generated' if state.is_report_generated() else '⏳ Pending'}")
                    if not state.is_model_generated() or not state.is_news_analyzed():
                        missing = []
                        if not state.is_model_generated():
                            missing.append("financial model")
                        if not state.is_news_analyzed():
                            missing.append("news analysis")
                        main_logger.info(f"[SUPERVISOR]    ⚠️  Missing prerequisites for report: {', '.join(missing)}")
                    main_logger.info("")
                    
                    # LLM response - use [LLM] prefix for natural language responses (UI display)
                    if supervisor_message:
                        main_logger.info(f"[LLM] {supervisor_message}")
                        main_logger.info(f"[SUPERVISOR] → Next action: {next_node} (confidence: {confidence:.0%})")
                    else:
                        # Fallback to reasoning if no supervisor_message
                        main_logger.info(f"[LLM] {reasoning.strip()}")
                        main_logger.info(f"[SUPERVISOR] → Next action: {next_node} (confidence: {confidence:.0%})")
                    main_logger.info("")
                    
                    # Force flush to ensure log is written immediately
                    for handler in main_logger.logger.handlers:
                        handler.flush()
            except Exception as log_error:
                # Log the error but don't fail the routing
                pass

            # Log the LLM decision with structured details for machine consumption
            state.log_action(
                agent="supervisor_llm_flexible",
                action="route_decision",
                details={
                    "next": next_node,
                    "reasoning": reasoning,
                    "confidence": confidence,
                    "supervisor_message": supervisor_message
                }
            )
            
            # Save routing decision to history for conversation context
            state.routing_history.append({
                "iteration": len(state.routing_history) + 1,
                "next_node": next_node,
                "reasoning": reasoning,
                "confidence": confidence,
                "supervisor_message": supervisor_message,
                "timestamp": datetime.now().isoformat()
            })
            
            # Update state based on routing decision
            if next_node == AgentNode.FINANCIAL_DATA_AGENT.value:
                state.next_agent = AgentNode.FINANCIAL_DATA_AGENT
            elif next_node == AgentNode.NEWS_ANALYSIS_AGENT.value:
                state.next_agent = AgentNode.NEWS_ANALYSIS_AGENT
            elif next_node == AgentNode.MODEL_GENERATION_AGENT.value:
                state.next_agent = AgentNode.MODEL_GENERATION_AGENT
            elif next_node == AgentNode.REPORT_GENERATOR_AGENT.value:
                state.next_agent = AgentNode.REPORT_GENERATOR_AGENT
            else:  # AgentNode.END.value
                state.current_stage = PipelineStage.COMPLETED
                state.next_agent = AgentNode.END
                
                # Log workflow completion
                _log_workflow_completion(state, logger)
            
            return next_node
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {response[:200]}...")
        
    except Exception as e:
        # Fall back to deterministic routing
        state.log_error("supervisor_llm_flexible", str(e), {"fallback": "deterministic routing"})
        return route_workflow(state, config, logger)
