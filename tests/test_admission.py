"""Bound queued work without silently accepting or replaying overload."""
import asyncio
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from rich.console import Console

from questchain.runtime import TaskRequest, TaskRuntime


@pytest.fixture
async def runtime(tmp_path):
    definition = {"id": "default", "kind": "main", "name": "Main", "tools": []}
    manager = SimpleNamespace(get=lambda _: definition, get_active_id=lambda: "default")
    events = []
    runtime = TaskRuntime(manager, default_model="unused", path=tmp_path / "runs.sqlite3", event_sink=events.append)
    runtime.test_events = events
    runtime.test_started = asyncio.Event()
    runtime.test_release = asyncio.Event()
    runtime.test_calls = []
    async def execute(run):
        runtime.test_calls.append(run["text"])
        runtime.test_started.set()
        await runtime.test_release.wait()
        runtime._finish(run, "completed")
    runtime._execute = execute
    yield runtime
    await runtime.close()


def request(text="work", source="cli", **kwargs):
    return TaskRequest(text, "default", "cli-test", source, **kwargs)


async def test_burst_rejected_before_any_persistence_or_callbacks(runtime):
    for i in range(32):
        runtime.submit(request(str(i)))
    before_runs = runtime.store.runs()
    before_events = list(runtime.test_events)
    before_futures = dict(runtime._futures)
    with pytest.raises(ValueError, match="capacity"):
        runtime.submit(request("overload", audio_callback=lambda _: None))
    assert runtime.store.runs() == before_runs
    assert runtime.test_events == before_events
    assert runtime._futures == before_futures
    assert runtime._audio_callbacks == {}
    assert runtime.queue.qsize() == 32


async def test_cancelled_queued_requests_do_not_accumulate_tombstones(runtime):
    runtime.submit(request("active"))
    await runtime.test_started.wait()
    for i in range(100):
        run_id = runtime.submit(request(str(i)))
        runtime.cancel(run_id)
        assert (await runtime.wait(run_id))["status"] == "cancelled"
    assert runtime.queue.qsize() == 0
    assert len(runtime._futures) == 1
    runtime.test_release.set()
    await asyncio.wait_for(runtime.queue.join(), 2)
    assert runtime.test_calls == ["active"]


async def test_rejected_terminal_submit_does_not_leak_event_subscriber(monkeypatch):
    from questchain.runtime.terminal import run_terminal_task
    from questchain.gateway.events import get_bus
    def reject(_):
        raise ValueError("Task capacity reached")
    bus = get_bus()
    before = list(bus._queues)
    try:
        with pytest.raises(ValueError, match="capacity"):
            await run_terminal_task(SimpleNamespace(submit=reject), request(), Console(file=StringIO()))
        assert bus._queues == before
    finally:
        for queue in list(bus._queues):
            if queue not in before:
                bus.unsubscribe(queue)


async def test_full_queue_deduplicates_existing_occurrence_and_reclaims_cancelled_slot(runtime):
    first = runtime.submit(request("occurrence", occurrence_key="same"))
    for i in range(31):
        runtime.submit(request(str(i)))
    assert runtime.submit(request("occurrence", occurrence_key="same")) == first
    runtime.cancel(first)
    assert runtime.submit(request("occurrence", occurrence_key="same")) == first
    replacement = runtime.submit(request("replacement"))
    assert runtime.store.get(replacement)["status"] == "queued"
    assert len(runtime._futures) == 32
    assert runtime.queue.qsize() == 32


async def test_active_slot_counts_toward_limit_and_priority_survives_cancellation(runtime):
    runtime.submit(request("active"))
    await runtime.test_started.wait()
    for i in range(30):
        runtime.submit(request(f"scheduled-{i}", "cron"))
    cancelled = runtime.submit(request("cancelled", "cron"))
    with pytest.raises(ValueError, match="capacity"):
        runtime.submit(request("overload"))
    runtime.cancel(cancelled)
    runtime.submit(request("interactive"))
    runtime.test_release.set()
    await asyncio.wait_for(runtime.queue.join(), 2)
    assert runtime.test_calls == ["active", "interactive"] + [f"scheduled-{i}" for i in range(30)]
    assert not runtime._futures


async def test_rebuild_does_not_wake_join_while_retained_work_remains(runtime):
    # Hold worker startup to exercise cancellation before any item is dequeued.
    held = asyncio.create_task(asyncio.Event().wait())
    runtime._worker_task = held
    joiner = None
    try:
        cancelled = runtime.submit(request("cancel"))
        runtime.submit(request("retained"))
        joiner = asyncio.create_task(runtime.queue.join())
        await asyncio.sleep(0)
        runtime.cancel(cancelled)
        await asyncio.sleep(0)
        assert not joiner.done()
    finally:
        held.cancel()
        await asyncio.gather(held, return_exceptions=True)
        runtime._worker_task = asyncio.create_task(runtime._worker())
        runtime.test_release.set()
        if joiner:
            await asyncio.wait_for(joiner, 2)


async def test_overload_is_visible_to_web_telegram_and_scheduler(runtime, monkeypatch, tmp_path):
    from questchain.gateway import server
    from questchain import telegram
    from questchain.scheduler import CronScheduler
    for i in range(32):
        runtime.submit(request(str(i)))
    monkeypatch.setattr(server, "_runtime", runtime)
    monkeypatch.setattr(server, "_agent_manager", runtime.manager)
    monkeypatch.setattr(server, "_clients", {})
    ws = SimpleNamespace(send_json=AsyncMock())
    await server._handle_inbound(ws, {"type": "chat", "message": "rejected"})
    assert ws.send_json.call_args.args[0]["type"] == "error"
    assert "capacity" in ws.send_json.call_args.args[0]["error"]
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), message=SimpleNamespace(message_id=1, reply_text=AsyncMock()))
    context = SimpleNamespace(bot_data={"runtime": runtime, "agent_manager": runtime.manager}, chat_data={})
    monkeypatch.setattr(telegram, "_get_thread_id", lambda _: "test")
    await telegram._submit_runtime_message(update, context, "rejected")
    assert "capacity" in update.message.reply_text.call_args.args[0]
    assert "last_run_id" not in context.chat_data
    scheduler = CronScheduler(None, AsyncMock(), jobs_path=tmp_path / "jobs.json", runtime=runtime)
    job = scheduler.add_job("test", "0 0 * * *", "rejected")
    await scheduler._run_task(job, "occurrence")
    assert scheduler.get_job(job["id"])["last_status"] == "error"
    assert "capacity" in scheduler.get_job(job["id"])["last_result"]
    scheduler._send_callback.assert_awaited_once()
    assert "capacity" in scheduler._send_callback.call_args.args[0]
    assert len(runtime.store.runs()) == 32


async def test_cli_retry_overload_returns_to_prompt(runtime, monkeypatch):
    from questchain import cli
    cancelled = runtime.submit(request("retry me"))
    runtime.cancel(cancelled)
    for i in range(32):
        runtime.submit(request(str(i)))
    inputs = iter(["/retry", "/exit"])
    class Session:
        async def prompt_async(self, *args, **kwargs):
            return next(inputs)
    output = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output))
    state = {"runtime": runtime, "last_run_id": cancelled, "thread_id": "test"}
    await cli._repl_loop(Session(), {"runtime": runtime}, state)
    assert "capacity" in output.getvalue()
    assert state["last_run_id"] == cancelled
    assert len(runtime.store.runs()) == 33
