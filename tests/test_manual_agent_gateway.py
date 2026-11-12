"""Manual selection preserves the shared active-agent behavior without routing."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from questchain.agents import AgentManager
from questchain.gateway import server

@pytest.mark.asyncio
async def test_web_selects_specialist_then_submits_directly(monkeypatch, tmp_path):
    from questchain import config
    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path)
    manager = AgentManager()
    specialist = next(a for a in manager.all_agents() if a["kind"] == "specialist")
    requests = []
    runtime = SimpleNamespace(submit=lambda request: requests.append(request) or "run")
    ws = SimpleNamespace(send_json=AsyncMock())
    monkeypatch.setattr(server, "_runtime", runtime)
    monkeypatch.setattr(server, "_agent_manager", manager)
    monkeypatch.setattr(server, "_clients", {})
    monkeypatch.setattr(server, "_agents_payload", lambda: {"agents": manager.all_agents(), "active_id": manager.get_active_id()})
    await server._handle_inbound(ws, {"type": "switch_agent", "agent_id": specialist["id"]})
    assert manager.get_active_id() == specialist["id"]
    assert ws.send_json.call_args.args[0] == {"type": "agent_selected", "agent_id": specialist["id"]}
    await server._handle_inbound(ws, {"type": "chat", "message": "Inspect this file"})
    assert requests[0].agent_id == specialist["id"]
    await server._handle_inbound(ws, {"type": "switch_agent", "agent_id": "missing"})
    assert manager.get_active_id() == specialist["id"]
    assert ws.send_json.call_args.args[0]["type"] == "error"
