"""Conversation history manager.

Stores history as JSONL per thread (human-readable, debuggable).
Tracks token budget and compacts old turns when approaching the context limit.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from questchain.config import QUESTCHAIN_DATA_DIR

logger = logging.getLogger(__name__)

_INTERNAL_PREFIXES = ("busy_work", "heartbeat", "onboarding", "cron:")
_COMPACT_KEEP_RECENT = 6       # messages preserved verbatim during compaction
_COMPACT_CONTENT_LIMIT = 800   # chars per message fed to the summarizer
_THREAD_FIRST_MSG_LIMIT = 80   # chars kept for the first-message preview
_THREAD_LIST_DEFAULT_LIMIT = 50


def _sessions_dir() -> Path:
    d = QUESTCHAIN_DATA_DIR / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ContextManager:
    """Per-thread conversation history backed by a JSONL file.

    Token budget is approximated as total chars / 4. When the budget is tight,
    call compact() to summarise old turns and reclaim space.
    """

    def __init__(
        self,
        thread_id: str,
        max_tokens: int = 8192,
        reserve: int = 1024,
    ):
        self.thread_id = thread_id
        self.max_tokens = max_tokens
        self.reserve = reserve
        self._messages: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Message access
    # ------------------------------------------------------------------

    @property
    def messages(self) -> list[dict]:
        return list(self._messages)

    def add(self, message: dict) -> None:
        self._messages.append(message)

    def extend(self, messages: list[dict]) -> None:
        self._messages.extend(messages)

    # ------------------------------------------------------------------
    # Token budget
    # ------------------------------------------------------------------

    def tokens_used(self) -> int:
        return self._approx_tokens(self._messages)

    def token_budget(self) -> int:
        return max(0, self.max_tokens - self.reserve - self.tokens_used())

    def needs_compaction(self) -> bool:
        """True when less than reserve tokens remain."""
        return self.token_budget() < self.reserve

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    async def compact(self, model) -> None:
        """Summarise old turns to free context space.

        Keeps the most recent 6 messages intact; summarises everything before.
        """
        if len(self._messages) <= _COMPACT_KEEP_RECENT:
            return

        old = self._messages[:-_COMPACT_KEEP_RECENT]
        recent = self._messages[-_COMPACT_KEEP_RECENT:]

        text = "\n\n".join(
            f"{m['role'].upper()}: {str(m.get('content', ''))[:_COMPACT_CONTENT_LIMIT]}"
            for m in old
        )

        logger.info("Compacting %d old messages for thread %s", len(old), self.thread_id)
        summary = await model.summarize(text)

        self._messages = [
            {
                "role": "system",
                "content": f"[Earlier conversation — summarised]\n{summary}",
                "compacted_at": datetime.now(timezone.utc).isoformat(),
            },
            *recent,
        ]
        self.save()
        logger.info("Compaction done — %d messages remain", len(self._messages))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        path = _sessions_dir() / f"{self.thread_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for msg in self._messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def _load(self) -> None:
        path = _sessions_dir() / f"{self.thread_id}.jsonl"
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as f:
                self._messages = [
                    json.loads(line) for line in f if line.strip()
                ]
        except Exception as e:
            logger.warning("Failed to load context for %s: %s", self.thread_id, e)
            self._messages = []

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def list_threads(limit: int = _THREAD_LIST_DEFAULT_LIMIT) -> list[dict]:
        """Return metadata for saved threads, newest first.

        Each entry: {thread_id, last_active (datetime|None), first_message (str|None)}
        Internal threads (heartbeat, onboarding, cron) are excluded.
        """
        sessions = _sessions_dir()
        threads = []

        paths = sorted(
            sessions.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for path in paths:
            tid = path.stem
            if any(tid.startswith(p) for p in _INTERNAL_PREFIXES):
                continue

            first_msg = ""
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        data = json.loads(line)
                        if data.get("role") == "user" and data.get("content"):
                            first_msg = str(data["content"])[:_THREAD_FIRST_MSG_LIMIT]
                            break
            except Exception as e:
                logger.warning("Could not read thread preview for %s: %s", path.stem, e)

            threads.append({
                "thread_id": tid,
                "last_active": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ),
                "first_message": first_msg,
            })

            if len(threads) >= limit:
                break

        return threads

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _approx_tokens(messages: list[dict]) -> int:
        return sum(len(str(m.get("content", ""))) for m in messages) // 4
