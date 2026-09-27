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
        timeout: Max seconds to wait (default: 60)
    """
    proc = None
    finished = False
    try:
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
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        finished = True
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
    except Exception as e:
        return f"Error: {e}"
    finally:
        if proc is not None and not finished:
            await _stop_process_tree(proc)
