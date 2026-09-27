"""Durable run records and conversation-scoped event replay."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class RunStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = path.with_suffix(".lock").open("a+b")
        try:
            self._lock.seek(0)
            if not self._lock.read(1):
                self._lock.write(b"0")
                self._lock.flush()
            self._lock.seek(0)
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.close()
            raise RuntimeError("QuestChain is already running against this data directory.") from None
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                parent_run_id TEXT, occurrence_key TEXT UNIQUE, record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS runs_conversation ON runs(conversation_id);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
                record TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_conversation ON events(conversation_id, seq);
            PRAGMA user_version=1;
        """)

    def put(self, run: dict) -> None:
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET record=excluded.record",
                            (run["id"], run["conversation_id"], run.get("parent_run_id"),
                             run.get("occurrence_key"), json.dumps(run)))

    def get(self, run_id: str) -> dict:
        row = self.db.execute("SELECT record FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Run not found.")
        return json.loads(row[0])

    def occurrence(self, key: str) -> dict | None:
        row = self.db.execute("SELECT record FROM runs WHERE occurrence_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def runs(self, conversation_id: str | None = None) -> list[dict]:
        rows = (self.db.execute("SELECT record FROM runs WHERE conversation_id=? ORDER BY rowid", (conversation_id,))
                if conversation_id else self.db.execute("SELECT record FROM runs ORDER BY rowid"))
        return [json.loads(r[0]) for r in rows]

    def event(self, event: dict) -> dict:
        with self.db:
            cursor = self.db.execute("INSERT INTO events(conversation_id,record) VALUES (?,?)",
                                     (event["conversation_id"], json.dumps(event)))
        return {**event, "seq": cursor.lastrowid}

    def events(self, conversation_id: str, after: int = 0) -> list[dict]:
        return [{**json.loads(row[1]), "seq": row[0]} for row in self.db.execute(
            "SELECT seq,record FROM events WHERE conversation_id=? AND seq>? ORDER BY seq LIMIT 2000",
            (conversation_id, after))]

    def snapshot(self, conversation_id: str) -> dict:
        seq = self.db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
        return {"conversation_id": conversation_id, "runs": self.runs(conversation_id), "seq": seq}

    def close(self) -> None:
        self.db.close()
        self._lock.close()
