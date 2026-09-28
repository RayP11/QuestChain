"""Exercise real agent history and handoffs without network calls."""
import asyncio
import copy

import pytest

from questchain.agents import AgentManager
from questchain.engine.agent import Agent
from questchain.engine.context import ContextManager
from questchain.engine.model import Chunk
from questchain.engine.tools import ToolRegistry, make_registry, tool
from questchain.runtime import TaskRequest, TaskRuntime


class ChatModel:
    num_ctx = 32768

    def __init__(self):
        self.calls = []
        self.tool_calls = []
        self.text = "Ready when you are."
        self.tools = []

    async def chat_stream(self, messages, tools=None):
        self.calls.append(copy.deepcopy(messages))
        self.tools = tools
        if self.tool_calls:
            yield Chunk(done=True, tool_calls=self.tool_calls)
        else:
            yield Chunk(text=self.text)
            yield Chunk(done=True)


@pytest.fixture
def setup(monkeypatch, tmp_path):
    from questchain import config
    from questchain.engine import context
    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path)
    monkeypatch.setattr(context, "QUESTCHAIN_DATA_DIR", tmp_path)
    manager = AgentManager()
    manager.seed_preset_agents()
    for definition in manager.all_agents():
        manager.update(definition["id"], tools=[])
    models = {d["id"]: ChatModel() for d in manager.all_agents()}
    events = []

    def runtime():
        return TaskRuntime(manager, default_model="fake", path=tmp_path / "runs.sqlite3",
            agent_factory=lambda d: Agent(models[d["id"]], ToolRegistry(), d["system_prompt"], d["name"]),
            event_sink=events.append)

    return manager, models, events, runtime


async def test_router_chats_streams_and_restores_only_its_own_thread(setup):
    manager, models, events, create = setup
    router = manager.get_active_id()
    specialist = manager.get_by_class_name("Planner")["id"]
    runtime = create()
    try:
        for text, owner, thread in [("Call me Rowan", router, "telegram-a"),
                                    ("Private planning details", specialist, "telegram-a"),
                                    ("Another conversation", router, "telegram-b")]:
            result = await runtime.wait(runtime.submit(TaskRequest(text, owner, thread, "telegram")))
            assert result["status"] == "completed", result["error"]
        assert any(e["type"] == "token" and e["agent_id"] == router for e in events)
    finally:
        await runtime.close()
    runtime = create()
    try:
        result = await runtime.wait(runtime.submit(TaskRequest("What did I ask you to call me?", router, "telegram-a", "telegram")))
        assert result["status"] == "completed"
        messages = models[router].calls[-1]
        assert [m["content"] for m in messages if m["role"] == "user"] == ["Call me Rowan", "What did I ask you to call me?"]
        assert "Private planning details" not in str(messages)
        assert "Another conversation" not in str(messages)
        await runtime.wait(runtime.submit(TaskRequest("New thread", router, "telegram-new", "telegram")))
        assert [m["content"] for m in models[router].calls[-1] if m["role"] == "user"] == ["New thread"]
    finally:
        await runtime.close()


async def test_handoff_keeps_original_request_and_specialist_owns_the_answer(setup):
    manager, models, events, create = setup
    router = manager.get_active_id()
    specialist = manager.get_by_class_name("Planner")["id"]
    models[router].tool_calls = [{"name": "route_to_agent", "args": {"agent_id": specialist, "context": "The budget is $50."}}]
    models[specialist].text = "Here is the plan."
    runtime = create()
    try:
        first = await runtime.wait(runtime.submit(TaskRequest("Make a plan", router, "web-a", "web")))
        assert first["status"] == "completed", first["error"]
        assert first["result_agent_id"] == specialist
        assert first["result"] == "Here is the plan."
        assert len(models[router].calls) == 1  # No pass back through Perseus to rewrite it.
        assert "Make a plan" in models[specialist].calls[-1][-1]["content"]
        assert "The budget is $50." in models[specialist].calls[-1][-1]["content"]
        second = await runtime.wait(runtime.submit(TaskRequest("Shorten it", router, "web-a", "web")))
        assert second["status"] == "completed"
        assert "Here is the plan." in str(models[specialist].calls[-1])
        assert "route_to_agent" in str(models[router].calls[-1][1:-1])
        assert "Here is the plan." not in str(models[router].calls[-1])
    finally:
        await runtime.close()


