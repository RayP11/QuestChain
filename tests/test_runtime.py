"""Public execution behavior shared by the UI, terminal, Telegram and cron."""
import asyncio
import json
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from questchain.agents import AgentManager
from questchain.runtime import TaskRequest, TaskRuntime
from questchain.engine.agent import Agent
from questchain.engine.model import Chunk
from questchain.engine.tools import ToolRegistry


@pytest.fixture
def manager(monkeypatch, tmp_path):
    from questchain import config
    from questchain.engine import context
    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(context, "QUESTCHAIN_DATA_DIR", tmp_path / "data")
    result = AgentManager()
    result.seed_preset_agents()
    return result


class Model:
    num_ctx = 32768

    def __init__(self, manager):
        self.manager = manager
        self.calls = []
        self.text = ""
        self.destination = ""
        self.context = ""

    async def chat_stream(self, messages, tools=None):
        self.calls.append(copy.deepcopy(messages))
        if self.text:
            yield Chunk(text=self.text, done=True)
        else:
            destination = self.destination or next(a["id"] for a in self.manager.catalog() if a["name"] == "Quill")
            yield Chunk(done=True, tool_calls=[dict(name="route_to_agent", args=dict(agent_id=destination, context=self.context))])


class Runner:
    def __init__(self, definition, calls):
        self.definition = definition
        self.calls = calls

    async def run(self, prompt, thread_id, on_tool_call, **kwargs):
        self.calls.append((self.definition["id"], prompt, thread_id))
        yield self.definition["name"] + ": "
        yield "original specialist answer"


@pytest.fixture
async def runtime(manager, tmp_path):
    model = Model(manager)
    calls = []
    events = []
    runtime = TaskRuntime(manager, default_model="fake", path=tmp_path / "runs.sqlite3",
                          agent_factory=lambda d: Agent(model, ToolRegistry(), d["system_prompt"], d["name"])
                              if d["class_name"] == "Router" else Runner(d, calls),
                          event_sink=events.append)
    runtime.test_model, runtime.test_calls, runtime.test_events = model, calls, events
    yield runtime
    await runtime.close()


def quill(manager):
    return manager.add("Quill", None, "Revise the supplied prose. Keep {JSON} intact.", [],
                       when_to_call="Draft and revise supplied prose.", routable=True)


async def test_telegram_history_is_ordinary_chat_and_scoped_to_the_conversation(runtime, manager, monkeypatch):
    from questchain import telegram
    monkeypatch.setattr(telegram, "_get_thread_id", lambda chat_id: f"history-{chat_id}")
    context = SimpleNamespace(bot_data={"runtime": runtime, "agent_manager": manager}, chat_data={})
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=101, send_action=AsyncMock()),
                             message=SimpleNamespace(message_id=1, reply_chat_action=AsyncMock(), reply_text=AsyncMock()))
    runtime.test_model.text = "I'm here."
    await telegram._submit_runtime_message(update, context, "Hey you there?")
    first_id = context.chat_data["last_run_id"]
    runtime.test_model.text = "Yes, I can see our interactions in this conversation."
    update.message.message_id = 2
    await telegram._submit_runtime_message(update, context, "Do you have a message history?")
    result = runtime.store.get(context.chat_data["last_run_id"])
    assert result["status"] == "completed"
    assert "Perseus · completed" in update.message.reply_text.call_args.args[0]
    assert [m["content"] for m in runtime.test_model.calls[-1] if m["role"] == "user"] == ["Hey you there?", "Do you have a message history?"]
    assert not runtime.test_calls
    runtime.test_model.text = "I'm here."
    update.effective_chat.id = 202
    await telegram._submit_runtime_message(update, context, "Hello")
    assert [m["content"] for m in runtime.test_model.calls[-1] if m["role"] == "user"] == ["Hello"]


