"""QuestChain engine — async agent loop.

The loop:
  1. Load conversation history from JSONL (ContextManager)
  2. Compact if context is tight
  3. Add user message
  4. Stream model response
  5. If tool calls → execute (parallel) → append results → goto 4
  6. If text → yield tokens to caller → done
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Awaitable, Callable

from questchain.engine.context import ContextManager
from questchain.engine.model import OllamaModel
from questchain.engine.skills import SkillsManager
from questchain.engine.tools import ToolRegistry

logger = logging.getLogger(__name__)

HEARTBEAT_OK = "HEARTBEAT_OK"
_MAX_ITERATIONS = 30


class Agent:
    """Async ReAct agent: model + tools + JSONL context + skills."""

    def __init__(
        self,
        model: OllamaModel,
        tools: ToolRegistry,
        skills: SkillsManager,
        system_prompt: str,
        agent_name: str = "QuestChain",
    ):
        self.model = model
        self.tools = tools
        self.skills = skills
        self.agent_name = agent_name
        self._base_system_prompt = system_prompt

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        user_input: str,
        thread_id: str,
        on_tool_call: Callable[[str, dict], Awaitable[None]] | None = None,
        max_iterations: int = _MAX_ITERATIONS,
    ) -> AsyncIterator[str]:
        """Run the agent loop, yielding response text tokens as they stream.

        Args:
            user_input: The user's message.
            thread_id: Conversation thread identifier (used for JSONL persistence).
            on_tool_call: Optional async callback called with (tool_name, tool_args)
                          before each tool execution — used by the CLI to display
                          "Using tool: …" indicators.
            max_iterations: Safety cap on tool-call loops.
        """
        context = ContextManager(
            thread_id,
            max_tokens=self.model.num_ctx,
            reserve=max(512, self.model.num_ctx // 8),
        )

        if context.needs_compaction():
            logger.info("Compacting context for thread %s", thread_id)
            await context.compact(self.model)

        context.add({"role": "user", "content": user_input})

        tool_schemas = self.tools.schemas()

        for iteration in range(max_iterations):
            messages = self._build_messages(context)

            text_chunks: list[str] = []
            tool_calls: list[dict] = []

            async for chunk in self.model.chat_stream(messages, tools=tool_schemas):
                if chunk.text:
                    text_chunks.append(chunk.text)
                    yield chunk.text
                if chunk.done:
                    tool_calls = chunk.tool_calls

            full_text = "".join(text_chunks)

            if tool_calls:
                # Record assistant message with tool calls
                context.add({
                    "role": "assistant",
                    "content": full_text or "",
                    "tool_calls": [
                        {"function": {"name": tc["name"], "arguments": tc["args"]}}
                        for tc in tool_calls
                    ],
                })

                # Notify CLI / caller of each tool call
                if on_tool_call:
                    for tc in tool_calls:
                        try:
                            await on_tool_call(tc["name"], tc["args"])
                        except Exception:
                            pass

                # Execute tools in parallel
                results = await self.tools.execute_parallel(tool_calls)
                context.extend(results)
                context.save()
                # Loop — let model process the results
                continue

            else:
                # Final answer
                context.add({"role": "assistant", "content": full_text})
                context.save()
                return

        logger.warning(
            "Agent reached max_iterations (%d) for thread %s", max_iterations, thread_id
        )

    async def heartbeat(self, thread_id: str) -> str | None:
        """Run a heartbeat check against HEARTBEAT.md.

        Returns the agent's response if action is needed, or None if all clear.
        HEARTBEAT_OK responses (< 300 chars) are silently suppressed.
        """
        from questchain.config import WORKSPACE_DIR

        heartbeat_path = WORKSPACE_DIR / "workspace" / "HEARTBEAT.md"

        if not heartbeat_path.exists():
            return None

        content = heartbeat_path.read_text(encoding="utf-8").strip()
        # Skip if only headers and blank lines (file is effectively empty)
        meaningful = [
            l for l in content.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        if not meaningful:
            return None

        prompt = (
            f"HEARTBEAT. Check /workspace/HEARTBEAT.md and act on anything that needs "
            f"attention. If nothing needs attention, reply with exactly: {HEARTBEAT_OK}"
        )

        tokens: list[str] = []
        async for chunk in self.run(prompt, thread_id=thread_id, max_iterations=15):
            tokens.append(chunk)

        response = re.sub(
            r"<think>.*?</think>", "", "".join(tokens), flags=re.DOTALL
        ).strip()

        if HEARTBEAT_OK in response and len(response) < 300:
            return None
        return response or None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        parts = [self._base_system_prompt]

        skill_text = self.skills.skill_list_text()
        if skill_text:
            parts.append(skill_text)

        always_text = self.skills.always_active_text()
        if always_text:
            parts.append(always_text)

        parts.append(f"Current date and time: {now}")
        return "\n\n".join(parts)

    def _build_messages(self, context: ContextManager) -> list[dict]:
        return [
            {"role": "system", "content": self._build_system_prompt()},
            *context.messages,
        ]
