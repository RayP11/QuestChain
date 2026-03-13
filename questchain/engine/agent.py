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

                # Notify CLI / caller of each tool call
                if on_tool_call:
                    for tc in tool_calls:
                        try:
                            await on_tool_call(tc["name"], tc["args"])
                        except Exception as e:
                            logger.debug("on_tool_call callback raised: %s", e)

                # Execute tools in parallel
                results = await self.tools.execute_parallel(tool_calls)
                for r in results:
                    content = r.get("content", "")
                    if isinstance(content, str) and content.startswith("Error running"):
                        self.last_tool_errors += 1
                self.last_iterations = iteration + 1
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

    async def run_quest(self, thread_id: str, quest_path: "Path | None" = None) -> str | None:
        """Pick and complete a quest from workspace/quests/.

        Args:
            thread_id: Conversation thread identifier.
            quest_path: Specific quest file to run. If None, picks the
                        alphabetically-first quest in workspace/quests/.

        Returns the agent's summary response, or None if there are no quests.
        Deletes the quest file on completion.
        """
        from questchain.config import WORKSPACE_DIR
        from questchain.quest_meta import parse_quest

        if quest_path is None:
            quests_dir = WORKSPACE_DIR / "workspace" / "quests"
            if not quests_dir.exists():
                return None
            quest_files = sorted(quests_dir.glob("*.md"))
            if not quest_files:
                return None
            quest_path = quest_files[0]

        if not quest_path.exists():
            return None

        quest_name = quest_path.name
        _, body = parse_quest(quest_path)

        prompt = (
            f"QUEST: Complete the following task (from {quest_name}).\n\n"
            f"{body}\n\n"
            f"When finished, present your actual findings, results, or produced content directly "
            f"in your response — not a description of steps taken."
        )

        tokens: list[str] = []
        async for chunk in self.run(prompt, thread_id=thread_id, max_iterations=15):
            tokens.append(chunk)

        response = _THINK_RE.sub("", "".join(tokens)).strip()

        await asyncio.to_thread(quest_path.unlink, True)

        return response or None

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