def test_catalog_and_migration_preserve_identity(manager):
    assert {a["name"] for a in manager.all_agents()} == {"Perseus", "Argus", "Athena", "Talos", "Zeus"}
    assert manager.get_active()["name"] == "Perseus"
    agent = quill(manager)
    manager.update(agent["id"], name="Scribe", when_to_call="Write release notes.")
    catalog = manager.catalog()
    assert next(a for a in catalog if a["id"] == agent["id"])["when_to_call"] == "Write release notes."
    assert all("system_prompt" not in a for a in catalog)
    assert all(a["class_name"] != "Router" for a in catalog)
    manager.update(agent["id"], routable=False)
    assert agent["id"] not in {a["id"] for a in manager.catalog()}
    assert manager.get(agent["id"])["name"] == "Scribe"
    manager.remove(agent["id"])
    planner = manager.get_by_class_name("Planner")
    manager.remove(planner["id"])
    reloaded = AgentManager()
    reloaded.seed_preset_agents()
    assert reloaded.get(planner["id"]) is None
    assert reloaded.get_by_class_name("Planner") is None


def test_invalid_definition_does_not_change_saved_agent(manager):
    agent = quill(manager)
    with pytest.raises(ValueError, match="Describe when"):
        manager.update(agent["id"], when_to_call="")
    assert manager.get(agent["id"]) == agent
    with pytest.raises(ValueError, match="Unknown agent fields"):
        manager.update(agent["id"], id="overwritten")
    with pytest.raises(ValueError, match="coordinator"):
        manager.update(manager.get_active_id(), tools=["shell"])


async def test_router_streams_custom_specialist_without_rewriting(runtime, manager):
    custom = quill(manager)
    runtime.test_model.destination = custom["id"]
    run_id = runtime.submit(TaskRequest("Polish these notes", manager.get_active_id(), "web-a", "web"))
    result = await runtime.wait(run_id)
    assert result["status"] == "completed"
    assert result["result"] == "Quill: original specialist answer"
    assert result["result_agent_id"] == custom["id"]
    assert len(runtime.test_model.calls) == 1
    assert runtime.test_calls[0][:2] == (custom["id"], "Polish these notes")
    tokens = [e for e in runtime.test_events if e["type"] == "token"]
    assert all(e["agent_id"] == custom["id"] and e["conversation_id"] == "web-a" for e in tokens)
    assert "".join(e["content"] for e in tokens) == result["result"]
    snapshot = runtime.snapshot("web-a")
    assert len(snapshot["runs"]) == 2
    assert not runtime.events("web-a", snapshot["seq"])
    assert not runtime.snapshot("telegram-other")["runs"]


async def test_direct_chat_bypasses_router_and_agent_selection_is_captured(runtime, manager):
    custom = quill(manager)
    run_id = runtime.submit(TaskRequest("Hello", custom["id"], "cli-a"))
    manager.set_active(manager.get_by_class_name("Builder")["id"])
    manager.update(custom["id"], name="New name")
    result = await runtime.wait(run_id)
    assert result["agent_name"] == "Quill"
    assert result["result"].startswith("Quill:")
    assert not runtime.test_model.calls
    next_id = runtime.submit(TaskRequest("Again", custom["id"], "cli-a"))
    assert (await runtime.wait(next_id))["agent_name"] == "New name"


async def test_invalid_routing_and_clarification_do_not_execute(runtime, manager):
    runtime.test_model.destination = "invented"
    result = await runtime.wait(runtime.submit(TaskRequest("Something", manager.get_active_id(), "web-a")))
    assert result["status"] == "failed"
    assert len(runtime.test_model.calls) == 30  # Normal agent tool loop is bounded.
    assert not runtime.test_calls
    runtime.test_model.text = "Which project?"
    result = await runtime.wait(runtime.submit(TaskRequest("Something", manager.get_active_id(), "web-a")))
    assert result["status"] == "completed"  # Clarifications are ordinary replies.
    assert result["result"] == "Which project?"


async def test_missing_owner_and_failure_never_fall_back(runtime, manager):
    custom = quill(manager)
    run_id = runtime.submit(TaskRequest("Hello", custom["id"], "web-a"))
    manager.remove(custom["id"])
    result = await runtime.wait(run_id)
    assert result["status"] == "failed"
    assert not runtime.test_calls
    with pytest.raises(ValueError, match="no longer exists"):
        runtime.submit(TaskRequest("Hello", custom["id"], "web-a"))


