"""Persistent memory and checkpointing for Genie."""

from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.memory import InMemoryStore

from genie.config import get_db_path


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
