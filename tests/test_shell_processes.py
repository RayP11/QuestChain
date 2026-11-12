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


@pytest.mark.parametrize("stream", ["stdout", "stderr", "both"])
async def test_shell_rejects_excess_output(tmp_path, stream):
    script = tmp_path / "noisy.py"
    script.write_text(
        "import sys\n"
        + ("sys.stdout.buffer.write(b'x' * 262145)\n" if stream == "stdout" else
           "sys.stderr.buffer.write(b'x' * 262145)\n" if stream == "stderr" else
           "sys.stdout.buffer.write(b'x' * 150000)\nsys.stderr.buffer.write(b'y' * 150000)\n")
    )
    result = await execute(f'"{sys.executable}" "{script}"')
    assert result.startswith("Error: output exceeded")
    assert len(result) < 1000


@pytest.mark.parametrize("timeout", [None, True, 0, -1, 1801, float("inf"), float("nan"), "60"])
async def test_shell_rejects_invalid_deadline_before_execution(tmp_path, timeout):
    marker = tmp_path / "executed"
    script = tmp_path / "marker.py"
    script.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    result = await execute(f'"{sys.executable}" "{script}"', timeout=timeout)
    assert result.startswith("Error: timeout must be")
    assert not marker.exists()


async def test_shell_preserves_output_at_budget_and_nonzero_exit(tmp_path):
    script = tmp_path / "boundary.py"
    script.write_text("import sys\nsys.stdout.buffer.write(b'x' * 131072)\n"
                      "sys.stderr.buffer.write(b'y' * 131072)\nsys.exit(7)\n")
    result = await execute(f'"{sys.executable}" "{script}"')
    assert result == "Error: command exited with code 7\n" + "x" * 131072 + "\n[stderr]\n" + "y" * 131072


async def test_output_overflow_stops_process_tree(tmp_path):
    script = tmp_path / "flood.py"
    script.write_text('''import os, subprocess, sys, time
from pathlib import Path
folder = Path(sys.argv[1])
if len(sys.argv) == 2:
    subprocess.Popen([sys.executable, __file__, str(folder), "child"]).wait()
else:
    (folder / "child.pid").write_text(str(os.getpid()))
    for count in range(600):
        (folder / "heartbeat").write_text(str(count))
        sys.stdout.buffer.write(b'x' * 65536)
        sys.stdout.buffer.flush()
        time.sleep(0.01)
''')
    task = asyncio.create_task(execute(f'"{sys.executable}" "{script}" "{tmp_path}"', timeout=10))
    try:
        result = await asyncio.wait_for(task, 8)
        assert result.startswith("Error: output exceeded")
        heartbeat = tmp_path / "heartbeat"
        before = heartbeat.stat().st_mtime_ns
        await asyncio.sleep(.2)
        assert heartbeat.stat().st_mtime_ns == before
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        pid_file = tmp_path / "child.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text())
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            else:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
