"""Built-in deletion, Keeper defaults, and permission upgrades."""
import json
from pathlib import Path

import pytest

from questchain.agents import AgentManager, CLASS_TOOL_PRESETS, SELECTABLE_TOOLS, tool_access_allowed
from questchain.engine.builtins import filesystem


@pytest.fixture
def workspace(monkeypatch, tmp_path):
    from questchain import config, agent as factory
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "WORKSPACE_DIR", root)
    monkeypatch.setattr(factory, "WORKSPACE_DIR", root)
    monkeypatch.setattr(factory, "ensure_memory_dir", lambda: None)
    monkeypatch.setattr(filesystem, "_ROOT", root)
    return root


def test_delete_removes_only_the_named_file(workspace):
    target = workspace / "obsolete.md"
    other = workspace / "keep.md"
    target.write_text("Temporary test data")
    other.write_text("Keep this file")
    assert filesystem.delete_file("/obsolete.md") == "Deleted file: /obsolete.md"
    assert not target.exists()
    assert other.read_text() == "Keep this file"


@pytest.mark.parametrize("path", ["/", "/notes", "/missing.md", "/../outside.md"])
def test_delete_rejects_directories_missing_files_and_traversal(workspace, path):
    folder = workspace / "notes"
    folder.mkdir()
    note = folder / "keep.md"
    note.write_text("Keep this file")
    outside = workspace.parent / "outside.md"
    outside.write_text("Outside the workspace")
    assert filesystem.delete_file(path).startswith("Error:")
    assert note.exists()
    assert outside.read_text() == "Outside the workspace"


def test_delete_rejects_absolute_paths_outside_workspace(workspace):
    outside = workspace.parent / "outside.md"
    outside.write_text("Outside the workspace")
    assert filesystem.delete_file(str(outside)).startswith("Error:")
    assert outside.exists()


def test_delete_rejects_symlinks_without_touching_the_target(workspace, monkeypatch):
    target = workspace / "notes.md"
    target.write_text("Keep this file")
    monkeypatch.setattr(Path, "is_symlink", lambda self: True)
    assert "symbolic links" in filesystem.delete_file("/notes.md")
    assert target.exists()


def test_athena_has_built_in_delete_by_default_without_workspace_tools(workspace):
    from questchain.agent import create_questchain_agent
    manager = AgentManager()
    manager.seed_preset_agents()
    athena = manager.get_by_class_name("Keeper")
    assert {"read_file", "write_file", "edit_file", "delete_file", "ls", "glob", "grep"} <= set(athena["tools"])
    assert "delete_file" in CLASS_TOOL_PRESETS["Keeper"]
    assert "delete_file" in dict(SELECTABLE_TOOLS)
    assert all("delete_file" not in a["tools"] for a in manager.all_agents() if a["id"] != athena["id"])
    agent = create_questchain_agent(tools_filter=athena["tools"], class_name="Keeper")
    assert agent.tools._tools["delete_file"].fn is filesystem.delete_file
    assert tool_access_allowed(athena, "delete_file")
    assert not (workspace / "workspace/tools").exists()


async def test_default_athena_creates_edits_and_deletes_knowledge_through_shared_runtime(workspace, monkeypatch):
    from questchain import agent as factory, config
    from questchain.engine import context
    from questchain.engine.model import Chunk
    from questchain.runtime import TaskRequest, TaskRuntime
    monkeypatch.setattr(context, "QUESTCHAIN_DATA_DIR", config.QUESTCHAIN_DATA_DIR)
    manager = AgentManager()
    manager.seed_preset_agents()
    athena = manager.get_by_class_name("Keeper")
    path = "/workspace/knowledge/PLAN_sprint.md"
    target = workspace / "workspace/knowledge/PLAN_sprint.md"
    steps = [
        ("write_file", {"path": path, "content": "Status: draft"}),
        ("read_file", {"path": path}),
        ("edit_file", {"path": path, "old_str": "draft", "new_str": "ready"}),
        ("read_file", {"path": path}),
        ("delete_file", {"path": path}),
        ("ls", {"path": "/workspace/knowledge"}),
    ]
    results = []

    class Model:
        num_ctx = 8192

        async def chat_stream(self, messages, tools=None):
            if messages[-1]["role"] == "tool":
                results.append(messages[-1]["content"])
            if steps:
                name, args = steps.pop(0)
                assert name in {t["function"]["name"] for t in tools}
                yield Chunk(done=True, tool_calls=[{"name": name, "args": args}])
            else:
                yield Chunk(text="Created, updated, and deleted the requested test note.", done=True)

    monkeypatch.setattr(factory, "OllamaModel", lambda *args, **kwargs: Model())
    events = []
    runtime = TaskRuntime(manager, default_model="fake", path=workspace / "runs.sqlite3", event_sink=events.append)
    try:
        result = await runtime.wait(runtime.submit(TaskRequest("Create a draft note, update it to ready, then delete it.",
                                                             athena["id"], "telegram-files", "telegram")))
        assert result["status"] == "completed", result["error"]
        assert not target.exists()
        assert "Status: draft" in results
        assert "Status: ready" in results
        assert "Deleted file: " + path in results
        assert results[-1] == "(empty)"
        assert [e["name"] for e in events if e["type"] == "tool_call"] == [
            "write_file", "read_file", "edit_file", "read_file", "delete_file", "ls"]
    finally:
        await runtime.close()


