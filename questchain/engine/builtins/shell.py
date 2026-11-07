"""Built-in shell execution tool."""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess

from questchain.engine.tools import tool

# Shell metacharacters that require a shell interpreter
_SHELL_CHARS = frozenset('|&;<>(){}$`!')
_MAX_OUTPUT_BYTES = 256 * 1024
_MAX_TIMEOUT_SECONDS = 1800


class _OutputLimitExceeded(Exception):
    pass


async def _communicate_bounded(proc, timeout: int) -> tuple[bytes, bytes]:
    """Drain both pipes concurrently; retain at most one shared output budget.

    Readers keep draining after overflow so process-tree cleanup cannot deadlock
    on a full pipe. No overflowing output is returned to the model or persisted.
    """
    remaining = _MAX_OUTPUT_BYTES
    exceeded = asyncio.Event()

    async def read(stream):
        nonlocal remaining
        chunks = []
        while chunk := await stream.read(8192):
            if len(chunk) > remaining:
                exceeded.set()
            if not exceeded.is_set():
                remaining -= len(chunk)
                chunks.append(chunk)
        return b"".join(chunks)

    stdout = asyncio.create_task(read(proc.stdout))
    stderr = asyncio.create_task(read(proc.stderr))
    completed = asyncio.gather(stdout, stderr, proc.wait())
    overflow = asyncio.create_task(exceeded.wait())
    try:
        async with asyncio.timeout(timeout):
            await asyncio.wait((completed, overflow), return_when=asyncio.FIRST_COMPLETED)
            if exceeded.is_set():
                raise _OutputLimitExceeded
            out, err, _ = await completed
            return out, err
    except BaseException:
        await _stop_process_tree(proc)
        raise
    finally:
        completed.cancel()
        overflow.cancel()
        await asyncio.gather(completed, overflow, return_exceptions=True)


def _needs_shell(command: str) -> bool:
    """Return True if the command contains shell metacharacters."""
    return any(c in _SHELL_CHARS for c in command) or '>>' in command


async def _stop_process_tree(proc) -> None:
    """Stop owned descendants as well as the shell, with bounded cleanup."""
    try:
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                await asyncio.wait_for(killer.wait(), 3)
            finally:
                if killer.returncode is None:
                    killer.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, asyncio.TimeoutError):
        pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await asyncio.wait_for(proc.wait(), 3)
    except asyncio.TimeoutError:
        # An inherited pipe must not block the execution queue indefinitely.
        pass


@tool
async def execute(command: str, timeout: int = 60) -> str:
    """Execute a shell command and return its output.

    Supports pipes, redirects, and all shell operators.

    Args:
        command: Shell command to run
        timeout: Max seconds to wait, integer 1–1800 (default: 60).
            Combined stdout/stderr is limited to 256 KiB; overflow stops the command.
    """
    proc = None
    try:
        if type(timeout) is not int or not 1 <= timeout <= _MAX_TIMEOUT_SECONDS:
            return "Error: timeout must be an integer between 1 and 1800 seconds"
        if not command.strip():
            return "Error: empty command"
        process_options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                           if os.name == "nt" else {"start_new_session": True})
        if _needs_shell(command):
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **process_options,
            )
        else:
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **process_options,
            )
        stdout, stderr = await _communicate_bounded(proc, timeout)
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        parts = []
        if proc.returncode:
            parts.append(f"Error: command exited with code {proc.returncode}")
        if out:
            parts.append(out)
        if err:
            parts.append(f"[stderr]\n{err}")
        if not parts:
            parts.append(f"(exit {proc.returncode})")
        return "\n".join(parts)
    except asyncio.TimeoutError:
        return f"Error: timed out after {timeout}s"
    except _OutputLimitExceeded:
        return f"Error: output exceeded {_MAX_OUTPUT_BYTES} bytes; command stopped. Narrow the command's output before retrying."
    except Exception as e:
        return f"Error: {e}"
