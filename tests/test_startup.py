"""Startup regressions; no Ollama server or external services required."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize("system,installer,shell", [("Windows", "install.ps1", "powershell"), ("Linux", "install.sh", "bash")])
def test_update_installer_fallback_uses_existing_master_branch(monkeypatch, system, installer, shell):
    import shutil
    from questchain import __main__ as entry
    from questchain import updater

    commands = []
    monkeypatch.setattr(entry.platform, "system", lambda: system)
    monkeypatch.setattr(shutil, "which", lambda name: f"/resolved/{shell}" if name == shell else None)
    monkeypatch.setattr(updater, "handoff_windows_update", lambda cmd: commands.append(cmd))
    monkeypatch.setattr(entry.subprocess, "run", lambda cmd: commands.append(cmd) or SimpleNamespace(returncode=7))
    with pytest.raises(SystemExit) as result:
        entry.do_update()
    assert result.value.code == (0 if system == "Windows" else 7)
    assert f"QuestChain/master/{installer}" in commands[0][-1]
    assert commands[0][0] == f"/resolved/{shell}"


@pytest.mark.parametrize("returncode", [0, 7])
def test_update_uses_uv_directly_when_available(monkeypatch, returncode):
    import shutil
    from questchain import __main__ as entry

    commands = []
    monkeypatch.setattr(entry.platform, "system", lambda: "Linux")
    monkeypatch.setattr(shutil, "which", lambda name: "/resolved/uv" if name == "uv" else None)
    monkeypatch.setattr(entry.subprocess, "run", lambda cmd: commands.append(cmd) or SimpleNamespace(returncode=returncode))
    with pytest.raises(SystemExit) as result:
        entry.do_update()
    assert result.value.code == returncode
    assert commands == [["/resolved/uv", "tool", "install", "git+https://github.com/RayP11/QuestChain@master", "--reinstall"]]


def test_update_launch_denied_reports_recovery_without_traceback(monkeypatch, capsys):
    import shutil
    from questchain import __main__ as entry
    from questchain import updater

    monkeypatch.setattr(shutil, "which", lambda name: "/resolved/uv" if name == "uv" else None)

    def denied(cmd):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(entry.subprocess, "run", denied)
    monkeypatch.setattr(updater, "handoff_windows_update", denied)
    with pytest.raises(SystemExit) as result:
        entry.do_update()
    assert result.value.code == 1
    error = capsys.readouterr().err
    assert "Access is denied" in error
    assert "uv tool install" in error


def test_update_without_uv_or_shell_reports_recovery(monkeypatch, capsys):
    import shutil
    from questchain import __main__ as entry

    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(entry.subprocess, "run", lambda cmd: pytest.fail("No executable is available"))
    with pytest.raises(SystemExit) as result:
        entry.do_update()
    assert result.value.code == 1
    assert "uv tool install" in capsys.readouterr().err


def test_windows_update_hands_off_to_base_python_before_replacing_tool(monkeypatch):
    import os
    import shutil
    import sys
    from questchain import __main__ as entry, updater

    commands = []
    monkeypatch.setattr(entry.platform, "system", lambda: "Windows")
    monkeypatch.setattr(shutil, "which", lambda name: "/resolved/uv" if name == "uv" else None)
    monkeypatch.setattr(updater.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(entry.subprocess, "run", lambda cmd: pytest.fail("Do not replace the running tool"))
    with pytest.raises(SystemExit) as result:
        entry.do_update()
    assert result.value.code == 0
    assert commands[0][0] == sys._base_executable
    assert commands[0][2:4] == [str(os.getpid()), str(os.getppid())]
    assert commands[0][4] == sys.executable
    assert commands[0][5:] == ["/resolved/uv", "tool", "install", "git+https://github.com/RayP11/QuestChain@master", "--reinstall"]


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
    monkeypatch.setattr(cli, "_maybe_start_telegram", AsyncMock(return_value=(None,) * 3))
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

    monkeypatch.setattr(cli, "_run_with_scheduler", capture)
    await cli.repl("chosen:latest", enable_web=True)
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