def test_default_upgrade_is_once_and_preserves_custom_permissions(workspace):
    from questchain import config
    old_tools = ["read_file", "write_file", "edit_file", "ls", "glob", "grep"]
    old_prompt = """You are {agent_name}, a knowledge and file management specialist running locally via Ollama.

## Rules
- Read files carefully before modifying; confirm before any destructive changes.
- Organize information clearly using structured files and directories.
- Keep a concise plan for complex multi-step tasks.
- Never hallucinate file contents or paths — verify with tools.
- Be concise, precise, and thorough."""
    default = dict(id="keeper", name="Athena", model=None, class_name="Keeper", tools=old_tools,
                   system_prompt=old_prompt, revision=1, definition_version=2)
    customized = [
        {**default, "id": "edited", "revision": 2},
        {**default, "id": "readonly", "tools": ["read_file"]},
        {**default, "id": "custom-prompt", "system_prompt": "Read only."},
        {**default, "id": "migrated", "migrated_at": "2026-01-01"},
    ]
    path = config.get_agents_path()
    path.write_text(json.dumps([default, *customized]))
    path.with_name("agents_bootstrap_v3").write_text("3")
    manager = AgentManager()
    manager.seed_preset_agents()
    saved = manager.get("keeper")
    assert saved["tools"] == [*old_tools, "delete_file"]
    assert saved["id"] == default["id"] and saved["revision"] == 2
    for original in customized:
        assert manager.get(original["id"]) == original
    manager.update("keeper", tools=old_tools)
    # Users may also create a new Keeper with an explicit selection after upgrading.
    added = manager.add("Read and write", None, None, old_tools, class_name="Keeper")
    reloaded = AgentManager()
    reloaded.seed_preset_agents()
    assert "delete_file" not in reloaded.get("keeper")["tools"]
    assert "delete_file" not in reloaded.get(added["id"])["tools"]
    from questchain.agent import create_questchain_agent
    disabled = reloaded.get("keeper")
    assert not tool_access_allowed(disabled, "delete_file")
    assert "delete_file" not in create_questchain_agent(tools_filter=disabled["tools"], class_name="Keeper").tools.names()


def test_local_delete_workaround_cannot_duplicate_or_override_builtin(workspace):
    from questchain.agents import get_dynamic_selectable_tools
    from questchain.agent import create_questchain_agent
    from questchain.engine.workspace_tools import get_tool_entries, load_workspace_tools
    directory = workspace / "workspace/tools"
    directory.mkdir(parents=True)
    (directory / "delete_file.py").write_text(
        'raise RuntimeError("This obsolete tool must not load")\n'
        'from questchain.engine.tools import tool\n'
        '@tool\ndef delete_file(path: str):\n    """Old deletion tool."""\n    return "old"\n'
    )
    assert not get_tool_entries(workspace)
    assert not load_workspace_tools(workspace, ["delete_file"])
    assert [name for name, _ in get_dynamic_selectable_tools()].count("delete_file") == 1
    agent = create_questchain_agent(tools_filter=CLASS_TOOL_PRESETS["Keeper"], class_name="Keeper")
    assert agent.tools._tools["delete_file"].fn is filesystem.delete_file
