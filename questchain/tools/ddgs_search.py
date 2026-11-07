"""Experimental DuckDuckGo search using the pinned DDGS parser, not its transport.

Deliberately bypass DDGS metasearch, fallback, thread pools, and extraction APIs.
Only the fixed DuckDuckGo HTML endpoint can receive a search request.
"""

import asyncio
from importlib.metadata import version
from threading import BoundedSemaphore
from urllib.parse import urlsplit

import httpx
from ddgs.engines.duckduckgo import Duckduckgo
from langchain_core.tools import StructuredTool
from lxml.etree import LxmlError

from questchain.tools.searxng import (
    MAX_RESPONSE_BYTES,
    UNTRUSTED_NOTICE,
    _result_url,
    _text,
)

DDGS_VERSION = "9.16.1"
SEARCH_URL = "https://html.duckduckgo.com/html/"
SEARCH_TIMEOUT = 15.0
# One process-wide admission gate, shared by tools/agents and event loops. No queue.
_SEARCH_SLOTS = BoundedSemaphore(2)
PROVIDER_NOTICE = (
    "Experimental DDGS / DuckDuckGo search (unofficial). Query text and network IP "
    "leave this machine for DuckDuckGo; this is not offline or a local search index."
)


class _Parser(Duckduckgo):
    def __init__(self) -> None:
        # The pinned superclass normally creates a primp HTTP client. We only use
        # its payload builder/parser; all I/O belongs to our cancellable transport.
        pass


def dependency_issue() -> str | None:
    if (version("ddgs") != DDGS_VERSION or Duckduckgo.name != "duckduckgo"
            or Duckduckgo.search_url != SEARCH_URL or Duckduckgo.search_method != "POST"
            or Duckduckgo.disabled):
        return "DDGS dependency does not match the reviewed version/backend; reinstall QuestChain"
    return None


def _failure(code: str, message: str) -> dict:
    return {"source": "ddgs", "provider": "duckduckgo", "status": code,
            "notice": PROVIDER_NOTICE, "error": message, "results": []}


def _parse(body: bytes) -> dict:
    parser = _Parser()
    html = body.decode("utf-8", errors="replace")
    # Inspect challenge forms, not words in legitimate result titles/snippets.
    tree = parser.extract_tree(html)
    for form in tree.xpath("//form"):
        action_path = urlsplit(form.get("action", "")).path
        if form.get("id") == "challenge-form" or action_path == "/anomaly.js":
            return _failure("unavailable", "DuckDuckGo challenged the request. No retry or fallback was attempted.")
    rows = parser.post_extract_results(parser.extract_results(html))
    results = []
    for row in rows:
        if url := _result_url(row.href):
            results.append({"title": _text(row.title, 300), "url": url, "content": _text(row.body, 2000)})
            if len(results) == 5:
                break
    if not results:
        return _failure("inconclusive", "DuckDuckGo returned no usable results. This may mean no matches, "
                        "a block, or changed page markup; it does not establish that no matching pages exist.")
    return {"source": "ddgs", "provider": "duckduckgo", "status": "ok",
            "notice": PROVIDER_NOTICE + " " + UNTRUSTED_NOTICE, "results": results}


def create_ddgs_tool() -> StructuredTool:
    async def search(query: str) -> dict:
        """Search DuckDuckGo; queries leave the machine. Experimental unofficial client."""
        if not query.strip() or len(query) > 2000:
            return _failure("invalid_query", "Search query must contain 1–2000 characters.")
        if dependency_issue():
            return _failure("unavailable", "DDGS dependency mismatch; reinstall QuestChain.")
        if not _SEARCH_SLOTS.acquire(blocking=False):
            return _failure("busy", "Search capacity is busy. No request was sent.")
        try:
            # HTTPX honors operator proxy/CA environment settings, with TLS
            # verification intact. POST avoids query text in request URLs/logs.
            async with (
                asyncio.timeout(SEARCH_TIMEOUT),
                httpx.AsyncClient(timeout=httpx.Timeout(SEARCH_TIMEOUT, connect=5.0),
                                  follow_redirects=False, trust_env=True) as client,
                client.stream(
                    "POST", SEARCH_URL,
                    data=_Parser().build_payload(query, "us-en", "moderate", None, page=1),
                    headers={"Accept": "text/html", "Accept-Encoding": "identity",
                             "User-Agent": "QuestChain/0.1 (experimental DDGS/9.16.1 search)"},
                ) as response,
            ):
                if response.status_code != 200:
                    return _failure("unavailable", "DuckDuckGo refused or failed the request. "
                                    "No retry or fallback was attempted.")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    return _failure("unavailable", "DuckDuckGo returned unsupported compressed data.")
                if response.headers.get("content-type", "").split(";")[0].strip().lower() != "text/html":
                    return _failure("unavailable", "DuckDuckGo did not return an HTML search page.")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        return _failure("unavailable", "DuckDuckGo response exceeded the size limit.")
                    body.extend(chunk)
                if not body:
                    return _failure("inconclusive", "DuckDuckGo returned an empty response; search outcome is unknown.")
                return _parse(bytes(body))
        except (httpx.HTTPError, TimeoutError, ValueError, LxmlError):
            return _failure("unavailable", "DuckDuckGo search failed, timed out, or changed format. "
                            "No retry or fallback was attempted.")
        finally:
            _SEARCH_SLOTS.release()

    return StructuredTool.from_function(
        coroutine=search, name="web_search",
        description=PROVIDER_NOTICE + " " + UNTRUSTED_NOTICE,
    )
