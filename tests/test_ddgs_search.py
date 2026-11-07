"""Test the pinned DDGS parser and bounded transport without querying providers."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from threading import BoundedSemaphore

import httpx
import pytest

from questchain import config
from questchain.tools import ddgs_search as search
from questchain.tools import get_custom_tools
from questchain.tools.web_search import (
    search_configuration_issue,
    search_provider_label,
)

HTML = b'<html><div class="result__body"><h2>Example</h2><a href="https://example.com/">A snippet</a></div></html>'


class Stream(httpx.AsyncByteStream):
    def __init__(self, body=HTML):
        self.body = body
        self.closed = False

    async def __aiter__(self):
        yield self.body

    async def aclose(self):
        self.closed = True


@pytest.fixture
def mock_client(monkeypatch):
    real_client = httpx.AsyncClient
    requests, options = [], []
    monkeypatch.setattr(search, "_SEARCH_SLOTS", BoundedSemaphore(2))

    def install(handler):
        def wrapped(request):
            requests.append(request)
            return handler(request)

        def factory(**kwargs):
            options.append(kwargs)
            return real_client(transport=httpx.MockTransport(wrapped), **kwargs)

        monkeypatch.setattr(search.httpx, "AsyncClient", factory)
        return requests, options
    return install


def response(body=HTML, status=200, **headers):
    return httpx.Response(status, headers={"content-type": "text/html", **headers}, stream=Stream(body))


async def invoke(query="private query & backend=auto"):
    return await search.create_ddgs_tool().ainvoke({"query": query})


async def test_pinned_parser_fixed_provider_and_disclosure(mock_client, monkeypatch, caplog):
    from ddgs.ddgs import DDGS
    from ddgs.http_client import HttpClient

    def forbidden(*args, **kwargs):
        pytest.fail("Must not instantiate DDGS transport or use metasearch/extraction")

    monkeypatch.setattr(HttpClient, "__init__", forbidden)
    monkeypatch.setattr(DDGS, "text", forbidden)
    monkeypatch.setattr(DDGS, "extract", forbidden)
    assert search.dependency_issue() is None
    requests, options = mock_client(lambda r: response())
    with caplog.at_level("DEBUG"):
        result = await invoke()
    assert result["provider"] == "duckduckgo" and result["status"] == "ok"
    assert result["results"][0] == {"title": "Example", "url": "https://example.com/", "content": "A snippet"}
    for disclosure in ["unofficial", "IP", "leave", "Untrusted"]:
        assert disclosure in result["notice"]
    assert "DuckDuckGo" in search.create_ddgs_tool().description
    assert len(requests) == 1 and str(requests[0].url) == search.SEARCH_URL
    assert requests[0].method == "POST" and not requests[0].url.query
    assert b"q=private+query+%26+backend%3Dauto" in requests[0].content
    assert requests[0].headers["accept-encoding"] == "identity"
    assert options[0]["follow_redirects"] is False
    assert options[0]["timeout"].connect == 5.0
    assert options[0]["trust_env"] is True
    assert "private query" not in caplog.text and "backend=auto" not in caplog.text


@pytest.mark.parametrize("status", [202, 301, 302, 307, 308, 403, 429, 500])
async def test_refusal_failure_and_redirect_are_not_empty_success(mock_client, status):
    requests, _ = mock_client(lambda r: response(status=status, location="http://169.254.169.254/"))
    result = await invoke()
    assert result["status"] == "unavailable" and result["error"]
    assert len(requests) == 1


@pytest.mark.parametrize("body,status", [
    (b"", "inconclusive"),
    (b"<html><p>No results found</p></html>", "inconclusive"),
    (b"<html><div class='changed-markup'>Some results</div></html>", "inconclusive"),
    (b"<html><form id='challenge-form'>Solve challenge</form></html>", "unavailable"),
    (b"<html>CAPTCHA</html>", "inconclusive"),
    (b"<html><form action='https://duckduckgo.com/anomaly.js?sv=html'>Challenge</form></html>", "unavailable"),
    (b"<html><form action='//duckduckgo.com/anomaly.js'>Challenge</form></html>", "unavailable"),
])
async def test_empty_200_and_provider_markup_fragility(mock_client, body, status):
    mock_client(lambda r: response(body))
    result = await invoke()
    assert result["status"] == status and "error" in result
    assert result["results"] == []


@pytest.mark.parametrize("body,headers", [
    (b"x" * (search.MAX_RESPONSE_BYTES + 1), {}),
    (HTML, {"content-encoding": "gzip"}),
    (HTML, {"content-type": "application/json"}),
], ids=["size", "compression", "content-type"])
async def test_size_encoding_and_content_type_bounds(mock_client, body, headers):
    resp = response(body, **headers)
    stream = resp.stream
    mock_client(lambda r: resp)
    assert (await invoke())["status"] == "unavailable"
    assert stream.closed


async def test_result_limits_and_unsafe_links(mock_client):
    urls = ["javascript:alert(1)", "http://127.0.0.1/", "http://169.254.169.254/",
            "https://user:secret@example.com/", "http://localhost/", "http://host.internal/"]
    urls += [f"https://example.com/{n}" for n in range(10)]
    body = "<html>" + "".join(f'<div class="body"><h2>{"title" * 200}</h2><a href="{url}">{"snippet" * 500}</a></div>' for url in urls) + "</html>"
    mock_client(lambda r: response(body.encode()))
    result = await invoke()
    assert len(result["results"]) == 5
    assert all(r["url"].startswith("https://example.com/") for r in result["results"])
    assert len(result["results"][0]["title"]) == 300
    assert len(result["results"][0]["content"]) == 2000


async def test_timeout_and_cancellation_release_resources(mock_client, monkeypatch):
    entered = asyncio.Event()

    class Stall(Stream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b""

    streams = []

    def handler(r):
        stream = Stall()
        streams.append(stream)
        return httpx.Response(200, headers={"content-type": "text/html"}, stream=stream)

    requests, _ = mock_client(handler)
    first = asyncio.create_task(invoke())
    await asyncio.wait_for(entered.wait(), 1)
    entered.clear()
    second = asyncio.create_task(invoke())
    await asyncio.wait_for(entered.wait(), 1)
    assert (await invoke())["status"] == "busy"
    assert len(requests) == 2  # Admission is shared by separate tool instances.
    for task in [first, second]:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert all(s.closed for s in streams)
    monkeypatch.setattr(search, "SEARCH_TIMEOUT", 0.02)
    assert (await invoke())["status"] == "unavailable"
    assert streams[-1].closed
    # Both slots really were returned, not merely the caller's await cancelled.
    assert search._SEARCH_SLOTS.acquire(blocking=False)
    assert search._SEARCH_SLOTS.acquire(blocking=False)
    search._SEARCH_SLOTS.release()
    search._SEARCH_SLOTS.release()


async def test_errors_and_bad_inputs_never_leak_or_fallback(mock_client, monkeypatch, caplog):
    def fail(r):
        raise httpx.ConnectError("private query secret upstream details")
    requests, _ = mock_client(fail)
    result = await invoke()
    assert "secret" not in str(result) and "private query" not in caplog.text
    for query in ["", " ", "x" * 2001]:
        assert (await invoke(query))["status"] == "invalid_query"
    monkeypatch.setattr(search, "version", lambda name: "future-version")
    assert (await invoke())["status"] == "unavailable"
    assert len(requests) == 1


def test_provider_selection_disabled_browse_and_disclosure(monkeypatch):
    monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "ddgs")
    monkeypatch.setattr(config, "TAVILY_API_KEY", "old-key")
    assert search_configuration_issue() is None
    assert "DuckDuckGo" in search_provider_label()
    assert "external" in search_provider_label()
    assert [t.name for t in get_custom_tools("old-key", tools_filter=["web_search", "web_browse"])] == ["web_search"]
    assert get_custom_tools("old-key", tools_filter=[]) == []
    monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "none")
    assert get_custom_tools("old-key", tools_filter=["web_search", "web_browse"]) == []
    assert "disabled" in search_configuration_issue()


@pytest.mark.parametrize("provider,key,expected", [
    (None, "", "ddgs"), (None, "old-key", "tavily"),
    ("searxng", "old-key", "searxng"), ("ddgs", "old-key", "ddgs"),
    ("tavily", "", "tavily"), ("none", "old-key", "none"), ("typo", "", "typo"),
])
def test_fresh_and_legacy_configuration_defaults(tmp_path, provider, key, expected):
    env = {**os.environ, "QUESTCHAIN_DATA_DIR": str(tmp_path), "QUESTCHAIN_WORKSPACE_DIR": str(tmp_path),
           "TAVILY_API_KEY": key}
    env.pop("WEB_SEARCH_PROVIDER", None)
    if provider is not None:
        env["WEB_SEARCH_PROVIDER"] = provider
    code = "from questchain.config import WEB_SEARCH_PROVIDER; print(WEB_SEARCH_PROVIDER)"
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == expected


def test_import_and_parser_do_not_open_network_or_start_background_work():
    code = '''
import socket, threading
original_threads = set(threading.enumerate())
def forbidden(*args, **kwargs):
    raise AssertionError("Unexpected network activity")
socket.socket.connect = forbidden
socket.create_connection = forbidden
from questchain.tools.ddgs_search import _parse, dependency_issue
assert dependency_issue() is None
assert _parse(b"<html>Empty</html>")["status"] == "inconclusive"
assert set(threading.enumerate()) == original_threads
'''
    subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)


async def test_real_socket_cancellation_closes_connection(monkeypatch):
    """Exercise actual HTTPX TCP cleanup during a stalled body, not a fake stream."""
    entered, disconnected = asyncio.Event(), asyncio.Event()

    async def serve(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                          if line.lower().startswith(b"content-length:"))
            await reader.readexactly(length)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 9999\r\n\r\n<html>")
            await writer.drain()
            entered.set()
            assert await reader.read() == b""
            disconnected.set()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    real_client = httpx.AsyncClient
    port = server.sockets[0].getsockname()[1]

    async def local_transport_only(request):
        assert str(request.url) == search.SEARCH_URL
        request.url = httpx.URL(f"http://127.0.0.1:{port}/fixture")

    def factory(**kwargs):
        kwargs["trust_env"] = False
        return real_client(event_hooks={"request": [local_transport_only]}, **kwargs)

    monkeypatch.setattr(search.httpx, "AsyncClient", factory)
    monkeypatch.setattr(search, "_SEARCH_SLOTS", BoundedSemaphore(2))
    async with server:
        task = asyncio.create_task(invoke())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(disconnected.wait(), 2)
    assert search._SEARCH_SLOTS.acquire(blocking=False)
    assert search._SEARCH_SLOTS.acquire(blocking=False)
    search._SEARCH_SLOTS.release()
    search._SEARCH_SLOTS.release()


@pytest.mark.parametrize("attribute,value", [
    ("name", "auto"), ("search_url", "https://example.com/"),
    ("search_method", "GET"), ("disabled", True),
])
async def test_backend_contract_fails_closed(mock_client, monkeypatch, attribute, value):
    requests, _ = mock_client(lambda r: response())
    monkeypatch.setattr(search.Duckduckgo, attribute, value)
    assert (await invoke())["status"] == "unavailable"
    assert requests == []


def test_gateway_discloses_provider_without_configuration_values(monkeypatch):
    from questchain import models
    from questchain.gateway.server import _settings_payload

    monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "ddgs")
    monkeypatch.setattr(models, "list_available_models", list)
    integrations = _settings_payload()["integrations"]
    assert integrations["search_provider"] == "ddgs"
    assert integrations["web_search"] is True
    monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "none")
    assert _settings_payload()["integrations"]["web_search"] is False


async def test_legitimate_captcha_results_are_not_challenges(mock_client):
    body = (Path(__file__).parent / "fixtures" / "ddgs-captcha-results.html").read_bytes()
    mock_client(lambda r: response(body))
    result = await invoke("CAPTCHA documentation")
    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    assert "CAPTCHA" in result["results"][0]["title"]
    assert "CAPTCHA" in result["results"][0]["content"]
    assert result["results"][0]["url"] == "https://example.com/captcha"
