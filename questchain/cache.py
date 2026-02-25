"""Response caching utilities for QuestChain.

Two caching layers are provided:

1. **LLM response cache** (``setup_llm_cache``): Uses LangChain's SQLiteCache to
   persist LLM responses keyed by prompt + model.  Identical prompts are served
   from disk instead of re-invoking Ollama.  Enabled by setting
   ``QUESTCHAIN_RESPONSE_CACHE=true`` in your .env file.

2. **Tool result cache** (``tool_cache``): A lightweight in-process TTL decorator
   for wrapping sync or async tool functions.  Cache lives in memory for the
   duration of the process — useful for web search or browse calls where the
   same URL/query may be issued more than once in a session.

Usage example (tool cache)::

    from questchain.cache import tool_cache

    @tool_cache(ttl_seconds=120)
    async def fetch_page(url: str) -> str:
        ...
"""

import asyncio
import functools
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def setup_llm_cache(db_path: Path) -> None:
    """Configure LangChain's global LLM response cache using SQLite.

    Must be called before any LLM is invoked.  Subsequent calls to
    ``setup_llm_cache`` with the same path are safe (no-op).

    Args:
        db_path: Path to the SQLite cache database file.
                 The parent directory is created automatically.
    """
    from langchain_community.cache import SQLiteCache
    from langchain_core.globals import set_llm_cache

    db_path.parent.mkdir(parents=True, exist_ok=True)
    set_llm_cache(SQLiteCache(database_path=str(db_path)))


def tool_cache(ttl_seconds: int = 300) -> Callable:
    """Decorator that caches tool function results in memory with a TTL.

    Works transparently with both sync and async functions.  The cache is
    per-function (not shared) and lives only for the current process.

    Args:
        ttl_seconds: How long to keep cached results.  Default: 300 s (5 min).

    Returns:
        A decorator that wraps the function with TTL caching.

    Example::

        @tool_cache(ttl_seconds=60)
        async def web_search(query: str) -> str:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        # Dict of cache_key -> (result, expiry_monotonic)
        _store: dict[str, tuple[Any, float]] = {}

        def _make_key(*args: Any, **kwargs: Any) -> str:
            payload = json.dumps(
                {"args": args, "kwargs": kwargs},
                sort_keys=True,
                default=str,
            )
            return hashlib.sha256(payload.encode()).hexdigest()

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _make_key(*args, **kwargs)
                now = time.monotonic()
                if key in _store:
                    result, expires_at = _store[key]
                    if now < expires_at:
                        return result
                result = await fn(*args, **kwargs)
                _store[key] = (result, now + ttl_seconds)
                return result
            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _make_key(*args, **kwargs)
                now = time.monotonic()
                if key in _store:
                    result, expires_at = _store[key]
                    if now < expires_at:
                        return result
                result = fn(*args, **kwargs)
                _store[key] = (result, now + ttl_seconds)
                return result
            return sync_wrapper

    return decorator