async def test_saved_router_runs_are_restored_without_other_agents_private_chats(setup):
    manager, models, events, create = setup
    router = manager.get_active_id()
    specialist = manager.get_by_class_name("Planner")["id"]
    runtime = create()
    try:
        for owner, text, answer in [(router, "Call me Rowan", "Okay, Rowan."),
                                   (specialist, "Private planning details", "Private answer")]:
            rid = runtime.submit(TaskRequest(text, owner, "telegram-old", "telegram"))
            run = runtime.store.get(rid)
            run["result"] = answer
            runtime._finish(run, "completed")
        result = await runtime.wait(runtime.submit(TaskRequest("Remember my name?", router, "telegram-old", "telegram")))
        assert result["status"] == "completed", result["error"]
        messages = models[router].calls[-1]
        assert "Call me Rowan" in str(messages)
        assert "Okay, Rowan." in str(messages)
        assert "Private" not in str(messages)
    finally:
        await runtime.close()


async def test_web_new_and_load_restore_the_same_per_agent_context(setup, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from questchain.gateway import server
    manager, models, events, create = setup
    runtime = create()
    router = manager.get_active_id()
    ws = SimpleNamespace(send_json=AsyncMock())
    monkeypatch.setattr(server, "_runtime", runtime)
    monkeypatch.setattr(server, "_agent_manager", manager)
    monkeypatch.setattr(server, "_clients", {id(ws): {"conversation_id": "web-saved", "agent_id": router}})
    try:
        await runtime.wait(runtime.submit(TaskRequest("Remember Rowan", router, "web-saved", "web")))
        await runtime.wait(runtime.submit(TaskRequest("Telegram private", router, "telegram-other", "telegram")))
        await server._handle_inbound(ws, {"type": "get_conversations"})
        assert [c["id"] for c in ws.send_json.call_args.args[0]["conversations"]] == ["web-saved"]
        await server._handle_inbound(ws, {"type": "new_thread"})
        assert ws.send_json.call_args.args[0]["runs"] == []
        assert server._clients[id(ws)]["conversation_id"] != "web-saved"
        await server._handle_inbound(ws, {"type": "load_conversation", "conversation_id": "web-saved"})
        assert ws.send_json.call_args.args[0]["runs"][0]["text"] == "Remember Rowan"
        await server._handle_inbound(ws, {"type": "chat", "message": "My name?"})
        await runtime.wait(ws.send_json.call_args.args[0]["run_id"])
        assert "Remember Rowan" in str(models[router].calls[-1])
        assert "Telegram private" not in str(models[router].calls[-1])
        for bad in ("telegram-other", "web-missing", "../../private"):
            await server._handle_inbound(ws, {"type": "load_conversation", "conversation_id": bad})
            assert ws.send_json.call_args.args[0]["type"] == "error"
            assert server._clients[id(ws)]["conversation_id"] == "web-saved"
    finally:
        await runtime.close()


async def test_telegram_new_and_history_restore_agent_context(setup, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from questchain import telegram
    manager, models, events, create = setup
    router = manager.get_active_id()
    specialist = manager.get_by_class_name("Planner")["id"]
    runtime = create()
    monkeypatch.setattr(telegram, "_thread_ids", {})
    monkeypatch.setattr(telegram, "TELEGRAM_OWNER_ID", 42)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(id=101),
        message=SimpleNamespace(text="", reply_text=AsyncMock(), reply_chat_action=AsyncMock()))
    context = SimpleNamespace(bot_data={"runtime": runtime, "agent_manager": manager}, chat_data={})
    try:
        await telegram._submit_runtime_message(update, context, "Call me Rowan")
        saved_thread = telegram._get_thread_id(101)
        context.chat_data["agent_id"] = specialist
        await telegram._submit_runtime_message(update, context, "Private planning details")
        await telegram.cmd_new(update, context)
        context.chat_data["agent_id"] = router
        await telegram._submit_runtime_message(update, context, "New thread")
        assert [m["content"] for m in models[router].calls[-1] if m["role"] == "user"] == ["New thread"]
        update.message.text = "/history " + saved_thread
        await telegram.cmd_history(update, context)
        assert "Private planning details" in update.message.reply_text.call_args.args[0]  # Visible shared thread.
        await telegram._submit_runtime_message(update, context, "My name?")
        assert "Call me Rowan" in str(models[router].calls[-1])
        assert "Private planning details" not in str(models[router].calls[-1])  # Private model context.
    finally:
        await runtime.close()


async def test_no_eligible_specialists_still_allows_normal_chat(setup):
    manager, models, events, create = setup
    router = manager.get_active_id()
    for definition in manager.all_agents():
        if definition["id"] != router:
            manager.update(definition["id"], routable=False)
    runtime = create()
    try:
        result = await runtime.wait(runtime.submit(TaskRequest("Hi", router, "cli-a")))
        assert result["status"] == "completed"
        assert models[router].tools == []
    finally:
        await runtime.close()


async def test_multiple_handoffs_cannot_execute_multiple_agents(setup):
    manager, models, events, create = setup
    router = manager.get_active_id()
    specialist = manager.get_by_class_name("Planner")["id"]
    models[router].tool_calls = [{"name": "route_to_agent", "args": {"agent_id": specialist}}] * 2
    runtime = create()
    try:
        result = await runtime.wait(runtime.submit(TaskRequest("Plan", router, "web-a", "web")))
        assert result["status"] == "failed"
        assert "only tool call" in result["error"]
        assert not models[specialist].calls
        assert len(runtime.store.runs()) == 1
    finally:
        await runtime.close()


@pytest.mark.parametrize("interrupted", [False, True])
async def test_failed_or_cancelled_turn_is_restored_with_existing_history(setup, interrupted):
    manager, models, events, create = setup
    router = manager.get_active_id()
    model = models[router]
    runtime = create()
    original_stream = model.chat_stream
    started = asyncio.Event()

    async def failing_stream(*args, **kwargs):
        yield Chunk(text="You said May 12")
        started.set()
        if interrupted:
            await asyncio.Event().wait()
        raise TimeoutError("Test timeout")

    try:
        await runtime.wait(runtime.submit(TaskRequest("Call me Rowan", router, "web-saved", "web")))
        model.chat_stream = failing_stream
        failed = runtime.submit(TaskRequest("My birthday is May 12", router, "web-saved", "web"))
        await asyncio.wait_for(started.wait(), 1)
        if interrupted:
            runtime.cancel(failed)
        result = await runtime.wait(failed)
        assert result["status"] == ("cancelled" if interrupted else "failed")
        assert result["result"] == "You said May 12"
    finally:
        await runtime.close()
        model.chat_stream = original_stream
    runtime = create()
    try:
        result = await runtime.wait(runtime.submit(TaskRequest("When is my birthday?", router, "web-saved", "web")))
        assert result["status"] == "completed"
        messages = model.calls[-1]
        assert [m["content"] for m in messages if m["role"] == "user"] == [
            "Call me Rowan", "My birthday is May 12", "When is my birthday?"]
        assert any("You said May 12" in m["content"] and "interrupted" in m["content"] for m in messages if m["role"] == "assistant")
    finally:
        await runtime.close()


async def test_interrupted_tool_batch_preserves_completed_results_and_valid_history(setup):
    executed = []

    @tool
    async def first():
        """First step."""
        executed.append("first")
        return "First step completed."

    @tool
    async def second():
        """Second step."""
        executed.append("second")
        return "Second step completed."

    async def check_permission(name, args):
        if name == "second":
            raise PermissionError("Permission revoked")

    model = ChatModel()
    model.tool_calls = [{"name": name, "args": {}} for name in ("first", "second")]
    agent = Agent(model, make_registry(first, second), "Assistant")
    with pytest.raises(PermissionError, match="Permission revoked"):
        async for _ in agent.run("Do both steps", "tool-interruption", on_tool_call=check_permission):
            pass
    assert executed == ["first"]
    saved = ContextManager("tool-interruption").messages
    assert [m["role"] for m in saved] == ["user", "assistant", "tool", "tool", "assistant"]
    assert saved[2]["content"] == "First step completed."
    assert saved[3]["name"] == "second"
    assert "unknown" in saved[3]["content"]
    assert "interrupted" in saved[4]["content"]

    model.tool_calls = []
    async for _ in agent.run("What happened?", "tool-interruption"):
        pass
    assert model.calls[-1][1:-1] == saved