async def test_followup_context_is_scoped_and_model_context_is_per_agent(runtime, manager):
    custom = quill(manager)
    first = await runtime.wait(runtime.submit(TaskRequest("Draft", custom["id"], "web-a")))
    another = manager.get_by_class_name("Keeper")["id"]
    await runtime.wait(runtime.submit(TaskRequest("Summarize", another, "web-a", reply_to_run_id=first["id"])))
    assert "original specialist answer" in runtime.test_calls[-1][1]
    assert runtime.test_calls[0][2] != runtime.test_calls[-1][2]
    assert ":" not in runtime.test_calls[-1][2]
    with pytest.raises(ValueError, match="this conversation"):
        runtime.submit(TaskRequest("Leak", custom["id"], "web-b", reply_to_run_id=first["id"]))


async def test_clarification_handoff_preserves_original_request(runtime, manager):
    custom = quill(manager)
    runtime.test_model.text = "Which language?"
    first = await runtime.wait(runtime.submit(TaskRequest("Write a CSV parser", manager.get_active_id(), "web-a")))
    runtime.test_model.text = "Which delimiter?"
    second = await runtime.wait(runtime.submit(TaskRequest("Python", manager.get_active_id(), "web-a")))
    runtime.test_model.text = ""
    runtime.test_model.destination = custom["id"]
    runtime.test_model.context = "Write a CSV parser. Which language? Python. Which delimiter?"
    result = await runtime.wait(runtime.submit(TaskRequest("Semicolon", manager.get_active_id(), "web-a")))
    assert result["status"] == "completed"
    prompt = runtime.test_calls[0][1]
    assert all(text in prompt for text in ("Write a CSV parser", "Which language?", "Python", "Which delimiter?", "Semicolon"))
    assert prompt.index("Write a CSV parser") < prompt.index("Python") < prompt.index("Semicolon")


async def test_cancel_and_explicit_retry(runtime, manager):
    entered = asyncio.Event()
    class SlowRunner:
        async def run(self, prompt, thread_id, on_tool_call, **kwargs):
            yield "partial response " * 10
            entered.set()
            await asyncio.Event().wait()
    runtime.agent_factory = lambda d: SlowRunner()
    custom = quill(manager)
    run_id = runtime.submit(TaskRequest("Wait", custom["id"], "web-a"))
    await entered.wait()
    runtime.cancel(run_id)
    assert (await runtime.wait(run_id))["status"] == "cancelled"
    await runtime.queue.join()
    assert runtime.store.get(run_id)["result"].startswith("partial response")
    runtime.agent_factory = lambda d: Runner(d, runtime.test_calls)
    retry_id = runtime.retry(run_id)
    retry = await runtime.wait(retry_id)
    assert retry["status"] == "completed"
    assert retry_id != run_id
    assert retry["task_id"] == runtime.store.get(run_id)["task_id"]


async def test_occurrence_dedup_and_delivery_failure_do_not_rerun(runtime, manager):
    custom = quill(manager)
    request = TaskRequest("Do it", custom["id"], "cron-a", "cron", occurrence_key="job:minute")
    first = runtime.submit(request)
    assert runtime.submit(request) == first
    await runtime.wait(first)
    runtime.mark_delivered(first, "network unavailable")
    assert runtime.submit(request) == first
    result = runtime.store.get(first)
    assert result["status"] == "completed" and result["delivery_status"] == "failed"
    assert len(runtime.test_calls) == 1


async def test_routed_cron_occurrences_start_with_fresh_context(runtime, manager):
    quill(manager)
    for occurrence in ("first", "second"):
        result = await runtime.wait(runtime.submit(TaskRequest(
            "Draft today's summary", manager.get_active_id(), "cron-summary", "cron",
            occurrence_key=f"summary:{occurrence}")))
        assert result["status"] == "completed"
    assert len(runtime.test_model.calls) == 2
    assert all(len([m for m in call if m["role"] == "user"]) == 1 for call in runtime.test_model.calls)
    assert [call[1] for call in runtime.test_calls] == ["Draft today's summary"] * 2
    assert runtime.test_calls[0][2] != runtime.test_calls[1][2]


