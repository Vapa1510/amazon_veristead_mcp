"""Persistent cross-session household memory (Capability Charter, Pillar 5).

Backed by a local SQLite file so state survives server restarts, storing
household layout and preferences across sessions.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "memory.db"


@contextmanager
def _connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


MAX_MEMORY_ENTRIES = 100


def remember(topic: str, detail: str) -> dict:
    """Write one fact/detail under a topic (e.g. a room, a device nickname).

    Called automatically by device tools so household context builds up
    with no explicit "remember this" step required from the user.
    Enforces MAX_MEMORY_ENTRIES limit to prevent unbounded memory growth.
    """
    entry = {
        "topic": topic.strip().lower(),
        "detail": detail,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _connection() as conn:
        conn.execute(
            "INSERT INTO memory (topic, detail, created_at) VALUES (?, ?, ?)",
            (entry["topic"], entry["detail"], entry["created_at"]),
        )
        conn.execute(
            """
            DELETE FROM memory WHERE id NOT IN (
                SELECT id FROM memory ORDER BY created_at DESC LIMIT ?
            )
            """,
            (MAX_MEMORY_ENTRIES,),
        )
    return entry


def recall_context_impl(topic: str | None = None, limit: int = 10) -> list[dict]:
    """Return recent memory entries, optionally filtered to one topic."""
    limit = max(1, min(limit, 50))
    with _connection() as conn:
        if topic:
            rows = conn.execute(
                "SELECT topic, detail, created_at FROM memory "
                "WHERE topic LIKE ? ORDER BY created_at DESC LIMIT ?",
                (f"%{topic.strip().lower()}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT topic, detail, created_at FROM memory "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def recall_recent(limit: int = 10) -> list[dict]:
    """Helper to recall recent memory entries across all topics."""
    return recall_context_impl(topic=None, limit=limit)


def view_memory_impl() -> list[dict]:
    """Full transparency dump of everything currently remembered about the household."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT topic, detail, created_at FROM memory ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def forget_topic_impl(topic: str) -> dict:
    """Delete every memory entry under a topic. Returns how many were removed."""
    normalized = topic.strip().lower()
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM memory WHERE topic = ?", (normalized,))
        deleted = cursor.rowcount
    return {"topic": normalized, "deleted": deleted}
