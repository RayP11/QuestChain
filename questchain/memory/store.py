"""Conversation history helpers for QuestChain.

Thread history is now stored as JSONL files via the engine's ContextManager.
This module provides a compatibility shim so cli.py can keep calling
get_thread_history() unchanged.
"""

from __future__ import annotations

from questchain.engine.context import ContextManager


def get_thread_history(limit: int = 50) -> list[dict]:
    """Return past conversation threads, newest first.

    Each entry: {thread_id, last_active (datetime|None), first_message (str|None)}
    """
    return ContextManager.list_threads(limit=limit)