async def test_gateway_creation_validation_and_scoped_chat(runtime, manager, monkeypatch):
    from questchain.gateway import server
    monkeypatch.setattr(server, "_agent_manager", manager)
    monkeypatch.setattr(server, "_runtime", runtime)
    monkeypatch.setattr(server, "_settings_payload", lambda: {})
    ws = SimpleNamespace(send_json=AsyncMock())
    await server._handle_inbound(ws, dict(type="create_agent", name="Quill", tools=[], system_prompt="Write clearly.",
                                         when_to_call="Revise supplied prose.", routable=True))
    agent_id = ws.send_json.call_args.args[0]["agent_id"]
    await server._handle_inbound(ws, dict(type="update_agent", agent_id=agent_id, when_to_call="", routable=True))
    assert ws.send_json.call_args.args[0]["type"] == "agent_error"
    await server._handle_inbound(ws, dict(type="chat", message="Hello", agent_id=agent_id))
    run_id = ws.send_json.call_args.args[0]["run_id"]
    assert (await runtime.wait(run_id))["result"].startswith("Quill:")
    stranger = SimpleNamespace(send_json=AsyncMock())
    await server._handle_inbound(stranger, dict(type="cancel_run", run_id=run_id))
    assert stranger.send_json.call_args.args[0]["type"] == "error"


async def test_telegram_wizard_and_chat_use_custom_agent(runtime, manager, monkeypatch):
    from questchain import telegram
    monkeypatch.setattr(telegram, "_is_owner", lambda uid: uid == 42)
    monkeypatch.setattr(telegram, "is_onboarded", lambda: True)
    monkeypatch.setattr(telegram, "_thread_ids", {})
    reply = AsyncMock()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(id=42, send_action=AsyncMock()),
                             message=SimpleNamespace(text="", message_id=1, reply_chat_action=AsyncMock(), reply_text=reply))
    context = SimpleNamespace(bot_data={"runtime": runtime, "agent_manager": manager},
                              chat_data={"building_agent": {"step": "name", "data": {}}})
    for answer in ["Quill", "-", "-", "none", "Write clear prose.", "Draft prose from supplied notes.", "yes", "Do not browse.", "Polish this note", "yes"]:
        update.message.text = answer
        await telegram._handle_build_agent_wizard(update, context)
    custom = next(a for a in manager.all_agents() if a["name"] == "Quill")
    assert custom["when_to_call"] == "Draft prose from supplied notes."
    assert custom["tools"] == []
    context.chat_data["agent_id"] = custom["id"]
    update.message.text = "Polish this note"
    await telegram.handle_message(update, context)
    assert "Quill · completed" in reply.call_args.args[0]
    assert "original specialist answer" in reply.call_args.args[0]
    assert not runtime.test_model.calls


async def test_cron_waits_for_routed_specialist(runtime, manager, tmp_path):
    from questchain.scheduler import CronScheduler
    custom = quill(manager)
    delivery = AsyncMock()
    scheduler = CronScheduler(None, delivery, jobs_path=tmp_path / "cron.json", agent_manager=manager, runtime=runtime)
    await scheduler.start()
    try:
        job = scheduler.add_job("Writing", "0 9 * * *", "Polish notes", agent_id=manager.get_active_id())
        await scheduler._execute_job(job, "one-occurrence")
        saved = scheduler.get_job(job["id"])
        assert saved["last_status"] == "success"
        assert saved["last_agent_name"] == custom["name"]
        assert saved["last_result"] == "Quill: original specialist answer"
        assert runtime.store.get(saved["last_run_id"])["delivery_status"] == "delivered"
        assert len(runtime.test_calls) == 1
        await scheduler._execute_job(job, "one-occurrence")
        assert len(runtime.test_calls) == 1
        assert delivery.await_count == 1
    finally:
        await scheduler.stop()


async def test_restart_marks_unfinished_runs_interrupted_and_keeps_results(manager, tmp_path):
    from questchain.runtime.store import RunStore
    path = tmp_path / "recovery.sqlite3"
    store = RunStore(path)
    run = dict(id="unfinished", task_id="task", conversation_id="cli-a", parent_run_id=None,
               message_id="message", agent_id="default", agent_name="Original", source="cli",
               status="running", result="Partial saved text", error="")
    store.put(run)
    with pytest.raises(RuntimeError, match="already running"):
        RunStore(path)
    store.close()
    recovered = TaskRuntime(manager, default_model="fake", path=path)
    try:
        saved = recovered.store.get("unfinished")
        assert saved["status"] == "interrupted"
        assert saved["result"] == "Partial saved text"
        assert recovered.queue.empty()
    finally:
        await recovered.close()


