"""Exercise terminal interrupts in a subprocess so a regression cannot kill pytest."""

import os
import asyncio
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("interface", ["terminal", "telegram", "web"])
@pytest.mark.parametrize("exit_key", ["ctrl-c", "ctrl-d"])
def test_exit_key_shuts_down_repl_and_services_cleanly(tmp_path, interface, exit_key):
    script = r'''
import asyncio
import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from questchain import cli

async def main():
    prompts = asyncio.Queue()
    stop_requested = asyncio.Event()
    service_stopped = asyncio.Event()

    class TrackedSession(PromptSession):
        async def prompt_async(self, *args, **kwargs):
            prompts.put_nowait(True)
            return await super().prompt_async(*args, **kwargs)

    async def service():
        try:
            await stop_requested.wait()
        finally:
            service_stopped.set()

    background = asyncio.create_task(service())
    interface = sys.argv[1]
    queues = {} if interface == "terminal" else {interface + "_queue": asyncio.Queue()}

    async def run_and_shutdown(session):
        try:
            await cli._repl_loop(session, {}, {}, **queues)
        finally:
            assert not service_stopped.is_set(), "Service was cancelled before orderly shutdown"
            stop_requested.set()
            await background

    with create_pipe_input() as pipe:
        session = TrackedSession(input=pipe, output=DummyOutput())
        repl = asyncio.create_task(run_and_shutdown(session))
        await asyncio.wait_for(prompts.get(), timeout=3)
        pipe.send_text("\x03" if sys.argv[2] == "ctrl-c" else "\x04")
        await asyncio.wait_for(repl, timeout=3)
    assert prompts.empty(), "Exit key returned to the prompt instead of quitting"
    assert service_stopped.is_set(), "Shutdown left a background service running"
    assert not (asyncio.all_tasks() - {asyncio.current_task()}), "Input tasks leaked"
    print("INTERRUPT_AND_EXIT_OK")

asyncio.run(main())
'''
    result = subprocess.run(
        [sys.executable, "-c", script, interface, exit_key],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, QUESTCHAIN_DATA_DIR=str(tmp_path), PYTHONIOENCODING="utf-8"),
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Press Ctrl+D to exit." not in result.stdout
    assert "Goodbye!" in result.stdout
    assert "INTERRUPT_AND_EXIT_OK" in result.stdout
    assert not result.stderr


def test_ctrl_c_during_work_cleans_up_without_traceback(tmp_path):
    script = r'''
import asyncio
import signal
from questchain import cli

cleaned_up = False

async def working_repl(*args):
    global cleaned_up
    try:
        asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)
        await asyncio.Event().wait()
    finally:
        await asyncio.sleep(0)
        cleaned_up = True

cli.repl = working_repl
cli.main()
assert cleaned_up, "Ctrl+C skipped application cleanup"
print("WORK_SHUTDOWN_OK")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, QUESTCHAIN_DATA_DIR=str(tmp_path), PYTHONIOENCODING="utf-8"),
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WORK_SHUTDOWN_OK" in result.stdout
    assert not result.stderr


@pytest.mark.asyncio
async def test_cancelling_repl_drains_all_input_waiters():
    from questchain import cli

    ready = asyncio.Event()

    class WaitingSession:
        async def prompt_async(self, *args, **kwargs):
            ready.set()
            await asyncio.Event().wait()

    existing = asyncio.all_tasks()
    repl = asyncio.create_task(cli._repl_loop(
        WaitingSession(), {}, {}, telegram_queue=asyncio.Queue(), web_queue=asyncio.Queue(),
    ))
    await asyncio.wait_for(ready.wait(), timeout=3)
    repl.cancel()
    with pytest.raises(asyncio.CancelledError):
        await repl
    leaked = asyncio.all_tasks() - existing
    # Clean up even on failure, keeping this regression isolated from other tests.
    for task in leaked:
        task.cancel()
    await asyncio.gather(*leaked, return_exceptions=True)
    assert not leaked, "Cancelling the REPL left prompt or queue tasks running"
