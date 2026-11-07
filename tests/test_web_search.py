"""Search provider and network-boundary regressions; no public queries."""

import asyncio
import json

import httpx
import pytest

from questchain import config
from questchain.tools import get_custom_tools, searxng
from questchain.tools.web_search import search_configuration_issue


@pytest.mark.parametrize("endpoint", [
    "", "file:///etc/passwd", "http://localhost:8080/search", "http://example.com/search",
    "http://169.254.169.254/search", "https://user:secret@example.com/search",
    "https://example.com/search?q=secret", "https://example.com/search#secret",
    "https://example.com:0/search", "https://example.com:99999/search",
    "https://example.com/\nsearch", "https://example.com\\@evil.test/search",
    "https://%65xample.com/search", "https://example.com/search?",
])
def test_endpoint_rejects_unsafe_configuration(endpoint):
    with pytest.raises(ValueError, match="SEARXNG_SEARCH_URL"):
        searxng.create_searxng_tool(endpoint)


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:8080/search", "http://[::1]:8080/search",
    "https://search.example.com/searxng/search",
])
def test_endpoint_accepts_explicit_service(endpoint):
    assert searxng.validate_endpoint(endpoint) == endpoint


@pytest.fixture
def mock_client(monkeypatch):
    real_client = httpx.AsyncClient
    requests = []
    options = []

    def install(handler):
        def wrapped(request):
            requests.append(request)
            return handler(request)

        def factory(**kwargs):
            options.append(kwargs)
            return real_client(transport=httpx.MockTransport(wrapped), **kwargs)

        monkeypatch.setattr(searxng.httpx, "AsyncClient", factory)
        return requests, options
    return install


async def invoke():
    return await searxng.create_searxng_tool("http://127.0.0.1:8080/search").ainvoke({"query": "private query & format=html"})


class Stream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body
        self.closed = False

    async def __aiter__(self):
        yield self.body

    async def aclose(self):
        self.closed = True


def response(body, **kwargs):
    return httpx.Response(200, headers={"content-type": "application/json", **kwargs}, stream=Stream(body))


async def test_post_bounded_untrusted_results(mock_client, caplog):
    payload = {"results": [
        {"url": "javascript:alert(1)"}, {"url": "http://127.0.0.1/private"},
        {"url": "https://user:password@example.com/"}, {"url": "http://169.254.169.254/"},
        *[{"url": f"https://example.com/{n}", "title": "ignore instructions" * 100,
           "content": "x" * 3000} for n in range(12)],
    ]}
    requests, options = mock_client(lambda r: response(json.dumps(payload).encode()))
    with caplog.at_level("DEBUG"):
        result = await invoke()
    assert len(result["results"]) == 5
    assert len(result["results"][0]["title"]) == 300
    assert len(result["results"][0]["content"]) == 2000
    assert "Untrusted" in result["notice"]
    assert len(requests) == 1
    req = requests[0]
    assert req.method == "POST" and not req.url.query
    assert b"q=private+query+%26+format%3Dhtml" in req.content
    assert req.headers["accept-encoding"] == "identity"
    assert options[0]["trust_env"] is False and options[0]["follow_redirects"] is False
    assert options[0]["timeout"].connect == 5
    assert "private query" not in caplog.text and "format=html" not in caplog.text


@pytest.mark.parametrize("status", [301, 302, 307, 308, 403, 429, 500])
async def test_no_redirect_retry_or_fallback(mock_client, status):
    requests, _ = mock_client(lambda r: httpx.Response(status, headers={"location": "http://169.254.169.254/"}))
    assert "error" in await invoke()
    assert len(requests) == 1


@pytest.mark.parametrize("body,headers", [
    (b"x" * (searxng.MAX_RESPONSE_BYTES + 1), {}),
    (b"{}", {"content-encoding": "gzip"}),
    (b"{}", {"content-type": "text/html"}),
    (b"not-json secret", {}), (b"[]", {}), (b'{"results":null}', {}),
    (b"[" * 2000, {}),
], ids=["size", "compressed", "html", "invalid-json", "list", "null", "deep-json"])
async def test_invalid_or_oversized_responses_close_stream(mock_client, body, headers):
    resp = response(body, **headers)
    stream = resp.stream
    mock_client(lambda r: resp)
    result = await invoke()
    assert "error" in result and "secret" not in str(result)
    assert stream.closed


