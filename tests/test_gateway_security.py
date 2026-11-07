"""Gateway authentication and browser-origin regressions, without a model."""
import base64

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from questchain.gateway import server


def credentials(password="test-only-secret"):
    return "Basic " + base64.b64encode(("questchain:" + password).encode()).decode()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "_bound_host", "127.0.0.1")
    monkeypatch.setattr(server, "_bound_port", 8765)
    monkeypatch.setattr(server, "_ws_token", "")
    monkeypatch.setattr(server, "_agent_manager", None)
    async def initial(ws):
        await ws.send_json({"type": "ready"})
    monkeypatch.setattr(server, "_push_initial_state", initial)
    with TestClient(server.app, base_url="http://localhost:8765") as instance:
        yield instance


def test_configured_secret_requires_http_auth_and_is_not_disclosed(client, monkeypatch):
    monkeypatch.setattr(server, "_ws_token", "test-only-secret")
    for path in ("/", "/app.js", "/agent-image", "/openapi.json"):
        response = client.get(path)
        assert response.status_code == 401
        assert "test-only-secret" not in response.text
    response = client.get("/", headers={"Authorization": credentials()})
    assert response.status_code == 200
    assert "test-only-secret" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("host", ["localhost:8765", "127.0.0.1:8765", "[::1]:8765"])
def test_loopback_http_hosts_including_ipv6_work(client, host):
    assert client.get("/", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example:8765", "localhost.evil.example:8765", "localhost:8765@evil.example", "[::1", "localhost:invalid"])
def test_invalid_http_host_is_rejected(client, host):
    assert client.get("/", headers={"Host": host}).status_code == 421


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:9000", "https://localhost:8765", "null", "http://localhost:8765/path", "http://user@localhost:8765"])
def test_cross_origin_websocket_is_rejected(client, origin):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://localhost:8765/ws", headers={"Origin": origin}):
            pytest.fail("Untrusted origin accepted")


def test_websocket_validates_host_even_without_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://evil.example:8765/ws"):
            pytest.fail("Untrusted host accepted")


def test_same_origin_and_native_websocket_work(client):
    for headers in ({"Origin": "http://localhost:8765"}, {}):
        with client.websocket_connect("ws://localhost:8765/ws", headers=headers) as ws:
            assert ws.receive_json() == {"type": "ready"}


def test_websocket_requires_configured_secret(client, monkeypatch):
    monkeypatch.setattr(server, "_ws_token", "test-only-secret")
    for headers in ({}, {"Authorization": credentials("wrong")}):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("ws://localhost:8765/ws", headers=headers):
                pytest.fail("Unauthenticated connection accepted")
    with client.websocket_connect("ws://localhost:8765/ws", headers={"Authorization": credentials()}) as ws:
        assert ws.receive_json() == {"type": "ready"}
    # Preserve existing non-browser token clients.
    with client.websocket_connect("ws://localhost:8765/ws?token=test-only-secret") as ws:
        assert ws.receive_json() == {"type": "ready"}


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "example.com"])
async def test_remote_bind_fails_before_starting_server(monkeypatch, host):
    import uvicorn
    monkeypatch.setattr(uvicorn, "Config", lambda *a, **kw: pytest.fail("Unsafe bind reached server startup"))
    with pytest.raises(ValueError, match="loopback"):
        await server.start_gateway_server(host=host)


@pytest.mark.parametrize("authorization", ["", "Bearer test-only-secret", "Basic !!!", "Basic dXNlcg==", credentials("wrong"), "Basic " + base64.b64encode(b"other:test-only-secret").decode()])
def test_bad_http_credentials_fail_closed(client, monkeypatch, authorization):
    monkeypatch.setattr(server, "_ws_token", "test-only-secret")
    assert client.get("/", headers={"Authorization": authorization}).status_code == 401


def test_valid_credentials_do_not_bypass_origin_check(client, monkeypatch):
    monkeypatch.setattr(server, "_ws_token", "test-only-secret")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("ws://localhost:8765/ws?token=test-only-secret",
                                      headers={"Origin": "http://evil.example", "Authorization": credentials()}):
            pytest.fail("Cross-site authenticated connection accepted")


def test_wildcard_configuration_never_trusts_arbitrary_host(client, monkeypatch):
    monkeypatch.setattr(server, "_bound_host", "0.0.0.0")
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 421
