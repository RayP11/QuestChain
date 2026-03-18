"""Helpers for quest file frontmatter (YAML-style header block).

Quest files can optionally begin with:

    ---
    agent: <agent_id>
    cron: 0 9 * * 1
    last_run: 2026-03-10T09:00:00+00:00
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

    *meta* — dict with any recognised keys (``agent``, ``cron``, ``last_run``).
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


def is_cron_quest(path: Path) -> bool:
    """Return True if the quest file has a ``cron:`` key in its frontmatter."""
    try:
        meta, _ = parse_quest(path)
        return bool(meta.get("cron", "").strip())
    except Exception:
        return False


def cron_is_due(path: Path) -> bool:
    """Return True if the cron quest at *path* is due to run now.

    Uses ``croniter`` to compute the next scheduled time after ``last_run``
    (or the epoch if never run).  Returns True if that time is ≤ now.
    """
    try:
        from croniter import croniter
        from datetime import datetime, timezone

        meta, _ = parse_quest(path)
        expr = meta.get("cron", "").strip()
        if not expr:
            return False

        last_run_str = meta.get("last_run", "").strip()
        if last_run_str:
            try:
                base = datetime.fromisoformat(last_run_str)
                if base.tzinfo is None:
                    base = base.replace(tzinfo=timezone.utc)
            except ValueError:
                base = datetime(1970, 1, 1, tzinfo=timezone.utc)
        else:
            base = datetime(1970, 1, 1, tzinfo=timezone.utc)

        it = croniter(expr, base)
        next_run = it.get_next(datetime)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)
        return next_run <= datetime.now(timezone.utc)
    except Exception:
        return False


def update_last_run(path: Path) -> None:
    """Rewrite the quest file with ``last_run`` set to the current UTC time."""
    from datetime import datetime, timezone
    meta, body = parse_quest(path)
    meta["last_run"] = datetime.now(timezone.utc).isoformat()
    path.write_text(render_quest(meta, body), encoding="utf-8")
