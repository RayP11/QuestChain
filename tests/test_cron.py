"""Shared cron behavior through scheduler, terminal, WebSocket, and Telegram."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from questchain.scheduler import CronScheduler, set_scheduler


class Agent:
    model = SimpleNamespace(model_name="test")

    def __init__(self):
        self.calls = []

    async def run(self, prompt, thread_id):
        self.calls.append((prompt, thread_id))
        yield "Completed: " + prompt


@pytest.fixture
async def scheduler(tmp_path):
    instance = CronScheduler(Agent(), AsyncMock(), jobs_path=tmp_path / "jobs.json")
    await instance.start()
    set_scheduler(instance)
    yield instance
    await instance.stop()
    set_scheduler(None)
    await asyncio.sleep(0)


def add(scheduler):
    return scheduler.add_job("Morning", "0 9 * * mon", "Summarize notes", "America/New_York")


@pytest.mark.asyncio
async def test_persistence_edit_pause_and_resume(scheduler):
    job = add(scheduler)
    scheduler.set_enabled(job["id"], False)
    scheduler.update_job(job["id"], name="Evening", cron_expression="0 18 * * fri",
                         prompt="Updated instructions", timezone_str="UTC")
    assert scheduler._scheduler.get_job(f"cron:{job['id']}") is None
    other = CronScheduler(Agent(), AsyncMock(), jobs_path=scheduler._jobs_path)
    await other.start()
    try:
        restored = other.list_jobs()[0]
        assert restored["name"] == "Evening"
        assert restored["enabled"] is False
        assert restored["prompt"] == "Updated instructions"
        other.set_enabled(job["id"], True)
        assert other.list_jobs()[0]["next_run"]
        other.remove_job(job["id"])
        assert other.list_jobs() == []
    finally:
        await other.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"cron_expression": "invalid"}, {"timezone_str": "Not/AZone"},
    {"name": " "}, {"prompt": " "}, {"agent_id": "missing"},
])
async def test_validation_does_not_mutate_jobs(scheduler, changes):
    job = add(scheduler)
    values = dict(name="Updated", cron_expression="0 9 * * *", prompt="Instructions", timezone_str="UTC")
    values.update(changes)
    with pytest.raises((ValueError, KeyError)):
        scheduler.update_job(job["id"], **values)
    assert scheduler.get_job(job["id"]) == job


@pytest.mark.asyncio
async def test_actual_scheduler_fires_and_records_result(scheduler):
    job = add(scheduler)
    scheduler._scheduler.modify_job(f"cron:{job['id']}", next_run_time=datetime.now(timezone.utc))
    async with asyncio.timeout(3):
        while not scheduler.get_job(job["id"]).get("last_run"):
            await asyncio.sleep(.01)
    saved = scheduler.get_job(job["id"])
    assert saved["last_status"] == "success"
    assert saved["last_result"] == "Completed: Summarize notes"
    assert scheduler._agent.calls == [("Summarize notes", f"cron:{job['id']}")]
    scheduler._send_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_web_terminal_and_telegram_share_jobs(scheduler, monkeypatch):
    from questchain import cli, telegram
    from questchain.gateway.server import _handle_inbound

    ws = SimpleNamespace(send_json=AsyncMock())
    await _handle_inbound(ws, {"type": "save_cron", "name": "Web job", "prompt": "Hello",
                               "cron_expression": "0 9 * * *", "timezone": "UTC"})
    job_id = ws.send_json.call_args.args[0]["cron_id"]
    assert cli.handle_command(f"/cron pause {job_id}", {}) is True
    assert not scheduler.get_job(job_id)["enabled"]
    monkeypatch.setattr(telegram, "_is_owner", lambda user_id: user_id == 42)
    reply = AsyncMock()
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42),
                             message=SimpleNamespace(text=f"/cron resume {job_id}", reply_text=reply))
    await telegram.cmd_cron(update, SimpleNamespace())
    assert scheduler.get_job(job_id)["enabled"]
    assert "resumed" in reply.call_args.args[0]
    update.message.text = "/cron add Telegram job | 0 10 * * mon | UTC | Preserve My Case"
    await telegram.cmd_cron(update, SimpleNamespace())
    assert scheduler.list_jobs()[1]["prompt"] == "Preserve My Case"
    await _handle_inbound(ws, {"type": "get_cron_jobs"})
    assert len(ws.send_json.call_args.args[0]["jobs"]) == 2
    await _handle_inbound(ws, {"type": "delete_cron", "cron_id": job_id})
    assert len(scheduler.list_jobs()) == 1


@pytest.mark.asyncio
async def test_web_validation_returns_visible_error(scheduler):
    from questchain.gateway.server import _handle_inbound

    ws = SimpleNamespace(send_json=AsyncMock())
    await _handle_inbound(ws, {"type": "save_cron", "name": "Bad", "prompt": "Hello", "cron_expression": "bad"})
    assert ws.send_json.call_args.args[0]["type"] == "cron_error"
    assert scheduler.list_jobs() == []


@pytest.mark.asyncio
async def test_telegram_rejects_non_owner(scheduler, monkeypatch):
    from questchain import telegram

    monkeypatch.setattr(telegram, "_is_owner", lambda user_id: False)
    monkeypatch.setattr(telegram, "_reject", AsyncMock())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=9),
                             message=SimpleNamespace(text="/cron add Bad | * * * * * | UTC | Bad"))
    await telegram.cmd_cron(update, SimpleNamespace())
    telegram._reject.assert_awaited_once_with(update)
    assert scheduler.list_jobs() == []


@pytest.mark.asyncio
async def test_manual_run_of_paused_job_records_failure(scheduler):
    job = add(scheduler)
    scheduler.set_enabled(job["id"], False)

    async def fail(prompt, thread_id):
        raise RuntimeError("Model unavailable")
        yield ""

    scheduler._agent.run = fail
    scheduler.run_now(job["id"])
    async with asyncio.timeout(3):
        while not scheduler.get_job(job["id"]).get("last_run"):
            await asyncio.sleep(.01)
    result = scheduler.get_job(job["id"])
    assert result["last_status"] == "error"
    assert result["last_result"] == "Model unavailable"
    assert result["enabled"] is False


def test_legacy_progression_is_preserved_as_jobs(tmp_path, monkeypatch):
    import json
    from questchain import config
    from questchain.progression import ProgressionManager

    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path)
    path = config.get_progression_dir() / "default.json"
    path.write_text(json.dumps({"agent_id": "default", "quests_completed": 9, "total_xp": 100}))
    manager = ProgressionManager("default", "Custom")
    assert manager.load().jobs_completed == 9
    manager.award_xp([], is_job=True)
    assert manager.get_record().jobs_completed == 10
    assert "busy_bee" in [a.id for a in manager.get_record().achievements]
    assert json.loads(path.read_text())["jobs_completed"] == 10


@pytest.mark.asyncio
async def test_telegram_registers_cron_without_quest_commands(tmp_path, monkeypatch):
    from questchain import config, telegram

    monkeypatch.setattr(config, "QUESTCHAIN_DATA_DIR", tmp_path)
    monkeypatch.setattr(telegram, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(telegram, "TELEGRAM_OWNER_ID", 42)
    handlers = []
    app = SimpleNamespace(
        bot_data={}, add_handler=handlers.append, add_error_handler=lambda handler: None,
        initialize=AsyncMock(), start=AsyncMock(), stop=AsyncMock(), shutdown=AsyncMock(),
        bot=SimpleNamespace(set_my_commands=AsyncMock()),
        updater=SimpleNamespace(start_polling=AsyncMock(), stop=AsyncMock()),
    )
    builder = SimpleNamespace(build=lambda: app)
    builder.token = lambda token: builder
    monkeypatch.setattr(telegram, "Application", SimpleNamespace(builder=lambda: builder))
    _, stop = await telegram.run_telegram_alongside_cli({"agent": Agent()}, "test", asyncio.Queue(), None)
    try:
        commands = {c.command for c in app.bot.set_my_commands.call_args.args[0]}
        assert "cron" in commands
        assert not commands.intersection({"quest", "quests", "tasks"})
        registered = set().union(*(getattr(h, "commands", set()) for h in handlers))
        assert "cron" in registered
        assert not registered.intersection({"quest", "quests"})
    finally:
        await stop()
