"""
session_manager.py - Session Management for Supervisor Conversations

Provides persistent conversation memory across workflow runs.
Sessions are stored per-user and per-ticker, allowing the supervisor to maintain context
of previous analyses, queries, and routing decisions for each user.

Session Storage Structure:
    data/{email}/sessions/{ticker}/{session_name}.json

Session Data Format:
{
    "session_name": "mysession",
    "ticker": "AAPL",
    "company_name": "Apple Inc.",
    "created_at": "2025-11-03T10:30:00",
    "last_updated": "2025-11-03T11:45:00",
    "conversation_history": [
        {
            "timestamp": "2025-11-03T10:30:00",
            "user_query": "Analyze AAPL focusing on AI capabilities",
            "routing_decisions": ["financial_data_agent", "news_analysis_agent", ...],
            "completion_status": "completed",
            "key_findings": "Brief summary of what was learned"
        },
        ...
    ]
}
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any


class SessionManager:
    """Manages persistent conversation sessions for the supervisor."""
    
    def __init__(self, email: str, ticker: str, session_name: Optional[str] = None):
        """
        Initialize session manager.
        
        Args:
            email: User email (for organizing sessions by user)
            ticker: Stock ticker symbol
            session_name: Name of the session (optional, defaults to 'default')
        """
        self.email = email.lower()
        self.ticker = ticker.upper()
        self.session_name = session_name or "default"
        
        # Session directory: data/{email}/sessions/{ticker}/
        self.session_dir = Path("data") / self.email / "sessions" / self.ticker
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Session file: data/{email}/sessions/{ticker}/{session_name}.json
        self.session_file = self.session_dir / f"{self.session_name}.json"
        
        # Load existing session or create new one
        self.session_data = self._load_or_create_session()
    
    def _load_or_create_session(self) -> Dict[str, Any]:
        """Load existing session or create a new one."""
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r') as f:
                    data = json.load(f)
                    # Validate session data
                    if data.get("ticker") != self.ticker:
                        raise ValueError(f"Session ticker mismatch: {data.get('ticker')} != {self.ticker}")
                    return data
            except Exception as e:
                print(f"⚠️  Warning: Failed to load session '{self.session_name}': {e}")
                print(f"   Creating new session...")
        
        # Create new session
        return {
            "session_name": self.session_name,
            "ticker": self.ticker,
            "company_name": "",  # Will be set when first run
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "conversation_history": []
        }
    
    def add_conversation(self, 
                        user_query: str, 
                        company_name: str,
                        routing_decisions: List[str],
                        completion_status: str,
                        key_findings: Optional[str] = None,
                        statistics: Optional[Dict] = None,
                        error_message: Optional[str] = None) -> None:
        """
        Add a new conversation to the session history.
        
        Args:
            user_query: The user's query/instructions for this run
            company_name: Company name
            routing_decisions: List of agents that were routed to
            completion_status: Status of the workflow (completed, failed, in_progress, etc.)
            key_findings: Brief summary of findings (optional)
            statistics: Workflow statistics (optional)
            error_message: Error message if the workflow failed (optional)
        """
        conversation_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_query": user_query,
            "routing_decisions": routing_decisions,
            "completion_status": completion_status,
            "key_findings": key_findings,
            "statistics": statistics,
            "error_message": error_message
        }
        
        self.session_data["conversation_history"].append(conversation_entry)
        self.session_data["company_name"] = company_name
        self.session_data["last_updated"] = datetime.now().isoformat()
        
        # Save to disk
        self.save()
    
    def start_conversation(self, user_query: str, company_name: str) -> int:
        """
        Start a new conversation and save it immediately.
        This ensures the user query is saved even if the program crashes.
        
        Args:
            user_query: The user's query/instructions for this run
            company_name: Company name
            
        Returns:
            Index of the conversation in the history (0-based)
        """
        conversation_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_query": user_query,
            "routing_decisions": [],
            "completion_status": "in_progress",
            "key_findings": None,
            "statistics": None,
            "error_message": None
        }
        
        self.session_data["conversation_history"].append(conversation_entry)
        self.session_data["company_name"] = company_name
        self.session_data["last_updated"] = datetime.now().isoformat()
        
        # Save to disk immediately
        self.save()
        
        return len(self.session_data["conversation_history"]) - 1
    
    def update_conversation(self, 
                          conversation_index: int,
                          routing_decisions: Optional[List[str]] = None,
                          completion_status: Optional[str] = None,
                          key_findings: Optional[str] = None,
                          statistics: Optional[Dict] = None,
                          error_message: Optional[str] = None,
                          analysis_results: Optional[Dict] = None) -> None:
        """
        Update an in-progress conversation with new information.
        This is called after each agent completes or when workflow state changes.
        
        Args:
            conversation_index: Index of the conversation to update
            routing_decisions: Updated list of agents (optional)
            completion_status: Updated status (optional)
            key_findings: Updated findings (optional)
            statistics: Updated statistics (optional)
            error_message: Error message if the workflow failed (optional)
            analysis_results: Rich context about analysis results for LLM continuation (optional)
        """
        if conversation_index < 0 or conversation_index >= len(self.session_data["conversation_history"]):
            print(f"⚠️  Warning: Invalid conversation index {conversation_index}")
            return
        
        conversation = self.session_data["conversation_history"][conversation_index]
        
        # Update fields that are provided
        if routing_decisions is not None:
            conversation["routing_decisions"] = routing_decisions
        if completion_status is not None:
            conversation["completion_status"] = completion_status
        if key_findings is not None:
            conversation["key_findings"] = key_findings
        if statistics is not None:
            conversation["statistics"] = statistics
        if error_message is not None:
            conversation["error_message"] = error_message
        if analysis_results is not None:
            conversation["analysis_results"] = analysis_results
        
        self.session_data["last_updated"] = datetime.now().isoformat()
        
        # Save to disk immediately
        self.save()
    
    def get_conversation_history(self, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Get recent conversation history.
        
        Args:
            limit: Maximum number of recent conversations to return
        
        Returns:
            List of recent conversation entries
        """
        history = self.session_data.get("conversation_history", [])
        return history[-limit:] if limit > 0 else history
    
    def get_conversation_summary(self, limit: int = 3) -> str:
        """
        Generate a text summary of recent conversations for LLM context.
        Includes analysis results if available.
        
        Args:
            limit: Maximum number of recent conversations to include
        
        Returns:
            Formatted text summary
        """
        history = self.get_conversation_history(limit)
        
        if not history:
            return "No previous conversation history in this session."
        
        summary_lines = [f"## Previous Conversation History (Session: {self.session_name})"]
        summary_lines.append("")
        
        for i, conv in enumerate(history, 1):
            timestamp = conv.get("timestamp", "Unknown")
            user_query = conv.get("user_query", "")
            status = conv.get("completion_status", "unknown")
            agents = conv.get("routing_decisions", [])
            findings = conv.get("key_findings", "")
            analysis_results = conv.get("analysis_results", {})
            
            summary_lines.append(f"**Conversation {i}** ({timestamp}):")
            summary_lines.append(f"- User Query: \"{user_query}\"")
            summary_lines.append(f"- Status: {status}")
            summary_lines.append(f"- Agents Used: {', '.join(agents) if agents else 'None (direct answer)'}")
            if findings:
                summary_lines.append(f"- Key Findings: {findings}")
            
            # Include analysis results if available
            if analysis_results:
                # Valuation data
                valuation = analysis_results.get("valuation", {})
                if valuation:
                    summary_lines.append(f"- **Valuation Analysis**:")
                    if "current_price" in valuation:
                        summary_lines.append(f"  - Current Stock Price: ${valuation.get('current_price', 'N/A')}")
                    if "fair_value" in valuation:
                        summary_lines.append(f"  - Fair Value: ${valuation.get('fair_value', 'N/A')}")
                    if "upside_downside" in valuation:
                        upside = valuation.get('upside_downside', 0)
                        summary_lines.append(f"  - Upside/Downside: {upside:+.2f}%")
                    if "model_type" in valuation:
                        summary_lines.append(f"  - Model Used: {valuation.get('model_type', 'N/A')}")
                
                # News summary
                news = analysis_results.get("news_summary", {})
                if news:
                    summary_lines.append(f"- **News Analysis**:")
                    if "articles_analyzed" in news:
                        summary_lines.append(f"  - Articles Analyzed: {news.get('articles_analyzed', 0)}")
                    if "overall_sentiment" in news:
                        summary_lines.append(f"  - Overall Sentiment: {news.get('overall_sentiment', 'N/A')}")
                    
                    # Catalysts
                    catalysts = news.get("top_catalysts", [])
                    if catalysts:
                        summary_lines.append(f"  - **Key Catalysts** ({len(catalysts)}):")
                        for catalyst in catalysts[:3]:  # Top 3
                            summary_lines.append(f"    • {catalyst}")
                    
                    # Risks
                    risks = news.get("top_risks", [])
                    if risks:
                        summary_lines.append(f"  - **Key Risks** ({len(risks)}):")
                        for risk in risks[:3]:  # Top 3
                            summary_lines.append(f"    • {risk}")
                
                # Report info
                report = analysis_results.get("report", {})
                if report and "path" in report:
                    summary_lines.append(f"- **Report Generated**: {report.get('path', 'N/A')}")
            
            summary_lines.append("")
        
        return "\n".join(summary_lines)
    
    def save(self) -> None:
        """Save session data to disk."""
        try:
            with open(self.session_file, 'w') as f:
                json.dump(self.session_data, f, indent=2)
        except Exception as e:
            print(f"⚠️  Warning: Failed to save session: {e}")
    
    def clear_history(self) -> None:
        """Clear all conversation history in this session."""
        self.session_data["conversation_history"] = []
        self.session_data["last_updated"] = datetime.now().isoformat()
        self.save()
    
    def delete_session(self) -> bool:
        """
        Delete this session file.
        
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            if self.session_file.exists():
                self.session_file.unlink()
                return True
            return False
        except Exception as e:
            print(f"⚠️  Failed to delete session: {e}")
            return False
    
    @staticmethod
    def list_sessions(ticker: str) -> List[str]:
        """
        List all sessions for a ticker.
        
        Args:
            ticker: Stock ticker symbol
        
        Returns:
            List of session names
        """
        session_dir = Path("data") / "sessions" / ticker.upper()
        
        if not session_dir.exists():
            return []
        
        return [f.stem for f in session_dir.glob("*.json")]
    
    @staticmethod
    def get_session_info(ticker: str, session_name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a session without loading the full manager.
        
        Args:
            ticker: Stock ticker symbol
            session_name: Session name
        
        Returns:
            Session metadata or None if not found
        """
        session_file = Path("data") / "sessions" / ticker.upper() / f"{session_name}.json"
        
        if not session_file.exists():
            return None
        
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
                return {
                    "session_name": data.get("session_name"),
                    "ticker": data.get("ticker"),
                    "company_name": data.get("company_name"),
                    "created_at": data.get("created_at"),
                    "last_updated": data.get("last_updated"),
                    "conversation_count": len(data.get("conversation_history", []))
                }
        except Exception:
            return None
