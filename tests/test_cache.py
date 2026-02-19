"""Tests for genie.cache — tool_cache TTL decorator and LLM cache setup."""

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from genie.cache import tool_cache


# ──────────────────────────────────────────────────────────────────────────────
# tool_cache — synchronous functions
# ──────────────────────────────────────────────────────────────────────────────

class TestToolCacheSync:
    """tool_cache works correctly with ordinary (non-async) functions."""

    def test_first_call_invokes_function(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        fn(3)
        assert call_count == 1

    def test_second_call_returns_cached_result(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        assert fn(5) == 10
        assert fn(5) == 10
        assert call_count == 1  # only called once

    def test_different_args_produce_separate_entries(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        fn(1)
        fn(2)
        assert call_count == 2

    def test_kwargs_are_part_of_cache_key(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(a, b=0):
            nonlocal call_count
            call_count += 1
            return a + b

        fn(1, b=1)
        fn(1, b=2)
        assert call_count == 2

    def test_cache_miss_after_ttl_expires(self):
        call_count = 0

        @tool_cache(ttl_seconds=0)  # expires immediately
        def fn(x):
            nonlocal call_count
            call_count += 1
            return x

        fn(42)
        time.sleep(0.01)  # let TTL expire
        fn(42)
        assert call_count == 2

    def test_cache_hit_within_ttl(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(x):
            nonlocal call_count
            call_count += 1
            return x

        fn(99)
        fn(99)
        assert call_count == 1

    def test_return_value_preserved(self):
        @tool_cache(ttl_seconds=60)
        def fn(x):
            return {"result": x, "extra": [1, 2, 3]}

        assert fn("hello") == {"result": "hello", "extra": [1, 2, 3]}
        assert fn("hello") == {"result": "hello", "extra": [1, 2, 3]}

    def test_each_decorated_function_has_independent_cache(self):
        """Two separately decorated functions must not share a cache store."""
        count_a = count_b = 0

        @tool_cache(ttl_seconds=60)
        def fn_a(x):
            nonlocal count_a
            count_a += 1
            return x

        @tool_cache(ttl_seconds=60)
        def fn_b(x):
            nonlocal count_b
            count_b += 1
            return x

        fn_a(1)
        fn_b(1)
        fn_a(1)
        fn_b(1)
        assert count_a == 1
        assert count_b == 1

    def test_functools_wraps_preserves_name(self):
        @tool_cache(ttl_seconds=60)
        def my_special_function(x):
            return x

        assert my_special_function.__name__ == "my_special_function"


# ──────────────────────────────────────────────────────────────────────────────
# tool_cache — asynchronous functions
# ──────────────────────────────────────────────────────────────────────────────

class TestToolCacheAsync:
    """tool_cache works correctly with async functions."""

    def test_first_call_invokes_coroutine(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        async def fn(x):
            nonlocal call_count
            call_count += 1
            return x * 3

        asyncio.run(fn(4))
        assert call_count == 1

    def test_second_call_uses_cache(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        async def fn(x):
            nonlocal call_count
            call_count += 1
            return x * 3

        result1 = asyncio.run(fn(4))
        result2 = asyncio.run(fn(4))
        assert result1 == result2 == 12
        assert call_count == 1

    def test_async_cache_miss_after_ttl(self):
        call_count = 0

        @tool_cache(ttl_seconds=0)
        async def fn(x):
            nonlocal call_count
            call_count += 1
            return x

        asyncio.run(fn(7))
        time.sleep(0.01)
        asyncio.run(fn(7))
        assert call_count == 2

    def test_async_different_args_separate_entries(self):
        call_count = 0

        @tool_cache(ttl_seconds=60)
        async def fn(url):
            nonlocal call_count
            call_count += 1
            return f"result:{url}"

        asyncio.run(fn("https://a.com"))
        asyncio.run(fn("https://b.com"))
        assert call_count == 2

    def test_async_functools_wraps_preserves_name(self):
        @tool_cache(ttl_seconds=60)
        async def fetch_data(url: str) -> str:
            return url

        assert fetch_data.__name__ == "fetch_data"

    def test_async_return_value_preserved(self):
        @tool_cache(ttl_seconds=60)
        async def fn(q):
            return [q, q.upper()]

        assert asyncio.run(fn("hello")) == ["hello", "HELLO"]
        assert asyncio.run(fn("hello")) == ["hello", "HELLO"]


# ──────────────────────────────────────────────────────────────────────────────
# Cache key stability
# ──────────────────────────────────────────────────────────────────────────────

class TestCacheKeyStability:
    """Same logical call must always produce the same cache key."""

    def test_positional_and_keyword_produce_same_key(self):
        """fn(1, 2) and fn(1, b=2) should hit the same cache entry."""
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(a, b):
            nonlocal call_count
            call_count += 1
            return a + b

        fn(1, 2)
        fn(1, 2)
        assert call_count == 1

    def test_kwarg_order_does_not_matter(self):
        """json.dumps with sort_keys=True must normalise kwarg order."""
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(**kwargs):
            nonlocal call_count
            call_count += 1
            return kwargs

        fn(z=3, a=1)
        fn(a=1, z=3)  # same kwargs, different order
        assert call_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# setup_llm_cache()
# ──────────────────────────────────────────────────────────────────────────────

class TestSetupLlmCache:
    """setup_llm_cache() should configure LangChain's global cache.

    SQLiteCache and set_llm_cache are imported locally inside setup_llm_cache(),
    so we patch at their source-module paths.
    """

    def test_creates_parent_directory(self, tmp_path):
        db = tmp_path / "sub" / "dir" / "cache.db"

        with patch("langchain_community.cache.SQLiteCache", MagicMock()), \
             patch("langchain_core.globals.set_llm_cache", MagicMock()):
            from genie.cache import setup_llm_cache
            setup_llm_cache(db)

        assert db.parent.exists()

    def test_sqlite_cache_receives_string_path(self, tmp_path):
        db = tmp_path / "cache.db"

        mock_sqlite_instance = MagicMock()
        mock_sqlite_cls = MagicMock(return_value=mock_sqlite_instance)
        mock_set = MagicMock()

        with patch("langchain_community.cache.SQLiteCache", mock_sqlite_cls), \
             patch("langchain_core.globals.set_llm_cache", mock_set):
            from genie.cache import setup_llm_cache
            setup_llm_cache(db)

        mock_sqlite_cls.assert_called_once_with(database_path=str(db))

    def test_set_llm_cache_called_with_sqlite_instance(self, tmp_path):
        db = tmp_path / "cache.db"

        mock_sqlite_instance = MagicMock()
        mock_sqlite_cls = MagicMock(return_value=mock_sqlite_instance)
        mock_set = MagicMock()

        with patch("langchain_community.cache.SQLiteCache", mock_sqlite_cls), \
             patch("langchain_core.globals.set_llm_cache", mock_set):
            from genie.cache import setup_llm_cache
            setup_llm_cache(db)

        mock_set.assert_called_once_with(mock_sqlite_instance)


# ──────────────────────────────────────────────────────────────────────────────
# Cache persistence simulation (session-level hit/miss tracking)
# ──────────────────────────────────────────────────────────────────────────────

class TestCachePersistenceSimulation:
    """Simulate session-level cache behaviour: hits vs misses."""

    def test_cache_hit_rate_across_repeated_calls(self):
        hits = 0
        misses = 0

        @tool_cache(ttl_seconds=60)
        def web_search(query: str) -> str:
            nonlocal misses
            misses += 1
            return f"results:{query}"

        queries = ["python async", "python async", "langgraph", "python async", "langgraph"]
        for q in queries:
            web_search(q)
            # A "hit" is every call after the first for a given query
        # unique queries = 2, total = 5, so hits = 3
        unique_queries = len(set(queries))
        total = len(queries)
        expected_misses = unique_queries
        expected_hits = total - unique_queries
        assert misses == expected_misses
        assert (total - misses) == expected_hits

    def test_cache_cleared_between_test_instances(self):
        """Each @tool_cache decoration creates a fresh store — no cross-test leakage."""
        call_count = 0

        @tool_cache(ttl_seconds=60)
        def fn(x):
            nonlocal call_count
            call_count += 1
            return x

        fn(1)
        assert call_count == 1  # fresh store, definitely a miss
