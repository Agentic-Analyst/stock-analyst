"""
session_manager.py - Session Management for Supervisor Conversations

Provides persistent conversation memory across workflow runs.
Sessions are stored per-ticker and allow the supervisor to maintain context
of previous analyses, queries, and routing decisions.

Session Storage Structure:
    data/sessions/{ticker}/{session_name}.json

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
    
    def __init__(self, ticker: str, session_name: Optional[str] = None):
        """
        Initialize session manager.
        
        Args:
            ticker: Stock ticker symbol
            session_name: Name of the session (optional, defaults to 'default')
        """
        self.ticker = ticker.upper()
        self.session_name = session_name or "default"
        
        # Session directory: data/sessions/{ticker}/
        self.session_dir = Path("data") / "sessions" / self.ticker
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Session file: data/sessions/{ticker}/{session_name}.json
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
                        statistics: Optional[Dict] = None) -> None:
        """
        Add a new conversation to the session history.
        
        Args:
            user_query: The user's query/instructions for this run
            company_name: Company name
            routing_decisions: List of agents that were routed to
            completion_status: Status of the workflow (completed, failed, etc.)
            key_findings: Brief summary of findings (optional)
            statistics: Workflow statistics (optional)
        """
        conversation_entry = {
            "timestamp": datetime.now().isoformat(),
            "user_query": user_query,
            "routing_decisions": routing_decisions,
            "completion_status": completion_status,
            "key_findings": key_findings,
            "statistics": statistics
        }
        
        self.session_data["conversation_history"].append(conversation_entry)
        self.session_data["company_name"] = company_name
        self.session_data["last_updated"] = datetime.now().isoformat()
        
        # Save to disk
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
            
            summary_lines.append(f"**Conversation {i}** ({timestamp}):")
            summary_lines.append(f"- User Query: \"{user_query}\"")
            summary_lines.append(f"- Status: {status}")
            summary_lines.append(f"- Agents Used: {', '.join(agents)}")
            if findings:
                summary_lines.append(f"- Key Findings: {findings}")
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
