"""
Async tool framework for the generalizable agent.

A `Tool` is a single capability the agent can choose to call: resolve a symbol,
fetch prices, analyze news, build a model, write a report, get macro data, etc.
The agent (a ReAct loop) is handed the whole `ToolRegistry`, decides which tool(s)
a free-form request needs, calls them, reads the JSON results, and either calls
more tools or writes the final answer. There is NO fixed pipeline and NO intent
taxonomy — generality comes from the model reasoning over this toolbox.

Design (adapted from Vibe-Trading's BaseTool/ToolRegistry, MIT-licensed, made
async-native for our stack):

* Tools are **async** (`await tool.execute(**kwargs)`) — our task agents and LLM
  client are already async, so wrapping them is natural and non-blocking.
* Tools return a **JSON string** (a dict serialized). By convention it carries a
  ``status`` of "ok" | "error" so the loop can detect failure without exceptions
  leaking. The registry guarantees a JSON error envelope even if a tool raises.
* Schemas auto-generate from `name`/`description`/`parameters` (JSON Schema). The
  registry can emit both OpenAI- and Anthropic-shaped tool definitions so the same
  tool objects work across providers.
* `check_available()` lets a tool exclude itself when a dependency/key is missing,
  so the agent never sees a tool it can't run.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def tool_ok(**payload: Any) -> str:
    """Serialize a successful tool result as a JSON string with status=ok."""
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False, default=str)


def tool_error(message: str, **payload: Any) -> str:
    """Serialize a tool error as a JSON string with status=error."""
    return json.dumps({"status": "error", "error": message, **payload}, ensure_ascii=False, default=str)


class Tool(ABC):
    """
    Base class for an agent-callable tool.

    Subclasses set the class attributes and implement ``async execute``. Keep the
    ``description`` written for the MODEL — it's how the agent decides when to
    reach for this tool — and make ``parameters`` a valid JSON Schema object.
    """

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    # Whether the tool may be called more than once in a single run (e.g. price
    # lookups for different tickers). Non-repeatable tools are dedup-suppressed.
    repeatable: bool = True
    # Read-only tools have no side effects and may run concurrently.
    is_readonly: bool = True

    @classmethod
    def check_available(cls) -> bool:
        """Return False to exclude this tool (missing dep/key). Override as needed."""
        return True

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Run the tool and return a JSON string (use tool_ok/tool_error)."""
        raise NotImplementedError

    # -- schema emitters (per provider) --
    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }

    def to_anthropic_schema(self) -> Dict[str, Any]:
        # Anthropic's tools API uses input_schema instead of parameters.
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters or {"type": "object", "properties": {}},
        }


class ToolRegistry:
    """Holds the set of tools available to the agent and dispatches calls."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> "ToolRegistry":
        """Register a tool if its dependencies are met. Returns self (chainable)."""
        try:
            available = tool.check_available()
        except Exception as exc:  # a broken check must not crash startup
            logger.warning("check_available failed for %s: %s", getattr(tool, "name", "?"), exc)
            available = False
        if available:
            self._tools[tool.name] = tool
        else:
            logger.info("Tool %s excluded (dependencies not met)", getattr(tool, "name", "?"))
        return self

    def register_all(self, tools: List[Tool]) -> "ToolRegistry":
        for t in tools:
            self.register(t)
        return self

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def openai_defs(self) -> List[Dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def anthropic_defs(self) -> List[Dict[str, Any]]:
        return [t.to_anthropic_schema() for t in self._tools.values()]

    async def execute(self, name: str, params: Dict[str, Any]) -> str:
        """
        Execute a tool by name, guaranteeing a valid JSON string return value even
        on unknown-tool or exception (so the ReAct loop never sees a raw traceback).
        """
        tool = self._tools.get(name)
        if not tool:
            return tool_error(f"Tool '{name}' not found", tool=name)
        try:
            result = await tool.execute(**(params or {}))
            # Tolerate a tool that returns a dict instead of a JSON string.
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, default=str)
            return result if isinstance(result, str) else json.dumps(result, default=str)
        except TypeError as exc:
            # Usually a bad-arguments call from the model — report it so it can retry.
            logger.warning("Tool %s bad arguments: %s", name, exc)
            return tool_error(f"Invalid arguments for '{name}': {exc}", tool=name)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return tool_error(str(exc), tool=name)

    def is_repeatable(self, name: str) -> bool:
        t = self._tools.get(name)
        return bool(t and t.repeatable)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
