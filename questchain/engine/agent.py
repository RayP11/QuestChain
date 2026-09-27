"""QuestChain engine — async agent loop.

The loop:
  1. Load conversation history from JSONL (ContextManager)
  2. Compact if context is tight
  3. Add user message
  4. Stream model response
  5. If tool calls → execute in order → append results → goto 4
  6. If text → yield tokens to caller → done
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from questchain.engine.context import ContextManager
from questchain.engine.model import OllamaModel
from questchain.engine.tools import ToolRegistry

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 30
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class IterationLimitError(RuntimeError):
    pass


class Agent:
    """Async ReAct agent: model + tools + JSONL context."""

    def __init__(
        self,
        model: OllamaModel,
        tools: ToolRegistry,
        system_prompt: str,
        agent_name: str = "QuestChain",
        injected_files: list[Path] | None = None,
        personality_hint: str = "",
    ):
        self.model = model
        self.tools = tools
        self.agent_name = agent_name
        self._base_system_prompt = system_prompt
        self._injected_files: list[Path] = injected_files or []
        self._personality_hint = personality_hint
        self.last_iterations: int = 0   # tool-loop depth of the most recent turn
        self.last_tool_errors: int = 0  # error count of the most recent turn

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
        self.last_iterations = 0
        self.last_tool_errors = 0

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

                # Validate current permissions immediately before each execution.
                results = []
                for tc in tool_calls:
                    if on_tool_call:
                        await on_tool_call(tc["name"], tc["args"])
                    results.extend(await self.tools.execute_parallel([tc]))
                for r in results:
                    content = r.get("content", "")
                    if isinstance(content, str) and content.startswith("Error"):
                        self.last_tool_errors += 1
                self.last_iterations = iteration + 1
                context.extend(results)
                context.save()
                # Loop — let model process the results
                continue

            else:
                # Final answer
                if not full_text.strip():
                    raise RuntimeError("The model returned an empty response.")
                context.add({"role": "assistant", "content": full_text})
                context.save()
                return

        logger.warning(
            "Agent reached max_iterations (%d) for thread %s", max_iterations, thread_id
        )
        raise IterationLimitError(f"Agent reached its limit of {max_iterations} tool steps.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        parts = []

        if self._personality_hint:
            parts.append(self._personality_hint)

        parts.append(self._base_system_prompt)

        for path in self._injected_files:
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    parts.append(content)
            except FileNotFoundError:
                pass

        parts.append(f"Current date and time: {now}")
        return "\n\n".join(parts)

    def _build_messages(self, context: ContextManager) -> list[dict]:
        return [
            {"role": "system", "content": self._build_system_prompt()},
            *context.messages,
        ]