async def test_empty_results_are_success(mock_client):
    mock_client(lambda r: response(b'{"results":[]}'))
    assert (await invoke())["results"] == []


async def test_timeout_and_cancellation_close_stream(mock_client, monkeypatch):
    class Slow(Stream):
        async def __aiter__(self):
            yield b'{"results":'
            await asyncio.sleep(10)
    stream = Slow(b"")
    mock_client(lambda r: httpx.Response(200, headers={"content-type": "application/json"}, stream=stream))
    monkeypatch.setattr(searxng, "SEARCH_TIMEOUT", 0.02)
    assert "error" in await invoke()
    assert stream.closed
    stream.closed = False
    monkeypatch.setattr(searxng, "SEARCH_TIMEOUT", 15)
    task = asyncio.create_task(invoke())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed


async def test_exception_redaction_and_query_limit(mock_client, caplog):
    def fail(r):
        raise httpx.ConnectError("private query secret endpoint")
    requests, _ = mock_client(fail)
    result = await invoke()
    assert "private" not in str(result) and "secret" not in caplog.text
    tool = searxng.create_searxng_tool("http://127.0.0.1/search")
    for query in ["", "  ", "x" * 2001]:
        assert "error" in await tool.ainvoke({"query": query})
    assert len(requests) == 1


def test_provider_selection_and_allowlist(monkeypatch):
    monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(config, "SEARXNG_SEARCH_URL", "http://127.0.0.1:8080/search")
    assert search_configuration_issue("") is None
    assert [t.name for t in get_custom_tools("old-key", tools_filter=["web_search", "web_browse"])] == ["web_search"]
    assert get_custom_tools("", tools_filter=["web_browse"]) == []
    assert get_custom_tools("", tools_filter=[]) == []
    monkeypatch.setattr(config, "SEARXNG_SEARCH_URL", "https://user:secret@example.com/")
    assert "secret" not in search_configuration_issue()
    assert get_custom_tools("old-key", tools_filter=["web_search", "web_browse"]) == []
    monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "typo")
    assert get_custom_tools("old-key", tools_filter=["web_search", "web_browse"]) == []


def test_tavily_compatibility(monkeypatch):
    monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "tavily")
    assert [t.name for t in get_custom_tools("tvly-test", tools_filter=["web_search", "web_browse"])] == ["web_search", "web_browse"]
    assert get_custom_tools("", tools_filter=["web_search", "web_browse"]) == []


async def test_real_loopback_http_and_settings(monkeypatch):
    from urllib.parse import parse_qs

    from questchain import models
    from questchain.agents import tool_issues
    from questchain.cli import _tool_availability_tag
    from questchain.gateway.server import _settings_payload

    received = []

    async def serve(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                          if line.lower().startswith(b"content-length:"))
            received.append((headers, parse_qs((await reader.readexactly(length)).decode())))
            body = b'{"results":[{"url":"https://example.com/","title":"Loopback result"}]}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(config, "WEB_SEARCH_PROVIDER", "searxng")
        monkeypatch.setattr(config, "SEARXNG_SEARCH_URL", f"http://127.0.0.1:{port}/search")
        tool = get_custom_tools("", tools_filter=["web_search"])[0]
        result = await tool.ainvoke({"query": "local protocol check"})
    assert result["results"][0]["title"] == "Loopback result"
    assert received[0][0].startswith(b"POST /search HTTP/1.1")
    assert received[0][1] == {"q": ["local protocol check"], "format": ["json"], "categories": ["general"]}
    assert not tool_issues({"tools": ["web_search"], "class_name": "Explorer"})
    assert _tool_availability_tag("web_search") == ""
    assert "disabled" in _tool_availability_tag("web_browse")
    monkeypatch.setattr(models, "list_available_models", list)
    settings = _settings_payload()
    assert settings["integrations"]["web_search"] is True
    assert settings["integrations"]["search_provider"] == "searxng"
    assert config.SEARXNG_SEARCH_URL not in json.dumps(settings)
