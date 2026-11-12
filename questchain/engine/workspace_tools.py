"""Workspace tool loader — discovers and loads agent-authored tools from workspace/tools/."""

from __future__ import annotations

import ast
from collections import Counter
import importlib.util
import logging
from pathlib import Path

from questchain.engine.tools import ToolDef

logger = logging.getLogger(__name__)

# Built-in tool names that workspace tools must not shadow.
RESERVED_NAMES: frozenset[str] = frozenset({
    "read_file", "write_file", "edit_file", "delete_file", "ls", "glob", "grep",
    "delegate_to_agent", "route_to_agent",
    "shell", "execute", "web_search", "web_browse", "claude_code", "speak", "cron",
    "cron_add", "cron_list", "cron_remove", "write_todos", "read_todos",
})


def _tools_dir(workspace_dir: Path) -> Path:
    return workspace_dir / "workspace" / "tools"


def _scan_modules(workspace_dir: Path) -> list[tuple[Path, str, list[tuple[str, str]]]]:
    """Read source and static top-level declarations without executing code."""
    modules = []
    for path in sorted(_tools_dir(workspace_dir).glob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeError, SyntaxError, RecursionError):
            continue
        entries = []
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if not ((isinstance(target, ast.Name) and target.id == "tool")
                        or (isinstance(target, ast.Attribute) and target.attr == "tool")):
                    continue
                name = node.name
                if isinstance(dec, ast.Call):
                    # Dynamic names/arguments require executing code to resolve.
                    # Do not import a module to discover whether it was selected.
                    if dec.args or any(k.arg is None for k in dec.keywords):
                        continue
                    names = [k.value for k in dec.keywords if k.arg == "name"]
                    if names:
                        if not isinstance(names[0], ast.Constant) or not isinstance(names[0].value, str):
                            continue
                        name = names[0].value or node.name
                if name not in RESERVED_NAMES:
                    desc = (ast.get_docstring(node) or "").split("\n")[0] or f"Workspace tool: {name}"
                    entries.append((name, desc))
                break
        modules.append((path, source, entries))
    return modules


def get_tool_entries(workspace_dir: Path) -> list[tuple[str, str]]:
    """List unambiguous statically declared tools without importing Python."""
    entries = [entry for _, _, declared in _scan_modules(workspace_dir) for entry in declared]
    counts = Counter(name for name, _ in entries)
    return [entry for entry in entries if counts[entry[0]] == 1]


def load_workspace_tools(workspace_dir: Path, tools_filter: list[str]) -> list[ToolDef]:
    """Import workspace tool files and return ToolDefs for tools in tools_filter.

    Errors per-file are caught and logged — a broken file never crashes the agent.
    Only called when an agent has an explicit tools list (never for tools_filter=None).
    """
    selected = set(tools_filter) - RESERVED_NAMES
    if not selected:
        return []
    modules = _scan_modules(workspace_dir)
    counts = Counter(name for _, _, entries in modules for name, _ in entries)
    selected = {name for name in selected if counts[name] == 1}
    loaded: list[ToolDef] = []
    for path, source, entries in modules:
        declared = {name for name, _ in entries} & selected
        if not declared:
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"_ws_tool_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            logger.warning(
                "Loading workspace tool %s — this executes untrusted Python code. "
                "Only enable tools you have reviewed.",
                path.name,
            )
            # Execute the same source that passed selection, without a second
            # read or stale bytecode cache changing which module gets imported.
            exec(compile(source, str(path), "exec"), mod.__dict__)
        except Exception as e:
            logger.warning("Failed to load workspace tool %s: %s", path.name, e)
            continue
        for attr in vars(mod).values():
            td = getattr(attr, "_tool_def", None)
            if not isinstance(td, ToolDef):
                continue
            if td.name in RESERVED_NAMES:
                logger.error(
                    "Workspace tool file %s defines %r which conflicts with a built-in "
                    "tool name — skipped. Rename the function to load it.",
                    path.name, td.name,
                )
                continue
            if td.name in declared and not any(item.name == td.name for item in loaded):
                loaded.append(td)
    return loaded
