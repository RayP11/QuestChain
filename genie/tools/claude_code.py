"""Claude Code tool for Genie — delegates coding tasks to Claude Code CLI."""

import asyncio
import json
import shutil

from langchain_core.tools import tool

from genie.config import WORKSPACE_DIR

_TIMEOUT = 900  # 15 minutes


@tool
async def claude_code(task: str) -> str:
    """Delegate a coding task to Claude Code (Anthropic's AI coding agent).

    Use this for writing code, debugging, refactoring, creating files,
    or any programming task. Claude Code will operate on the filesystem
    and return its result.

    Args:
        task: The coding task or prompt to send to Claude Code.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return "Error: 'claude' CLI not found on PATH. Is Claude Code installed?"

    cwd = str(WORKSPACE_DIR)

    cmd = [
        claude_bin,
        "-p", task,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--max-budget-usd", "0.50",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        return "Error: Claude Code timed out after 15 minutes."
    except Exception as e:
        return f"Error running Claude Code: {e}"

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        return f"Claude Code exited with code {proc.returncode}: {err}"

    raw = stdout.decode(errors="replace").strip()

    # Parse JSON output to extract the result text
    try:
        data = json.loads(raw)
        result = data.get("result", raw)
        cost = data.get("cost_usd")
        suffix = f"\n\n[Cost: ${cost:.4f}]" if cost else ""
        return result + suffix
    except (json.JSONDecodeError, TypeError):
        # Fall back to raw output if JSON parsing fails
        return raw


def create_claude_code_tool():
    """Return the Claude Code tool."""
    return claude_code