async def test_explicit_reply_to_specialist_bypasses_router(runtime, manager):
    custom = quill(manager)
    first = runtime.submit(TaskRequest("Draft", custom["id"], "web-a", "web"))
    await runtime.wait(first)
    reply = runtime.submit(TaskRequest("Shorter", manager.get_active_id(), "web-a", "web", reply_to_run_id=first))
    result = await runtime.wait(reply)
    assert result["agent_id"] == custom["id"]
    assert not runtime.test_model.calls
    assert "original specialist answer" in runtime.test_calls[-1][1]


async def test_terminal_renderer_and_retry_commands(runtime, manager, monkeypatch):
    import io
    from rich.console import Console
    from questchain import cli
    from questchain.runtime.terminal import run_terminal_task
    from questchain.gateway.events import get_bus
    runtime.event_sink = get_bus().publish_nowait
    output = io.StringIO()
    terminal = Console(file=output, force_terminal=False)
    monkeypatch.setattr(cli, "console", terminal)
    custom = quill(manager)
    result = await run_terminal_task(runtime, TaskRequest("Draft", manager.get_active_id(), "cli-test"), terminal)
    assert "Perseus → Quill" in output.getvalue()
    assert "original specialist answer" in output.getvalue()
    state = dict(runtime=runtime, agent_manager=manager, thread_id="test", last_run_id=result["id"])
    assert cli.handle_command("/retry", state)
    assert state["retry_run_id"] == result["id"]
    assert cli.handle_command("/runs", state)
    assert result["id"] in output.getvalue()


async def test_cron_history_is_explicitly_subscribed(runtime, manager, monkeypatch):
    from questchain.gateway import server
    monkeypatch.setattr(server, "_runtime", runtime)
    monkeypatch.setattr(server, "_list_cron_jobs", lambda: [{"id": "job"}])
    ws = SimpleNamespace(send_json=AsyncMock())
    monkeypatch.setattr(server, "_clients", {id(ws): {"conversation_id": "web-test", "agent_id": "default"}})
    custom = quill(manager)
    run = runtime.submit(TaskRequest("Draft", custom["id"], "cron-job", "cron"))
    await runtime.wait(run)
    await server._send_cron_history(ws)
    ws.send_json.assert_not_called()
    await server._handle_inbound(ws, {"type": "get_cron_history", "cron_id": "job"})
    payload = ws.send_json.call_args.args[0]
    assert payload["type"] == "cron_history"
    assert payload["runs"][0]["result"].startswith("Quill:")
    assert "definition" not in payload["runs"][0]
    with pytest.raises(ValueError, match="not found"):
        await server._handle_inbound(ws, {"type": "get_cron_history", "cron_id": "other"})


