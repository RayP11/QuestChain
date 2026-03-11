"""Built-in shell execution tool."""

from __future__ import annotations

import asyncio
import shlex

from questchain.engine.tools import tool


@tool
async def execute(command: str, timeout: int = 60) -> str:
    """Execute a shell command and return its output.

    Commands are run without a shell interpreter (safer). For pipelines or
    redirects, prefix with the shell explicitly: execute("bash -c 'ls | grep .py'")

    Args:
        command: Shell command to run
        timeout: Max seconds to wait (default: 60)
    """
    try:
        args = shlex.split(command)
        if not args:
            return "Error: empty command"
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
