"""Persistent memory and checkpointing for Genie."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import msgpack
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore

from genie.config import get_db_path

_INTERNAL_PREFIXES = ("busy_work", "onboarding", "cron:")


def _decode_first_human_message(cp_blob: bytes) -> str | None:
    """Extract the first human message content from a msgpack checkpoint blob."""
    try:
        data = msgpack.unpackb(cp_blob, raw=False)
        msgs = data.get("channel_values", {}).get("messages", [])
        if not isinstance(msgs, list):
            return None
        for m in msgs:
            if isinstance(m, msgpack.ext.ExtType):
                inner = msgpack.unpackb(m.data, raw=False)
                if isinstance(inner, list) and len(inner) >= 3 and "human" in str(inner[0]):
                    content = inner[2].get("content", "") if isinstance(inner[2], dict) else ""
                    if content:
                        return content
    except Exception:
        pass
    return None


def _decode_ts(cp_blob: bytes) -> str | None:
    """Extract the ISO timestamp from a msgpack checkpoint blob."""
    try:
        data = msgpack.unpackb(cp_blob, raw=False)
        return data.get("ts")
    except Exception:
        return None


def get_thread_history(db_path: Path | None = None, limit: int = 50) -> list[dict]:
    """Return past conversation threads with timestamps and first-message previews.

    Each entry is a dict with keys:
        thread_id   – full thread UUID string
        last_active – datetime of last checkpoint (UTC-aware), or None
        first_message – first human message text, or None
    Threads are sorted newest-first.  Internal threads (busy_work, onboarding,
    cron) are excluded.
    """
    db_path = db_path or get_db_path()
    if not db_path.exists():
        return []

    results: list[dict] = []
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT thread_id, MIN(checkpoint_id) AS first_cp, MAX(checkpoint_id) AS last_cp
            FROM checkpoints
            GROUP BY thread_id
            ORDER BY last_cp DESC
        """)
        threads = cur.fetchall()

        for tid, first_cp, last_cp in threads:
            if any(tid.startswith(p) for p in _INTERNAL_PREFIXES):
                continue

            # Last active timestamp from the latest checkpoint
            last_active: datetime | None = None
            cur.execute(
                "SELECT checkpoint FROM checkpoints WHERE thread_id = ? AND checkpoint_id = ?",
                (tid, last_cp),
            )
            row = cur.fetchone()
            if row:
                ts_str = _decode_ts(row[0])
                if ts_str:
                    try:
                        last_active = datetime.fromisoformat(ts_str)
                    except ValueError:
                        pass

            # First human message from the earliest checkpoints
            first_msg: str | None = None
            cur.execute(
                "SELECT checkpoint FROM checkpoints WHERE thread_id = ? ORDER BY checkpoint_id ASC LIMIT 15",
                (tid,),
            )
            for (blob,) in cur.fetchall():
                first_msg = _decode_first_human_message(blob)
                if first_msg:
                    break

            results.append({"thread_id": tid, "last_active": last_active, "first_message": first_msg})
            if len(results) >= limit:
                break
    finally:
        con.close()

    return results


def create_checkpointer(db_path: Path | None = None) -> AsyncSqliteSaver:
    """Create a SQLite checkpointer for conversation persistence.

    Args:
        db_path: Path to the SQLite database. Defaults to ~/.genie/checkpoints.db.

    Returns:
        Configured AsyncSqliteSaver instance.
    """
    db_path = db_path or get_db_path()
    return AsyncSqliteSaver.from_conn_string(str(db_path))


def create_memory_store() -> InMemoryStore:
    """Create a memory store for long-term agent memory.

    Returns:
        Configured InMemoryStore instance.
    """
    return InMemoryStore()
