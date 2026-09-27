"""Command flows use the real run store with isolated data and mocked delivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from questchain.agents import AgentManager
from questchain.runtime import TaskRequest, TaskRuntime
from questchain import telegram


@pytest.fixture
async def chat(monkeypatch, tmp_path):
    from questchain import config

    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path)
    monkeypatch.setattr(telegram, "_thread_ids", {})
    monkeypatch.setattr(telegram, "TELEGRAM_OWNER_ID", 42)
    manager = AgentManager()
    manager.seed_preset_agents()
    writer = manager.add("Writer", None, "Write clearly.", [], when_to_call="Draft text.")

    class Runner:
        async def run(self, prompt, thread_id, on_tool_call):
            yield "Saved specialist answer"

    runtime = TaskRuntime(manager, default_model="runtime-model", path=tmp_path / "runs.sqlite3",
                          agent_factory=lambda definition: Runner(), event_sink=lambda event: None)
    context = SimpleNamespace(bot_data={"runtime": runtime, "agent_manager": manager, "model_name": "stale-model"},
                              chat_data={"agent_id": writer["id"]})
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42),
                             effective_chat=SimpleNamespace(id=101, send_action=AsyncMock()),
                             message=SimpleNamespace(text="", reply_text=AsyncMock()))

    async def submit(text="Original request", *, chat_id=101, thread_id=None, source="telegram"):
        thread_id = thread_id or telegram._get_thread_id(chat_id)
        run_id = runtime.submit(TaskRequest(text, writer["id"], f"{source}-{thread_id}", source,
                                           destination=str(chat_id)))
        await runtime.wait(run_id)
        return run_id

    async def command(name, args=""):
        update.message.text = f"/{name} {args}".strip()
        update.message.reply_text.reset_mock()
        await getattr(telegram, "cmd_" + name)(update, context)
        return "\n".join(call.args[0] for call in update.message.reply_text.call_args_list)

    yield SimpleNamespace(manager=manager, writer=writer, runtime=runtime, context=context, update=update,
                          submit=submit, command=command)
    await runtime.close()


async def test_model_follows_live_agent_override_and_runtime_default(chat):
    assert "runtime-model" in await chat.command("model")
    chat.manager.update(chat.writer["id"], model="writer-model")
    assert "writer-model" in await chat.command("model")
    chat.manager.update(chat.writer["id"], model=None)
    assert "runtime-model" in await chat.command("model")


async def test_new_clears_old_run_and_retry_cannot_cross_conversations(chat):
    old = await chat.submit()
    chat.context.chat_data["last_run_id"] = old
    previous_thread = telegram._get_thread_id(101)
    await chat.command("new")
    assert telegram._get_thread_id(101) != previous_thread
    assert "last_run_id" not in chat.context.chat_data
    for command in ("cancel", "retry"):
        assert "No runs in this conversation" in await chat.command(command)
        assert "this conversation" in await chat.command(command, old)
    assert len(chat.runtime.store.runs()) == 1


async def test_runs_show_saved_result_and_retry_works_after_restart(chat):
    run_id = await chat.submit()
    assert not chat.context.chat_data.get("last_run_id")
    listing = await chat.command("runs")
    assert run_id in listing and "completed" in listing and "Writer" in listing
    detail = await chat.command("runs", run_id)
    assert "Original request" in detail and "Saved specialist answer" in detail
    assert "Writer" in detail
    await chat.command("retry", run_id)
    retried = chat.runtime.store.get(chat.context.chat_data["last_run_id"])
    assert retried["id"] != run_id and retried["text"] == "Original request"
    assert retried["conversation_id"] == chat.runtime.store.get(run_id)["conversation_id"]


async def test_history_reopens_saved_conversation_and_persists_selection(chat):
    first = await chat.submit("Earlier request")
    first_thread = telegram._get_thread_id(101)
    await chat.command("new")
    await chat.submit("Later request")
    listing = await chat.command("history")
    assert first_thread in listing and "Earlier request" in listing and "Later request" in listing
    response = await chat.command("history", first_thread)
    assert "Earlier request" in response and "Saved specialist answer" in response
    assert telegram._get_thread_id(101) == first_thread
    assert telegram._load_thread_ids()[101] == first_thread
    assert first in await chat.command("runs")
    await chat.command("retry")
    assert chat.runtime.store.get(chat.context.chat_data["last_run_id"])["conversation_id"] == "telegram-" + first_thread


async def test_history_and_run_commands_do_not_expose_other_chats_or_interfaces(chat):
    other = await chat.submit("OTHER CHAT SECRET", chat_id=202)
    terminal = await chat.submit("TERMINAL SECRET", source="cli")
    # Even a malformed record sharing the conversation ID must not leak.
    mixed = await chat.submit("WRONG DESTINATION SECRET", chat_id=202, thread_id=telegram._get_thread_id(101))
    for command in ("history", "runs"):
        response = await chat.command(command)
        assert "SECRET" not in response
    for run_id in (other, terminal, mixed):
        for command in ("runs", "retry", "cancel"):
            assert "this conversation" in await chat.command(command, run_id)
    before = telegram._get_thread_id(101)
    assert "not found" in (await chat.command("history", telegram._get_thread_id(202))).lower()
    assert telegram._get_thread_id(101) == before


async def test_cancel_queued_run_and_reject_completed_run(chat):
    finished = await chat.submit()
    assert "already finished" in await chat.command("cancel", finished)
    async with chat.runtime.lock:
        pending = chat.runtime.submit(TaskRequest("Queued request", chat.writer["id"],
                    "telegram-" + telegram._get_thread_id(101), "telegram", destination="101"))
        assert "Cancellation requested" in await chat.command("cancel", pending)
    assert (await chat.runtime.wait(pending))["status"] == "cancelled"


async def test_cancel_without_id_cancels_wizard_but_explicit_id_targets_run(chat):
    chat.context.chat_data["building_agent"] = {"step": "name", "data": {}}
    async with chat.runtime.lock:
        pending = chat.runtime.submit(TaskRequest("Queued request", chat.writer["id"],
                    "telegram-" + telegram._get_thread_id(101), "telegram", destination="101"))
        assert "Cancellation requested" in await chat.command("cancel", pending)
        assert "building_agent" in chat.context.chat_data
    assert "Agent creation cancelled" in await chat.command("cancel")
    assert "building_agent" not in chat.context.chat_data


async def test_routed_result_keeps_specialist_author_and_hides_duplicate_child(chat):
    run_id = await chat.submit()
    run = chat.runtime.store.get(run_id)
    run.update(result_agent_name="Researcher", agent_name="Coordinator")
    chat.runtime.store.put(run)
    chat.runtime.store.put({**run, "id": "child-run", "parent_run_id": run_id, "agent_name": "Researcher"})
    listing = await chat.command("runs")
    assert "Researcher" in listing and "child-run" not in listing
    detail = await chat.command("history", telegram._get_thread_id(101))
    assert "Researcher: Saved specialist answer" in detail
    assert detail.count("Saved specialist answer") == 1


async def test_selecting_agent_only_changes_its_chat_and_model_is_live(chat):
    selected = chat.manager.get_active()
    chat.manager.update(selected["id"], model="selected-model")
    query = SimpleNamespace(from_user=SimpleNamespace(id=42), data="agent:pick:" + selected["id"],
                            answer=AsyncMock(), edit_message_text=AsyncMock())
    await telegram.callback_agent(SimpleNamespace(callback_query=query), chat.context)
    assert chat.context.chat_data["agent_id"] == selected["id"]
    assert chat.context.bot_data["model_name"] == "stale-model"
    assert "selected-model" in await chat.command("model")


async def test_history_pages_and_long_results_are_readable(chat):
    for index in range(22):
        await chat.submit(f"Conversation {index:02}", thread_id=f"saved-{index:02}")
    first_page = await chat.command("history")
    assert "Conversation 21" in first_page and "Conversation 00" not in first_page
    second_page = await chat.command("history", "page 2")
    assert "Conversation 00" in second_page
    for args in ("page 0", "page bad", "page 999"):
        assert "page" in (await chat.command("history", args)).lower()
    run_id = await chat.submit()
    run = chat.runtime.store.get(run_id)
    run["result"] = "Long saved answer. " * 1000
    chat.runtime.store.put(run)
    await chat.command("runs", run_id)
    assert len(chat.update.message.reply_text.call_args_list) > 1
    assert all(len(call.args[0]) <= 4096 for call in chat.update.message.reply_text.call_args_list)


@pytest.mark.parametrize("command", ["model", "new", "runs", "history", "retry", "cancel"])
async def test_commands_reject_non_owner(chat, command):
    chat.update.effective_user.id = 999
    assert "private" in await chat.command(command)
    assert not chat.runtime.store.runs()


def test_terminal_new_clears_run_selection_and_help_matches_autocomplete(monkeypatch):
    import io
    from rich.console import Console
    from questchain import cli
    from questchain.gateway import server

    output = io.StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output, width=140))
    monkeypatch.setattr(server, "update_thread_id", lambda thread_id: None)
    state = {"thread_id": "old", "last_run_id": "old-run", "retry_run_id": "old-run"}
    assert cli.handle_command("/new", state)
    assert state["thread_id"] != "old"
    assert "last_run_id" not in state and "retry_run_id" not in state
    assert cli.handle_command("/help", state)
    for command, _ in cli._SLASH_COMMANDS:
        assert command in output.getvalue()
    assert "Ctrl+C or Ctrl+D" in output.getvalue()
