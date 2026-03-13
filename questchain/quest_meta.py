"""Helpers for quest file frontmatter (YAML-style header block).

Quest files can optionally begin with:

    ---
    agent: <agent_id>
    ---
    # Quest Title

    Quest body…

If no frontmatter is present the entire file is treated as the body
and meta is returned as an empty dict.
"""

from __future__ import annotations

from pathlib import Path


def parse_quest(path: Path) -> tuple[dict, str]:
    """Read *path* and return ``(meta, body)``.

    *meta* — dict with any recognised keys (currently only ``agent``).
    *body* — quest content with frontmatter stripped.
    """
    content = path.read_text(encoding="utf-8")
    return parse_quest_content(content)


def parse_quest_content(content: str) -> tuple[dict, str]:
    """Parse frontmatter from a raw string, returning ``(meta, body)``."""
    meta: dict = {}
    if not content.startswith("---"):
        return meta, content

    end = content.find("\n---", 3)
    if end == -1:
        return meta, content

    block = content[3:end].strip()
    for line in block.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip()

    body = content[end + 4:].lstrip("\n")
    return meta, body


def render_quest(meta: dict, body: str) -> str:
    """Serialise *meta* + *body* to a quest file string.

    If *meta* is empty the body is returned unchanged (no frontmatter block).
    """
    if not meta:
        return body
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + body
