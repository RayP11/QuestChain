"""Built-in filesystem tools: read, write, edit, ls, glob, grep."""

from __future__ import annotations

import re as _re
from pathlib import Path

from questchain.config import WORKSPACE_DIR
from questchain.engine.tools import tool

_ROOT = WORKSPACE_DIR


def _resolve(virtual_path: str) -> Path:
    """Map a virtual /path to a real filesystem path under WORKSPACE_DIR."""
    rel = virtual_path.lstrip("/")
    return (_ROOT / rel).resolve()


@tool
def read_file(path: str) -> str:
    """Read a file from the filesystem.

    Args:
        path: Virtual file path starting with / (e.g. /workspace/memory/ABOUT.md)
    """
    real = _resolve(path)
    if not real.exists():
        return f"Error: file not found: {path}"
    try:
        return real.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading {path}: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed.

    Args:
        path: Virtual file path starting with /
        content: Content to write
    """
    real = _resolve(path)
    try:
        real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


@tool
def edit_file(path: str, old_str: str, new_str: str) -> str:
    """Replace the first occurrence of a string in a file.

    Args:
        path: Virtual file path starting with /
        old_str: Exact string to find and replace
        new_str: Replacement string
    """
    real = _resolve(path)
    if not real.exists():
        return f"Error: file not found: {path}"
    try:
        text = real.read_text(encoding="utf-8")
        if old_str not in text:
            return f"Error: string not found in {path}"
        real.write_text(text.replace(old_str, new_str, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error editing {path}: {e}"


@tool
def ls(path: str = "/workspace") -> str:
    """List files and directories at a path.

    Args:
        path: Virtual directory path to list (default: /workspace)
    """
    real = _resolve(path)
    if not real.exists():
        return f"Error: path not found: {path}"
    if not real.is_dir():
        return f"Error: not a directory: {path}"
    try:
        entries = sorted(real.iterdir(), key=lambda p: (p.is_file(), p.name))
        lines = [f"{e.name}/" if e.is_dir() else e.name for e in entries]
        return "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return f"Error listing {path}: {e}"


@tool
def glob(pattern: str) -> str:
    """Find files matching a glob pattern within the workspace.

    Args:
        pattern: Glob pattern (e.g. **/*.py or memory/*.md)
    """
    try:
        matches = list(_ROOT.glob(pattern))
        if not matches:
            return "No matches found."
        lines = []
        for m in sorted(matches)[:100]:
            try:
                lines.append(f"/{m.relative_to(_ROOT)}")
            except ValueError:
                lines.append(str(m))
        result = "\n".join(lines)
        if len(matches) > 100:
            result += f"\n… ({len(matches) - 100} more)"
        return result
    except Exception as e:
        return f"Error: {e}"


@tool
def grep(pattern: str, path: str = "/workspace", file_glob: str = "**/*") -> str:
    """Search for a regex pattern across files.

    Args:
        pattern: Regex pattern to search for
        path: Virtual directory to search in (default: /workspace)
        file_glob: Glob pattern for files to include (default: **/* = all files)
    """
    real = _resolve(path)
    try:
        regex = _re.compile(pattern, _re.IGNORECASE)
    except _re.error as e:
        return f"Invalid regex: {e}"

    results: list[str] = []
    try:
        for filepath in real.glob(file_glob):
            if not filepath.is_file():
                continue
            try:
                for i, line in enumerate(
                    filepath.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
                ):
                    if regex.search(line):
                        try:
                            vpath = f"/{filepath.relative_to(_ROOT)}"
                        except ValueError:
                            vpath = str(filepath)
                        results.append(f"{vpath}:{i}: {line.strip()}")
                        if len(results) >= 100:
                            break
            except Exception:
                continue
            if len(results) >= 100:
                break
    except Exception as e:
        return f"Error: {e}"

    return "\n".join(results) if results else "No matches found."
