"""Built-in planning tools (task list)."""

from __future__ import annotations

from questchain.config import WORKSPACE_DIR
from questchain.engine.tools import tool

_TASKS_PATH = WORKSPACE_DIR / "workspace" / "TASKS.md"


@tool
def write_todos(todos: str) -> str:
    """Write or update the task list.

    Args:
        todos: Markdown task list (use - [ ] for pending, - [x] for done)
    """
    _TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TASKS_PATH.write_text(todos, encoding="utf-8")
    return "Task list updated."


@tool
def read_todos() -> str:
    """Read the current task list."""
    if not _TASKS_PATH.exists():
        return "No task list found."
    return _TASKS_PATH.read_text(encoding="utf-8")