async def test_shell_cancellation_stops_owned_process(monkeypatch):
    from questchain.engine.builtins import shell
    started = asyncio.Event()
    async def communicate():
        started.set()
        await asyncio.Event().wait()
    proc = SimpleNamespace(communicate=communicate, returncode=None)
    monkeypatch.setattr(shell.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    cleanup = AsyncMock()
    monkeypatch.setattr(shell, "_stop_process_tree", cleanup)
    task = asyncio.create_task(shell.execute("test-command"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cleanup.assert_awaited_once_with(proc)


def test_legacy_agents_are_archived_until_explicit_migration(monkeypatch, tmp_path):
    from questchain import config
    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path)
    legacy = [dict(id="custom-id", name="My researcher", model="local", class_name="Explorer",
                   tools=["read_file"], system_prompt="Keep my prompt.")]
    path = config.get_agents_path()
    path.write_text(json.dumps(legacy))
    manager = AgentManager()
    manager.seed_preset_agents()
    assert manager.get("custom-id") is None
    assert manager.get_active()["name"] == "Perseus"
    assert {a["id"] for a in manager.legacy_agents()} == {"custom-id", "default"}
    archive = json.loads((tmp_path / "legacy" / "agents.json").read_text())
    assert archive[0] == legacy[0]
    migrated = manager.migrate_legacy("custom-id")
    assert migrated["name"] == "My researcher"
    assert migrated["tools"] == ["read_file"]
    assert migrated["system_prompt"] == "Keep my prompt."
    assert migrated["when_to_call"] and not migrated["routable"]
    assert manager.get_active()["name"] == "Perseus"
    assert AgentManager().get("custom-id")["id"] == "custom-id"
    assert json.loads(path.with_suffix(".v1.bak").read_text()) == legacy


@pytest.mark.parametrize("saved_definitions", [False, True])
def test_implicit_default_is_archived_for_empty_legacy_install(monkeypatch, tmp_path, saved_definitions):
    from questchain import config
    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path)
    config.get_active_agent_path().write_text("default")
    if saved_definitions:
        config.get_agents_path().write_text("[]")
    manager = AgentManager()
    manager.seed_preset_agents()
    assert manager.get("default") is None
    assert [a["id"] for a in manager.legacy_agents()] == ["default"]
    assert manager.migrate_legacy("default")["id"] == "default"
    assert AgentManager().get("default") is not None


async def test_terminal_agent_creation_and_edit_roundtrip(manager, monkeypatch):
    import io
    from rich.console import Console
    from questchain import cli
    answers = iter(["Quill", "1", "none", "Write clear prose.", "Polish provided drafts.", "yes", "Do not browse.", "Polish this note"])
    async def answer(*args):
        return next(answers)
    monkeypatch.setattr(cli, "_prompt_line", answer)
    monkeypatch.setattr(cli, "_prompt_model_line", AsyncMock(return_value=""))
    console = Console(file=io.StringIO())
    created = await cli._run_create_wizard(console, None, manager)
    assert created["name"] == "Quill" and created["tools"] == []
    answers = iter(["Scribe", "", "", "", "", "no", "", ""])
    await cli._run_edit_wizard(console, None, manager, created)
    saved = manager.get(created["id"])
    assert saved["name"] == "Scribe" and not saved["routable"]
    assert saved["system_prompt"] == "Write clear prose."
    assert saved["when_not_to_call"] == "Do not browse."


async def test_model_timeout_surfaces_failure_with_partial_output(runtime, manager):
    class TimeoutRunner:
        async def run(self, *args, **kwargs):
            yield "Saved partial answer"
            raise TimeoutError("Model timed out")
    runtime.agent_factory = lambda d: TimeoutRunner()
    result = await runtime.wait(runtime.submit(TaskRequest("Draft", quill(manager)["id"], "web-a")))
    assert result["status"] == "failed"
    assert result["result"] == "Saved partial answer"
    assert "timed out" in result["error"]


async def test_engine_rechecks_permissions_between_tool_calls(runtime, manager, monkeypatch, tmp_path):
    from questchain.engine.agent import Agent
    from questchain.engine.model import Chunk
    from questchain.engine.tools import make_registry, tool
    from questchain.engine import context
    monkeypatch.setattr(context, "QUESTCHAIN_DATA_DIR", tmp_path)
    custom = manager.add("Writer", None, "Write.", ["write_file"], when_to_call="Write files.")
    mutations = []
    @tool
    async def write_file(path: str):
        """Write a test marker."""
        mutations.append(path)
        manager.update(custom["id"], tools=[])
        return "Written"
    class ToolModel:
        num_ctx = 8192
        async def chat_stream(self, *args, **kwargs):
            yield Chunk(done=True, tool_calls=[{"name":"write_file","args":{"path":"one"}},
                                              {"name":"write_file","args":{"path":"two"}}])
    runtime.agent_factory = lambda d: Agent(ToolModel(), make_registry(write_file), "Write.")
    result = await runtime.wait(runtime.submit(TaskRequest("Write twice", custom["id"], "web-a")))
    assert result["status"] == "failed"
    assert mutations == ["one"]
    assert "no longer enabled" in result["error"]


async def test_legacy_migration_through_web_terminal_and_telegram(manager, runtime, monkeypatch):
    from questchain import config, cli, telegram
    from questchain.gateway import server
    folder = config.get_agents_path().parent / "legacy"
    folder.mkdir(exist_ok=True)
    archived = [dict(id=key, name=key, class_name="Hermes", model=None, tools=[], system_prompt="Research.")
                for key in ("web-old", "cli-old", "tg-old")]
    (folder / "agents.json").write_text(json.dumps(archived))
    assert not any(a["id"].endswith("-old") for a in manager.catalog())
    with pytest.raises(ValueError, match="no longer exists"):
        runtime.submit(TaskRequest("Research", "web-old", "cron-test", "cron"))
    monkeypatch.setattr(server, "_agent_manager", manager)
    monkeypatch.setattr(server, "_settings_payload", lambda: {})
    ws = SimpleNamespace(send_json=AsyncMock())
    await server._handle_inbound(ws, dict(type="migrate_legacy_agent", agent_id="web-old"))
    assert ws.send_json.call_args.args[0]["type"] == "legacy_migrated"
    assert cli.handle_command("/legacy migrate cli-old", {"agent_manager": manager})
    monkeypatch.setattr(telegram, "_is_owner", lambda uid: uid == 42)
    query = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock(),
                            data="agent:migrate:tg-old", edit_message_text=AsyncMock())
    await telegram.callback_agent(SimpleNamespace(callback_query=query),
                                  SimpleNamespace(bot_data={"agent_manager":manager}, chat_data={}))
    assert manager.legacy_agents() == []
    for old in archived:
        restored = manager.get(old["id"])
        assert restored["name"] == old["name"]
        assert restored["tools"] == old["tools"]
        assert restored["class_name"] == "Explorer"
        assert not restored["routable"]
    assert json.loads((folder / "agents.json").read_text()) == archived


