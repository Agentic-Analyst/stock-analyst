"""
The generalizable agent — a ReAct tool-use loop that replaces the ticker-centric
entry point.

Instead of demanding a single ticker up front (and bouncing everything else to a
canned greeting), this agent is handed a toolbox and reasons about ANY financial
request: it decides which tool(s) to call (or none), calls them, reads the JSON
results, and either calls more tools or writes the final answer. There is NO
intent taxonomy — generality comes from the model reasoning over the tools.

Tools available (see agents/tools/):
  * our four pipeline agents wrapped as tools: get_financials, build_model,
    analyze_news, write_report (all Phase 1–4 behaviour intact inside them);
  * keyless data tools: resolve_symbol (any-language), get_prices, get_technicals,
    get_global_news, and get_macro (when the free FRED key is set).

Contracts preserved for the rest of the stack:
  * When a run commits to a single ticker, the AgentContext prints
    ``[SUPERVISOR] ✅ Identified ticker: <T>`` (api-runner scrapes it).
  * The final answer is emitted on the Phase 2 ``[ANSWER_BEGIN]/[ANSWER_END]``
    channel and written to ``answer.md`` — the frontend renders it as the reply.
  * The run always ends by printing ``THE ENTIRE PROGRAM IS COMPLETED`` +
    ``SESSION_ID:`` (handled by main.py around this).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from llms.async_client import get_async_llm
from agents.tools.base import ToolRegistry
from agents.tools.analysis_tools import AgentContext, build_analysis_tools
from agents.tools.data_tools import build_data_tools


SYSTEM_PROMPT = """You are VYNN, a sharp, friendly senior equity research analyst and financial assistant. You help users with ANY financial or market question — analyzing companies, valuation, news, macro, trading strategy, portfolios, or general market questions.

You have TOOLS you can call to get real, current data and to run deep analysis. Reason about what the user actually wants, then use the right tools. You are NOT limited to one stock, and you must NEVER bounce a real question with a generic "I can analyze stocks, try asking about Apple" message.

## How to decide what to do
- **A specific company** ("analyze NVDA", "分析诺普信", "build a model for the green-coffee company"): identify the company and its ticker. If you're not 100% sure of the ticker (especially non-English names or descriptions), call `resolve_symbol`. CRITICAL: `resolve_symbol` searches in Latin script — so you MUST translate/transliterate the name to English or pinyin BEFORE calling it. For "分析诺普信" you already know 诺普信 = "Noposion", so call resolve_symbol with query="Noposion" (NOT the Chinese characters). For "贵州茅台" call it with "Kweichow Moutai". For "腾讯" call it with "Tencent". Use your own knowledge to do this translation. If you already know the exact ticker from your knowledge (e.g. Apple = AAPL), you may skip resolve_symbol and use it directly. Then use the analysis tools: `get_financials`, `build_model`, `analyze_news`, or `write_report`. For "analyze X comprehensively" or "should I buy X", use `write_report` (it runs the full pipeline). For a quick data point, use the lighter tool.
- **A market/macro question** ("how would falling rates affect banks?", "what happened in markets today?"): answer as an expert. Pull live data when it sharpens the answer — `get_macro` for rates/inflation/yield-curve, `get_global_news` for today's market news, `get_prices`/`get_technicals` for specific names. If a data tool isn't available, answer from your own knowledge and say it isn't live.
- **A trading strategy / watchlist** ("the market looks weak, flag breakdowns on my names — losing the 200-day"): ENGAGE with it as a strategist. Discuss the setup, and if names are given, use `get_technicals` to check the actual levels (200-day, RSI, etc.). Be honest that you don't place live alerts, but still give real value.
- **Multiple companies** ("compare NVDA and AMD"): call the tools for each and compare.
- **Genuine chit-chat only** ("hi", "who are you", "thanks"): reply briefly and warmly in 1-2 sentences, and invite their question. Do NOT dump a capabilities list. Only true small talk counts as chit-chat — a company name, a market question, or a strategy is NEVER chit-chat.

## CRITICAL: never analyze without a real company
- The analysis tools (get_financials, build_model, analyze_news, write_report) need a REAL ticker. NEVER call them with a placeholder like "CHAT", "PENDING", or a guess.
- If the user asks for analysis but you don't yet know which company (e.g. a vague "give me a detailed analysis" with no company mentioned and nothing in the conversation context), DO NOT run any analysis tool. Instead, ask them which company/ticker they want — briefly and helpfully. A wrong or empty analysis is far worse than a quick clarifying question.
- Only after you have a concrete company (from the user, the conversation context, or resolve_symbol) do you call the analysis tools.

