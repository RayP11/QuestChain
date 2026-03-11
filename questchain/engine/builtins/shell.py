"""Built-in shell execution tool."""

from __future__ import annotations

import asyncio
import shlex

from questchain.engine.tools import tool

# Shell metacharacters that require a shell interpreter
_SHELL_CHARS = frozenset('|&;<>(){}$`!')


def _needs_shell(command: str) -> bool:
    """Return True if the command contains shell metacharacters."""
    return any(c in _SHELL_CHARS for c in command) or '>>' in command


@tool
async def execute(command: str, timeout: int = 60) -> str:
    """Execute a shell command and return its output.

    Supports pipes, redirects, and all shell operators.

    Args:
        command: Shell command to run
        timeout: Max seconds to wait (default: 60)
    """
    try:
        if not command.strip():
            return "Error: empty command"
        if _needs_shell(command):
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            args = shlex.split(command)
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()

        parts = []
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