def test_windows_disconnect_does_not_hide_other_loop_errors():
    from questchain.gateway.server import _handle_loop_error
    from unittest.mock import Mock
    loop = SimpleNamespace(default_exception_handler=Mock())
    _handle_loop_error(loop, {"exception": ConnectionResetError(),
                             "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)"})
    loop.default_exception_handler.assert_not_called()
    other = {"exception": RuntimeError("task failed"), "message": "Task exception"}
    _handle_loop_error(loop, other)
    loop.default_exception_handler.assert_called_once_with(other)


async def test_delete_archived_agents_persists_and_refreshes_settings(manager, monkeypatch):
    from questchain import config
    from questchain.gateway import server
    from questchain.gateway.events import get_bus
    folder = config.get_agents_path().parent / "legacy"
    folder.mkdir()
    archive = folder / "agents.json"
    definitions = [dict(id=key, name=key, class_name="Custom", model=None, tools=[], system_prompt="Write.")
                   for key in ("remove-me", "keep-me", "migrated")]
    archive.write_text(json.dumps(definitions))
    manager.migrate_legacy("migrated")
    active_before = manager.all_agents()
    history = folder.parent / "sessions" / "old.jsonl"
    history.parent.mkdir()
    history.write_text('original history')
    monkeypatch.setattr(server, "_agent_manager", manager)
    monkeypatch.setattr(server, "_settings_payload", lambda: {"legacy_agents": manager.legacy_agents()})
    ws = SimpleNamespace(send_json=AsyncMock())
    queue = get_bus().subscribe()
    try:
        await server._handle_inbound(ws, {"type": "delete_legacy_agent", "agent_id": "remove-me"})
        assert ws.send_json.call_args.args[0]["type"] == "legacy_deleted"
        settings = queue.get_nowait()
        assert settings["type"] == "settings"
        assert [a["id"] for a in settings["legacy_agents"]] == ["keep-me"]
        assert [a["id"] for a in AgentManager().legacy_agents()] == ["keep-me"]
        with pytest.raises(ValueError, match="not found"):
            manager.migrate_legacy("remove-me")
        await server._handle_inbound(ws, {"type": "delete_legacy_agent", "agent_id": "keep-me"})
        assert queue.get_nowait()["legacy_agents"] == []
        assert AgentManager().legacy_agents() == []
        assert json.loads(archive.read_text()) == [definitions[2]]
        assert manager.all_agents() == active_before
        assert history.read_text() == 'original history'
    finally:
        get_bus().unsubscribe(queue)


async def test_archived_delete_rejects_active_or_missing_agents(manager, monkeypatch):
    from questchain import config
    from questchain.gateway import server
    folder = config.get_agents_path().parent / "legacy"
    folder.mkdir()
    active = manager.get_active()
    archive = folder / "agents.json"
    archive.write_text(json.dumps([active]))
    before = archive.read_bytes()
    monkeypatch.setattr(server, "_agent_manager", manager)
    ws = SimpleNamespace(send_json=AsyncMock())
    for agent_id in (active["id"], "missing"):
        await server._handle_inbound(ws, {"type": "delete_legacy_agent", "agent_id": agent_id})
        assert ws.send_json.call_args.args[0]["type"] == "legacy_error"
        assert archive.read_bytes() == before
    assert manager.get(active["id"]) == active
