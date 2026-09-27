"""Exercise terminal interrupts in a subprocess so a regression cannot kill pytest."""

import os
import asyncio
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("interface", ["terminal", "telegram", "web"])
def test_ctrl_c_keeps_prompt_and_background_services_alive(tmp_path, interface):
    script = r'''
import asyncio
import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from questchain import cli

async def main():
    prompts = asyncio.Queue()
    service_stopped = asyncio.Event()

    class TrackedSession(PromptSession):
        async def prompt_async(self, *args, **kwargs):
            prompts.put_nowait(True)
            return await super().prompt_async(*args, **kwargs)

    async def service():
        try:
            await asyncio.Event().wait()
        finally:
            service_stopped.set()

    background = asyncio.create_task(service())
    interface = sys.argv[1]
    queues = {} if interface == "terminal" else {interface + "_queue": asyncio.Queue()}
    with create_pipe_input() as pipe:
        session = TrackedSession(input=pipe, output=DummyOutput())
        repl = asyncio.create_task(cli._repl_loop(session, {}, {}, **queues))
        await asyncio.wait_for(prompts.get(), timeout=3)
        pipe.send_text("\x03")
        await asyncio.wait_for(prompts.get(), timeout=3)
        assert not service_stopped.is_set(), "Ctrl+C stopped a background service"
        assert not repl.done(), "Ctrl+C terminated the REPL"
        pipe.send_text("\x04")
        await asyncio.wait_for(repl, timeout=3)
    assert not service_stopped.is_set(), "Prompt shutdown cancelled unrelated services"
    background.cancel()
    await asyncio.gather(background, return_exceptions=True)
    assert not (asyncio.all_tasks() - {asyncio.current_task()}), "Input tasks leaked"
    print("INTERRUPT_AND_EXIT_OK")

asyncio.run(main())
'''
    result = subprocess.run(
        [sys.executable, "-c", script, interface],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, QUESTCHAIN_DATA_DIR=str(tmp_path), PYTHONIOENCODING="utf-8"),
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Press Ctrl+D to exit." in result.stdout
    assert "Goodbye!" in result.stdout
    assert "INTERRUPT_AND_EXIT_OK" in result.stdout
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
