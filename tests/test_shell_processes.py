"""Real subprocess coverage: descendants must stop writing after cancellation."""
import asyncio
import os
import signal
import subprocess
import sys
import time

import pytest

from questchain.engine.builtins.shell import execute


@pytest.mark.parametrize("cancel", [True, False], ids=["cancel", "timeout"])
async def test_shell_stops_descendant_processes(tmp_path, cancel):
    script = tmp_path / "process_tree.py"
    script.write_text('''import os, subprocess, sys, time
from pathlib import Path
folder = Path(sys.argv[1])
if len(sys.argv) == 2:
    subprocess.Popen([sys.executable, __file__, str(folder), "child"]).wait()
else:
    (folder / "child.pid").write_text(str(os.getpid()))
    for count in range(600):
        (folder / "heartbeat").write_text(str(count))
        time.sleep(0.05)
''')
    command = f'"{sys.executable}" "{script}" "{tmp_path}"'
    task = asyncio.create_task(execute(command, timeout=30 if cancel else 2))
    heartbeat = tmp_path / "heartbeat"
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while not heartbeat.exists() and time.monotonic() < deadline and not task.done():
            await asyncio.sleep(0.02)
        assert heartbeat.exists(), "Test child did not start"
        child_pid = int((tmp_path / "child.pid").read_text())
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 8)
        else:
            assert "timed out" in await asyncio.wait_for(task, 8)
        last_write = heartbeat.stat().st_mtime_ns
        await asyncio.sleep(0.3)
        assert heartbeat.stat().st_mtime_ns == last_write, "A descendant continued writing after cleanup"
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        # If the assertion fails, clean up only the disposable child this test created.
        if child_pid and heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 0.2:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child_pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            else:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
