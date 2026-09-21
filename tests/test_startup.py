"""Startup regressions; no Ollama server or external services required."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize("system,installer", [("Windows", "install.ps1"), ("Linux", "install.sh")])
def test_update_uses_existing_master_branch(monkeypatch, system, installer):
    from questchain import __main__ as entry

    commands = []
    monkeypatch.setattr(entry.platform, "system", lambda: system)
    monkeypatch.setattr(entry.subprocess, "run", lambda cmd: commands.append(cmd) or SimpleNamespace(returncode=7))
    with pytest.raises(SystemExit) as result:
        entry.do_update()
    assert result.value.code == 7
    assert f"QuestChain/master/{installer}" in commands[0][-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [None, "agent-override:latest"])
async def test_startup_model_matches_engine_chat_and_settings(monkeypatch, tmp_path, override):
    from questchain import agent, cli, config, models, onboarding, tools
    from questchain.gateway import server

    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(agent, "WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(agent, "OLLAMA_MODEL", "wrong-default:latest")
    monkeypatch.setattr(cli, "check_ollama_connection", lambda: True)
    monkeypatch.setattr(cli, "list_available_models", lambda: ["chosen:latest", "agent-override:latest"])
    monkeypatch.setattr(models, "list_available_models", lambda: ["chosen:latest"])
    monkeypatch.setattr(cli, "PromptSession", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(cli.MetricsManager, "fetch_model_info", lambda self: None)
    monkeypatch.setattr(tools, "get_custom_tools", lambda *args, **kwargs: [])
    monkeypatch.setattr(tools, "is_claude_code_available", lambda: False)
    monkeypatch.setattr(server, "_get_speak_available", lambda: False)
    monkeypatch.setattr(cli, "_maybe_start_telegram", AsyncMock(return_value=(None,) * 4))
    monkeypatch.setattr(server, "start_gateway_server", AsyncMock())
    get_active = cli.AgentManager.get_active
    monkeypatch.setattr(cli.AgentManager, "get_active", lambda self: {**get_active(self), "model": override})
    captured = {}
    saved_settings = []
    monkeypatch.setattr(onboarding, "_save_env_key", lambda key, value: saved_settings.append((key, value)))

    async def capture(session, holder, state, *args, **kwargs):
        captured["engine"] = holder["agent"].model.model_name
        captured["session"] = state["model_name"]
        captured["chat"] = server._stats_payload()["metrics"]["model_name"]
        captured["settings"] = server._settings_payload()["model_name"]
        # Saving a default for the next launch must not mislabel the running model.
        await server._handle_inbound(None, {"type": "set_model", "model": "next-launch:latest", "apply_all": False})
        assert saved_settings == [("OLLAMA_MODEL", "next-launch:latest")]
        assert server._settings_payload()["model_name"] == captured["engine"]

    monkeypatch.setattr(cli, "_run_with_quests", capture)
    await cli.repl("chosen:latest", quest_minutes=None, enable_web=True)
    assert captured == dict.fromkeys(("engine", "session", "chat", "settings"), override or "chosen:latest")


def test_saved_workspace_resolves_memory_under_configured_checkout(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys

    data = tmp_path / "data"
    data.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (data / ".env").write_text(f"QUESTCHAIN_WORKSPACE_DIR='{checkout.as_posix()}'\n")
    env = dict(os.environ, QUESTCHAIN_DATA_DIR=str(data))
    env.pop("QUESTCHAIN_WORKSPACE_DIR", None)
    result = subprocess.run(
        [sys.executable, "-c", "from questchain.config import WORKSPACE_DIR, MEMORY_DIR; print(WORKSPACE_DIR); print(MEMORY_DIR)"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert [Path(line) for line in result.stdout.splitlines()] == [checkout, checkout / "workspace" / "memory"]
