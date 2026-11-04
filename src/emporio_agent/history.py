"""Persistent conversation history (SQLite, standard library only).

One row per conversation and one per turn. A turn stores what the user saw (text + which tools were called) and the
exact messages the agent appended to its context (including tool calls/results), so a conversation can be resumed and
the model continues with the same context. API keys are never stored.

Privacy note: conversations may contain personal data (e-mail, phone, order details). The file lives in ``logs/``
(git-ignored), can be disabled with ``SAVE_HISTORY=0`` and every conversation can be deleted.
"""
import json
import os
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .agent import Reply, ToolTrace
from .config import LOGS_DIR, TIMEZONE

DB_PATH = LOGS_DIR / "conversations.db"
TITLE_MAX = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, provider TEXT, model TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, user_text TEXT NOT NULL, reply_text TEXT NOT NULL,
    tools TEXT NOT NULL, messages TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_turns_conv ON turns(conversation_id, seq);
"""


def history_enabled() -> bool:
    return os.getenv("SAVE_HISTORY", "1").strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class StoredTurn:
    user: str
    reply: str
    tools: list[ToolTrace]
    messages: list[dict] = field(default_factory=list)


@dataclass
class ConversationInfo:
    id: str
    title: str
    updated_at: str
    turns: int

    @property
    def when(self) -> str:
        return datetime.fromisoformat(self.updated_at).strftime("%d/%m %H:%M")


def _stamp() -> str:
    # real wall-clock time on purpose: the log records when things actually happened (not the pinned demo clock)
    return datetime.now(TIMEZONE).isoformat(timespec="microseconds")


class ConversationStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or os.getenv("HISTORY_DB") or DB_PATH)  # HISTORY_DB lets tests/ops relocate the file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self):
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA foreign_keys = ON")
        return _Connection(con)

    def create(self, provider: str = "", model: str = "") -> str:
        conv_id = uuid.uuid4().hex
        with self._db() as db:
            db.execute("INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
                       (conv_id, "Nova conversa", provider, model, _stamp(), _stamp()))
        return conv_id

    def add_turn(self, conv_id: str, user: str, reply: Reply) -> None:
        with self._db() as db:
            seq = db.execute("SELECT COUNT(*) FROM turns WHERE conversation_id = ?", (conv_id,)).fetchone()[0]
            db.execute("INSERT INTO turns (conversation_id, seq, user_text, reply_text, tools, messages, created_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (conv_id, seq, user, reply.text,
                        json.dumps([{"name": t.name, "arguments": t.arguments} for t in reply.tool_calls],
                                   ensure_ascii=False),
                        json.dumps(reply.messages, ensure_ascii=False, default=str), _stamp()))
            if seq == 0:
                title = " ".join(user.split())
                title = title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 1].rstrip() + "…"
                db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id))
            db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (_stamp(), conv_id))

    def recent(self, limit: int = 30) -> list[ConversationInfo]:
        with self._db() as db:
            rows = db.execute(
                "SELECT c.id, c.title, c.updated_at, COUNT(t.id) FROM conversations c "
                "JOIN turns t ON t.conversation_id = c.id GROUP BY c.id ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ?",
                (limit,)).fetchall()
        return [ConversationInfo(*r) for r in rows]

    def load(self, conv_id: str) -> list[StoredTurn]:
        with self._db() as db:
            rows = db.execute("SELECT user_text, reply_text, tools, messages FROM turns "
                              "WHERE conversation_id = ? ORDER BY seq", (conv_id,)).fetchall()
        return [StoredTurn(u, r, [ToolTrace(t["name"], t["arguments"], "") for t in json.loads(tools)],
                           json.loads(msgs)) for u, r, tools, msgs in rows]

    def delete(self, conv_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))


class _Connection:
    """sqlite3 connection as a context manager that commits AND closes (the stdlib one only commits)."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def __enter__(self) -> sqlite3.Connection:
        return self.con

    def __exit__(self, exc_type, *_):
        with closing(self.con):
            self.con.commit() if exc_type is None else self.con.rollback()
