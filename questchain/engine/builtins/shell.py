"""Built-in shell execution tool."""

from __future__ import annotations

import asyncio

from questchain.engine.tools import tool


@tool
async def execute(command: str, timeout: int = 60) -> str:
    """Execute a shell command and return its output.

    Args:
        command: Shell command to run
        timeout: Max seconds to wait (default: 60)
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
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
