"""Storage failures must not partially apply schedule edits or erase corrupt state."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from questchain.scheduler import CronScheduler


@pytest.fixture
async def scheduler(tmp_path):
    scheduler = CronScheduler(None, AsyncMock(), jobs_path=tmp_path / "jobs.json")
    await scheduler.start()
    yield scheduler
    await scheduler.stop()
    await asyncio.sleep(0)


def add(scheduler, name="original"):
    return scheduler.add_job(name, "0 0 1 1 *", "instructions")


@pytest.mark.parametrize("operation", ["add", "edit", "pause", "resume", "remove", "result"])
async def test_write_failure_keeps_memory_file_and_live_schedule(scheduler, monkeypatch, operation):
    job = add(scheduler)
    if operation == "resume":
        scheduler.set_enabled(job["id"], False)
    before_file = scheduler._jobs_path.read_bytes()
    before_jobs = scheduler.list_jobs()
    before_live = scheduler._scheduler.get_job("cron:" + job["id"])
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(scheduler, "_save_jobs", fail)
    with pytest.raises(OSError, match="disk full"):
        if operation == "add":
            add(scheduler, "new")
        elif operation == "edit":
            scheduler.update_job(job["id"], name="edited", cron_expression="0 12 * * *", prompt="new")
        elif operation in {"pause", "resume"}:
            scheduler.set_enabled(job["id"], operation == "resume")
        elif operation == "remove":
            scheduler.remove_job(job["id"])
        else:
            scheduler._record_result(job["id"], "success", "changed")
    assert scheduler.list_jobs() == before_jobs
    assert scheduler._jobs_path.read_bytes() == before_file
    assert scheduler._scheduler.get_job("cron:" + job["id"]) is before_live
    assert len(scheduler._scheduler.get_jobs()) == (0 if operation == "resume" else 1)


@pytest.mark.parametrize("contents", ['{', '{}', '[{}]', '[{"id":"a","name":"n","prompt":"p","cron_expression":"bad"}]'])
async def test_corrupt_existing_file_is_never_silently_reset(tmp_path, contents):
    path = tmp_path / "jobs.json"
    path.write_text(contents)
    scheduler = CronScheduler(None, AsyncMock(), jobs_path=path)
    with pytest.raises(ValueError, match="load quests"):
        await scheduler.start()
    assert not scheduler._scheduler.running
    with pytest.raises(ValueError, match="load"):
        add(scheduler)
    assert path.read_text() == contents


async def test_replace_failure_preserves_old_json_and_registration(scheduler, monkeypatch):
    import os
    job = add(scheduler)
    before = scheduler._jobs_path.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("rename denied")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError, match="rename denied"):
        scheduler.set_enabled(job["id"], False)
    assert scheduler._jobs_path.read_bytes() == before
    assert scheduler.get_job(job["id"])["enabled"]
    assert scheduler._scheduler.get_job("cron:" + job["id"])


async def test_file_sync_failure_leaves_old_file_and_cleans_temp(scheduler, monkeypatch):
    import os
    job = add(scheduler)
    before = scheduler._jobs_path.read_bytes()
    monkeypatch.setattr(os, "fsync", lambda _: (_ for _ in ()).throw(OSError("sync denied")))
    with pytest.raises(OSError, match="sync denied"):
        scheduler.remove_job(job["id"])
    assert scheduler._jobs_path.read_bytes() == before
    assert scheduler.get_job(job["id"])
    assert not list(scheduler._jobs_path.parent.glob(".jobs.json.*.tmp"))


async def test_directory_sync_failure_is_committed_not_false_rollback(scheduler, monkeypatch, caplog):
    import os
    import stat
    if os.name != "posix":
        pytest.skip("Directory fsync is POSIX-specific")
    job = add(scheduler)
    original = os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory sync denied")
        return original(fd)
    monkeypatch.setattr(os, "fsync", fail_directory)
    scheduler.set_enabled(job["id"], False)
    assert not json.loads(scheduler._jobs_path.read_text())[0]["enabled"]
    assert not scheduler.get_job(job["id"])["enabled"]
    assert scheduler._scheduler.get_job("cron:" + job["id"]) is None
    assert "state was replaced" in caplog.text
    assert "durability is uncertain" in caplog.text


async def test_replacement_preserves_existing_file_and_directory_mode(scheduler):
    import os
    import stat
    if os.name != "posix":
        pytest.skip("POSIX modes")
    job = add(scheduler)
    scheduler._jobs_path.chmod(0o640)
    directory_mode = stat.S_IMODE(scheduler._jobs_path.parent.stat().st_mode)
    scheduler.set_enabled(job["id"], False)
    assert stat.S_IMODE(scheduler._jobs_path.stat().st_mode) == 0o640
    assert stat.S_IMODE(scheduler._jobs_path.parent.stat().st_mode) == directory_mode


@pytest.mark.parametrize("operation", ["register", "remove"])
async def test_post_commit_registration_failure_pauses_instead_of_running_stale_state(scheduler, monkeypatch, operation):
    from apscheduler.schedulers.base import STATE_PAUSED
    job = add(scheduler)
    def fail(*args, **kwargs):
        raise RuntimeError("executor failure")
    monkeypatch.setattr(scheduler._scheduler, "add_job" if operation == "register" else "remove_job", fail)
    with pytest.raises(RuntimeError, match="state was saved"):
        if operation == "register":
            scheduler.update_job(job["id"], name="new", cron_expression="0 0 * * *", prompt="new")
        else:
            scheduler.remove_job(job["id"])
    assert scheduler._scheduler.state == STATE_PAUSED
    disk = json.loads(scheduler._jobs_path.read_text())
    assert disk == scheduler._jobs
    assert (disk[0]["name"] if disk else None) == ("new" if operation == "register" else None)


async def test_write_errors_are_visible_through_schedule_adapters(scheduler, monkeypatch):
    from io import StringIO
    from types import SimpleNamespace
    from rich.console import Console
    from questchain import cli, telegram
    from questchain import scheduler as module
    from questchain.gateway.server import _handle_inbound
    monkeypatch.setattr(module, "_scheduler_instance", scheduler)
    monkeypatch.setattr(scheduler, "_save_jobs", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    output = StringIO()
    monkeypatch.setattr(cli, "console", Console(file=output))
    assert cli.handle_command("/quests add Test | 0 0 * * * | UTC | Work", {})
    assert "disk full" in output.getvalue()
    monkeypatch.setattr(telegram, "_is_owner", lambda _: True)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=SimpleNamespace(
        text="/quests add Test | 0 0 * * * | UTC | Work", reply_text=AsyncMock()))
    await telegram.cmd_cron(update, SimpleNamespace())
    assert "disk full" in update.message.reply_text.call_args.args[0]
    ws = SimpleNamespace(send_json=AsyncMock())
    await _handle_inbound(ws, {"type": "save_cron", "name": "Test", "prompt": "Work", "cron_expression": "0 0 * * *"})
    assert ws.send_json.call_args.args[0] == {"type": "cron_error", "message": "disk full"}
    assert scheduler.list_jobs() == []
    assert not scheduler._scheduler.get_jobs()


@pytest.mark.parametrize("phase", ["before", "after"])
async def test_process_exit_around_replace_leaves_one_complete_snapshot(scheduler, phase):
    import os
    from pathlib import Path
    import subprocess
    import sys
    add(scheduler)
    script = '''import os, sys
from pathlib import Path
from unittest.mock import AsyncMock
from questchain.scheduler import CronScheduler
s = CronScheduler(None, AsyncMock(), jobs_path=Path(sys.argv[1]))
s._load_jobs()
replace = os.replace
def crash(source, target):
    if sys.argv[2] == "after":
        replace(source, target)
    os._exit(73)
os.replace = crash
s.add_job("new", "0 0 1 1 *", "instructions")
'''
    result = subprocess.run([sys.executable, "-c", script, str(scheduler._jobs_path), phase],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert result.returncode == 73, result.stderr
    restored = CronScheduler(None, AsyncMock(), jobs_path=scheduler._jobs_path)
    await restored.start()
    try:
        assert [j["name"] for j in restored.list_jobs()] == (["original"] if phase == "before" else ["original", "new"])
        await asyncio.sleep(.02)
        restored._send_callback.assert_not_awaited()
        assert not restored._running
    finally:
        await restored.stop()


async def test_failed_load_requires_successful_reload_before_writes(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text("broken")
    scheduler = CronScheduler(None, AsyncMock(), jobs_path=path)
    with pytest.raises(ValueError, match="load quests"):
        scheduler._load_jobs()
    path.write_text("[]")  # Explicit operator repair.
    with pytest.raises(ValueError, match="failed load"):
        add(scheduler)
    scheduler._load_jobs()
    add(scheduler)
    assert json.loads(path.read_text())[0]["name"] == "original"


async def test_missing_owner_pause_must_persist_before_start(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path = tmp_path / "jobs.json"
    data = [{"id": "legacy", "name": "legacy", "prompt": "p", "cron_expression": "0 0 * * *", "agent_id": "missing", "enabled": True}]
    path.write_text(json.dumps(data))
    scheduler = CronScheduler(None, AsyncMock(), jobs_path=path, agent_manager=SimpleNamespace(get=lambda _: None))
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(scheduler, "_save_jobs", fail)
    with pytest.raises(OSError, match="disk full"):
        await scheduler.start()
    assert not scheduler._scheduler.running
    assert not scheduler._scheduler.get_jobs()
    assert json.loads(path.read_text()) == data


def test_existing_file_cannot_be_overwritten_before_loading(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text("broken")
    scheduler = CronScheduler(None, AsyncMock(), jobs_path=path)
    with pytest.raises(ValueError, match="Load quests"):
        add(scheduler)
    assert path.read_text() == "broken"


@pytest.mark.parametrize("bad_field", [{"enabled": "false"}, {"timezone": []}, {"id": None}])
def test_invalid_record_fields_fail_closed(tmp_path, bad_field):
    path = tmp_path / "jobs.json"
    data = [{"id": "one", "name": "Test", "prompt": "Work", "cron_expression": "0 0 * * *", **bad_field}]
    path.write_text(json.dumps(data))
    scheduler = CronScheduler(None, AsyncMock(), jobs_path=path)
    with pytest.raises(ValueError, match="load quests"):
        scheduler._load_jobs()
    assert json.loads(path.read_text()) == data
