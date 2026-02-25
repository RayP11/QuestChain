"""Claude Code tool for QuestChain — delegates coding tasks to Claude Code CLI."""

import asyncio
import json
import shutil
from typing import Literal

from langchain_core.tools import tool

from questchain.config import WORKSPACE_DIR

# Complexity → model + timeout mapping
_COMPLEXITY_CONFIG = {
    "simple":  {"model": "haiku",  "timeout": 300},   # 5 min
    "medium":  {"model": "sonnet", "timeout": 600},   # 10 min
    "complex": {"model": "sonnet", "timeout": 900},   # 15 min
}

# Mode → permission flags mapping
_MODE_CONFIG = {
    "code": {
        "permission_mode": "acceptEdits",
        "allowed_tools": None,
    },
    "review": {
        "permission_mode": "plan",
        "allowed_tools": "Read,Glob,Grep,Bash(git:*)",
    },
}

_APPEND_SYSTEM = (
    "You are working inside the QuestChain project at {cwd}. "
    "This is a Python project using uv, LangGraph Deep Agents, and Ollama."
)


@tool
async def claude_code(
    task: str,
    complexity: Literal["simple", "medium", "complex"] = "medium",
    mode: Literal["code", "review"] = "code",
    context: str = "",
) -> str:
    """Delegate a coding task to Claude Code (Anthropic's AI coding agent).

    Use this for writing code, debugging, refactoring, creating files,
    reviewing code, or any programming task. Claude Code operates directly
    on the filesystem and returns its result.

    WHEN TO USE:
    - Writing new code, scripts, or files
    - Debugging or fixing bugs in existing code
    - Refactoring or improving code quality
    - Code review and analysis
    - Any task that involves reading, writing, or editing source code

    Args:
        task: The coding task or prompt to send to Claude Code. Be specific
              about what to build/change, which files are involved, and any
              constraints.
        complexity: Controls which Claude model and timeout to use.
            - "simple": Fast model (Haiku), 5min timeout. Use for explanations,
              small edits, quick questions about code.
            - "medium": Capable model (Sonnet), 10min timeout. Use for most
              coding tasks, bug fixes, new features. (default)
            - "complex": Capable model (Sonnet), 15min timeout. Use for large
              refactors, multi-file changes, complex implementations.
        mode: Controls what Claude Code is allowed to do.
            - "code": Can read AND write/edit files. Use when you need code
              changes made. (default)
            - "review": Read-only access. Use for code review, analysis, or
              when you only need information about the codebase.
        context: Optional additional project context to include with the task.
            Use this to pass relevant information from the conversation that
            Claude Code might need (e.g. error messages, user requirements,
            file paths mentioned earlier).
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return "Error: 'claude' CLI not found on PATH. Is Claude Code installed?"

    cwd = str(WORKSPACE_DIR)

    # Build structured prompt
    prompt_parts = [f"## Task\n{task}"]
    if context:
        prompt_parts.append(f"## Context\n{context}")
    structured_prompt = "\n\n".join(prompt_parts)

    # Resolve complexity config
    comp_cfg = _COMPLEXITY_CONFIG[complexity]
    timeout = comp_cfg["timeout"]
    model = comp_cfg["model"]

    # Resolve mode config
    mode_cfg = _MODE_CONFIG[mode]

    # Build command
    cmd = [
        claude_bin,
        "-p", structured_prompt,
        "--output-format", "json",
        "--model", model,
        "--permission-mode", mode_cfg["permission_mode"],
        "--append-system-prompt", _APPEND_SYSTEM.format(cwd=cwd),
    ]

    if mode_cfg["allowed_tools"]:
        cmd.extend(["--allowedTools", mode_cfg["allowed_tools"]])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return f"Error: Claude Code timed out after {timeout // 60} minutes."
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
