"""Workspace tool loader — discovers and loads agent-authored tools from workspace/tools/."""

from __future__ import annotations

import ast
import importlib.util
import logging
from pathlib import Path

from questchain.engine.tools import ToolDef

logger = logging.getLogger(__name__)

# Built-in tool names that workspace tools must not shadow.
RESERVED_NAMES: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "ls", "glob", "grep",
    "shell", "web_search", "web_browse", "claude_code", "speak", "cron",
})


def _tools_dir(workspace_dir: Path) -> Path:
    return workspace_dir / "workspace" / "tools"


def get_tool_entries(workspace_dir: Path) -> list[tuple[str, str]]:
    """Scan workspace/tools/*.py with AST and return (name, description) pairs.

    Never imports the files — safe to call even if tool code is broken.
    """
    d = _tools_dir(workspace_dir)
    if not d.exists():
        return []

    entries: list[tuple[str, str]] = []
    for path in sorted(d.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                is_tool = (
                    (isinstance(dec, ast.Name) and dec.id == "tool")
                    or (isinstance(dec, ast.Attribute) and dec.attr == "tool")
                )
                if is_tool:
                    name = node.name
                    raw_doc = ast.get_docstring(node) or ""
                    desc = raw_doc.split("\n")[0] or f"Workspace tool: {name}"
                    entries.append((name, desc))
                    break
    return entries


def load_workspace_tools(workspace_dir: Path, tools_filter: list[str]) -> list[ToolDef]:
    """Import workspace tool files and return ToolDefs for tools in tools_filter.

    Errors per-file are caught and logged — a broken file never crashes the agent.
    Only called when an agent has an explicit tools list (never for tools_filter=None).
    """
    d = _tools_dir(workspace_dir)
    if not d.exists():
        return []

    loaded: list[ToolDef] = []
    for path in sorted(d.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"_ws_tool_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            logger.warning(
                "Loading workspace tool %s — this executes untrusted Python code. "
                "Only enable tools you have reviewed.",
                path.name,
            )
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("Failed to load workspace tool %s: %s", path.name, e)
            continue
        for attr in vars(mod).values():
            if not hasattr(attr, "_tool_def"):
                continue
            td: ToolDef = attr._tool_def
            if td.name in RESERVED_NAMES:
                logger.error(
                    "Workspace tool file %s defines %r which conflicts with a built-in "
                    "tool name — skipped. Rename the function to load it.",
                    path.name, td.name,
                )
                continue
            if td.name in tools_filter:
                loaded.append(td)
    return loaded
