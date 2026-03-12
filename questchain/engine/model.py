"""Thin async wrapper around the ollama Python client."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import ollama

from questchain.config import MODEL_PRESETS, OLLAMA_BASE_URL, OLLAMA_NUM_GPU, OLLAMA_NUM_THREAD

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class Chunk:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    done: bool = False


@dataclass
class Response:
    text: str
    tool_calls: list[dict]


class OllamaModel:
    """Async wrapper around the ollama Python client.

    Handles streaming, tool schema passing, and approximate token counting.
    """

    def __init__(self, model_name: str, base_url: str | None = None):
        self.model_name = model_name
        preset = MODEL_PRESETS.get(model_name, {})
        self.num_ctx = preset.get("num_ctx", 32768)
        self.num_predict = preset.get("num_predict", 4096)
        self.temperature = preset.get("temperature", 0.7)

        self._client = ollama.AsyncClient(host=base_url or OLLAMA_BASE_URL)
        self._options = {
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "temperature": self.temperature,
        }
        if OLLAMA_NUM_GPU is not None:
            self._options["num_gpu"] = OLLAMA_NUM_GPU
        if OLLAMA_NUM_THREAD is not None:
            self._options["num_thread"] = OLLAMA_NUM_THREAD

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[Chunk]:
        """Stream a chat completion, yielding Chunk objects.

        Text tokens are yielded as they arrive. Tool calls appear in the final
        done=True chunk. Thinking blocks (<think>…</think>) are filtered out.
        """
        kwargs: dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "options": self._options,
        }
        if tools:
            kwargs["tools"] = tools

        tool_calls: list[dict] = []
        think_buf = ""
        in_think = False

        stream = await self._client.chat(**kwargs)
        try:
            async with asyncio.timeout(300):
                async for part in stream:
                    msg = part.message

                    # --- Text chunk ---
                    raw = msg.content or ""
                    if raw:
                        # Filter <think>…</think> blocks on the fly
                        raw, in_think, think_buf = _filter_think(raw, in_think, think_buf)
                        if raw:
                            yield Chunk(text=raw)

                    # --- Tool calls (typically in the final message) ---
                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            tool_calls.append({
                                "name": tc.function.name,
                                "args": dict(tc.function.arguments) if tc.function.arguments else {},
                            })

                    if part.done:
                        yield Chunk(tool_calls=tool_calls, done=True)
        except asyncio.TimeoutError:
            logger.warning("Ollama stream timed out after 300s")
            yield Chunk(text="\n[Response timed out]", done=False)
            yield Chunk(tool_calls=[], done=True)

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> Response:
        """Non-streaming chat. Returns complete Response."""
        kwargs: dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": self._options,
        }
        if tools:
            kwargs["tools"] = tools

        result = await self._client.chat(**kwargs)
        msg = result.message

        tool_calls: list[dict] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append({
                    "name": tc.function.name,
                    "args": dict(tc.function.arguments) if tc.function.arguments else {},
                })

        text = _THINK_RE.sub("", msg.content or "").strip()
        return Response(text=text, tool_calls=tool_calls)

    async def summarize(self, text: str) -> str:
        """Summarize old conversation turns for context compaction."""
        result = await self.chat([
            {
                "role": "system",
                "content": "You are a concise summarizer. Preserve key facts, decisions, file paths, and tool outcomes. Be brief.",
            },
            {
                "role": "user",
                "content": f"Summarize this conversation history:\n\n{text}",
            },
        ])
        return result.text

    def count_tokens_approx(self, messages: list[dict]) -> int:
        """Approximate token count (chars / 4). Fast, no API call needed."""
        total = sum(len(str(m.get("content", ""))) for m in messages)
        return total // 4


def _filter_think(raw: str, in_think: bool, buf: str) -> tuple[str, bool, str]:
    """Strip <think>…</think> blocks from a streaming text chunk.

    Returns (filtered_text, in_think, leftover_buf).
    """
    buf += raw
    out = []

    while buf:
        if in_think:
            end = buf.find("</think>")
            if end != -1:
                buf = buf[end + 8:]
                in_think = False
            else:
                buf = ""
                break
        else:
            start = buf.find("<think>")
            if start != -1:
                out.append(buf[:start])
                buf = buf[start + 7:]
                in_think = True
            else:
                out.append(buf)
                buf = ""
                break

    return "".join(out), in_think, buf