## Depth: answer well, then offer to go deeper
- Give a genuinely useful answer — not a shallow one-liner. Bring in the relevant angles (numbers, drivers, risks, context) the question deserves.
- BUT for anything that could warrant a fuller treatment, END by offering a concrete next step the user can take: e.g. "Want me to build the full DCF model and report for X?", "I can pull the live technicals and news to confirm — want that?", "I can break this into a bull/base/bear scenario table." Make the offer specific to what you'd actually do.
- Match effort to the question: a factual lookup stays short; "analyze X" / "should I buy" deserves the full pipeline (write_report) and a thorough synthesis.

## Style
- Answer the user's ACTUAL question directly and first. Lead with the point.
- Ground claims in the data your tools return — cite real numbers (price, fair value, upside %, RSI, sentiment, macro values).
- Warm, precise, second person.
- If a tool fails or data is missing, say so honestly and answer with what you have — never fabricate numbers.
- When you've produced a downloadable artifact (model/report), reference its FINDINGS, not the file.

When you have enough to answer, write the final answer as plain text (no more tool calls). That text is what the user sees.
"""


class GeneralistAgent:
    """Drives the ReAct tool-use loop for one chat turn."""

    def __init__(self, email: str, timestamp: str, user_prompt: str,
                 session_id: Optional[str] = None, conversation_context: Optional[str] = None,
                 max_iterations: int = 8):
        self.email = email
        self.timestamp = timestamp
        self.user_prompt = user_prompt
        self.session_id = session_id
        self.conversation_context = conversation_context
        self.max_iterations = max_iterations

        self.ctx = AgentContext(email, timestamp, user_prompt)
        self.registry = ToolRegistry()
        self.registry.register_all(build_analysis_tools(self.ctx))
        self.registry.register_all(build_data_tools())
        self.total_cost = 0.0
        self._called_once = set()  # for non-repeatable dedup (none currently, future-proof)

    # -- logging that mirrors the supervisor's channels --
    def _log(self, msg: str):
        if self.ctx.logger:
            self.ctx.logger.info(msg)
        else:
            print(msg)

    def _friendly_progress(self, tool_name: str, args: dict) -> str:
        """
        Human-readable progress line for a tool call, shown live in the UI status
        area (matched by api-runner's progress extractor). Returns "" if the tool
        needs no announcement.
        """
        t = (args or {}).get("ticker") or (args or {}).get("query") or (args or {}).get("indicator") or ""
        t = str(t).upper() if t else ""
        # Emoji chosen from the set the frontend's progress extractor recognizes
        # (📊📈📉🔍💰🎯⚡🚀📋📄📑💹🏢📰) so these surface in the live status area.
        mapping = {
            "resolve_symbol": f"🔍 Looking up {args.get('query', 'the company')}",
            "get_financials": f"📊 Fetching financial data for {t}",
            "build_model": f"💹 Building the DCF valuation model for {t} (takes ~30s)",
            "analyze_news": f"📰 Analyzing news for {t}, screening articles in parallel",
            "write_report": f"📋 Running the full analysis for {t}: financials, model, news, and report",
            "get_prices": f"📈 Pulling price history for {t}",
            "get_technicals": f"📉 Computing technical indicators for {t}",
            "get_global_news": "🔍 Checking the latest market news",
            "get_macro": f"🏢 Fetching macro data {args.get('indicator', '')}".strip(),
        }
        return mapping.get(tool_name, "")

    def _emit_answer(self, answer_text: str):
        """Emit on the Phase 2 structured answer channel + persist answer.md."""
        answer_text = (answer_text or "").strip()
        if not answer_text:
            answer_text = "I wasn't able to produce an answer for that. Could you rephrase or give me a bit more detail?"
        # Guarantee a folder/logger (CHAT folder if no ticker was committed).
        self.ctx.ensure_base_logger()
        # Persist answer.md into the run folder.
        try:
            folder = self.ctx.base_path
            if folder is not None:
                p = Path(folder) / "answer.md"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(answer_text, encoding="utf-8")
        except Exception:
            pass
        self._log("")
        self._log("[ANSWER_BEGIN]")
        for line in answer_text.split("\n"):
            self._log(f"[LLM] {line}")
        self._log("[ANSWER_END]")
        self._log("")

    async def run(self) -> dict:
        """
        Run the tool-use loop and emit the final answer. Returns a small result dict.
        """
        # Ensure a logger + folder exist up front (CHAT folder until/unless a
        # ticker is committed) so ALL reasoning + tool-call lines land in
        # info.log — not just stdout. Restores the observability the old
        # supervisor had.
        self.ctx.ensure_base_logger()

        provider = get_async_llm()
        is_openai = provider.is_openai

        # Build the initial transcript.
        user_content = self.user_prompt
        if self.conversation_context and self.conversation_context.strip() and \
           self.conversation_context.strip().lower() != "no previous conversation":
            user_content = (
                f"[Recent conversation for context]\n{self.conversation_context}\n\n"
                f"[Current message]\n{self.user_prompt}"
            )

        if is_openai:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
            tool_defs = self.registry.openai_defs()
        else:
            # Anthropic: system is a separate kwarg (our client extracts role==system).
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]
            tool_defs = self.registry.anthropic_defs()

        print("[SUPERVISOR] 🧠 Generalist agent reasoning about the request...")
        final_text = ""

        for iteration in range(self.max_iterations):
            is_last = iteration == self.max_iterations - 1
            # On the last allowed turn, drop tools to force a text answer.
            turn_tools = [] if is_last else tool_defs
            try:
                resp = await provider.call_with_tools(
                    messages, turn_tools, temperature=0.4,
                )
            except Exception as e:
                self._log(f"[SUPERVISOR] ❌ LLM turn failed: {e}")
                final_text = ("I hit an error while working on that. Please try again in a moment.")
                break

            self.total_cost += resp.cost

            if not resp.has_tool_calls:
                final_text = resp.text
                break

            # Log the model's brief narration (its "thinking") if any.
            if resp.text.strip():
                self._log(f"[SUPERVISOR] 💭 {resp.text.strip()[:300]}")

            # Append the assistant turn (provider-native) so tool_results attach correctly.
            messages.append(resp.raw)

            # Execute the requested tools (sequentially — simplest + safe; the heavy
            # tools already parallelize internally). For each, emit a HUMAN-FRIENDLY
            # progress line the frontend surfaces live (so the user sees "Building
            # the valuation model…" instead of a silent wait), plus the technical
            # detail line for the collapsible log.
            tool_result_blocks = []  # anthropic
            for call in resp.tool_calls:
                friendly = self._friendly_progress(call.name, call.arguments)
                if friendly:
                    self._log(friendly)  # picked up by the progress extractor
                self._log(f"[SUPERVISOR] 🔧 {call.name}({json.dumps(call.arguments, ensure_ascii=False)})")
                result_json = await self.registry.execute(call.name, call.arguments)
                # Log a one-line result status so the log shows what each tool returned.
                try:
                    _rd = json.loads(result_json)
                    _status = _rd.get("status", "ok")
                    _note = _rd.get("note") or _rd.get("error") or ""
                    self._log(f"[SUPERVISOR]    ↳ {call.name}: {_status}{(' — ' + str(_note)[:120]) if _note else ''}")
                except Exception:
                    pass
                if is_openai:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result_json,
                    })
                else:
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": result_json,
                    })
            if not is_openai and tool_result_blocks:
                messages.append({"role": "user", "content": tool_result_blocks})

        # If we exhausted iterations without a text answer, ask for one more plain turn.
        if not final_text:
            try:
                resp = await provider.call_with_tools(messages, [], temperature=0.4)
                final_text = resp.text
                self.total_cost += resp.cost
            except Exception:
                final_text = "I gathered some information but ran out of steps before summarizing. Please ask again."

        self._emit_answer(final_text)
        self._log(f"[SUPERVISOR] 💰 Total LLM cost: ${self.total_cost:.4f}")

        # Persist this turn to the session so follow-ups have context.
        self._save_session(final_text)

        # Completion contract: print SESSION_ID + THE ENTIRE PROGRAM IS COMPLETED.
        if self.ctx.logger and hasattr(self.ctx.logger, "program_end"):
            self.ctx.logger.program_end()

        return {
            "status": "completed",
            "ticker": self.ctx.ticker or "CHAT",
            "company_name": self.ctx.company_name,
            "session_name": self.ctx.session_name,
            "answer": final_text,
            "total_cost": self.total_cost,
        }

    def _save_session(self, answer_text: str):
        """
        Append this turn to the on-disk session (best-effort, additive) so a
        follow-up in the same session_id gets conversation context. Uses the same
        SessionManager format the supervisor path uses.
        """
        try:
            from src.session_manager import SessionManager
            ticker = self.ctx.ticker or "CHAT"
            sm = SessionManager(
                email=self.email, ticker=ticker,
                session_name=self.ctx.session_name or (self.session_id or f"chat_{self.timestamp}"),
            )
            idx = sm.start_conversation(user_query=self.user_prompt, company_name=self.ctx.company_name)
            sm.update_conversation(
                conversation_index=idx,
                completion_status="completed",
                key_findings=answer_text[:500],
            )
        except Exception:
            pass  # session persistence must never break the answer
