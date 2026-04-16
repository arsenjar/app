"""
Shared SQLite layer — used by both bot.py and server.py.
Tasks are stored once; both the Telegram bot and the Mini App operate on the same rows.
"""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", "tasks.db")
_lock = threading.Lock()


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with _lock, conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                text       TEXT    NOT NULL,
                type       TEXT    NOT NULL DEFAULT 'task',   -- task | deadline | meeting
                due_at     TEXT,                               -- ISO 'YYYY-MM-DDTHH:MM'
                duration   INTEGER DEFAULT 0,                  -- minutes, for meetings
                done       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    NOT NULL DEFAULT (datetime('now')),
                reminded   INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due  ON tasks(due_at)")


# ── CRUD ───────────────────────────────────────────────────────────────────

def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["done"] = bool(d["done"])
    return d


def list_tasks(user_id: int) -> list[dict]:
    """All tasks for a user, ordered: undone first, then by due_at."""
    with conn() as c:
        rows = c.execute(
            """SELECT * FROM tasks WHERE user_id=?
               ORDER BY done ASC,
                        CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
                        due_at ASC,
                        id DESC""",
            (user_id,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_task(
    user_id: int,
    text: str,
    task_type: str = "task",
    due_at: str | None = None,
    duration: int = 0,
) -> dict:
    if task_type not in ("task", "deadline", "meeting"):
        task_type = "task"
    with _lock, conn() as c:
        cur = c.execute(
            "INSERT INTO tasks (user_id, text, type, due_at, duration) VALUES (?,?,?,?,?)",
            (user_id, text.strip(), task_type, due_at, duration),
        )
        task_id = cur.lastrowid
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_dict(row)


def update_task(user_id: int, task_id: int, **fields) -> dict | None:
    allowed = {"text", "type", "due_at", "duration", "done"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_task(user_id, task_id)
    cols = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [task_id, user_id]
    with _lock, conn() as c:
        cur = c.execute(f"UPDATE tasks SET {cols} WHERE id=? AND user_id=?", vals)
        if cur.rowcount == 0:
            return None
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_dict(row)


def get_task(user_id: int, task_id: int) -> dict | None:
    with conn() as c:
        r = c.execute(
            "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone()
    return _row_to_dict(r) if r else None


def delete_task(user_id: int, task_id: int) -> bool:
    with _lock, conn() as c:
        cur = c.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
    return cur.rowcount > 0


# ── Reminder helpers (used by bot's background job) ───────────────────────

def due_within(minutes: int = 30) -> list[dict]:
    now = datetime.now()
    soon = now + timedelta(minutes=minutes)
    with conn() as c:
        rows = c.execute(
            """SELECT * FROM tasks
               WHERE done=0 AND reminded=0 AND due_at IS NOT NULL
                 AND due_at BETWEEN ? AND ?""",
            (now.strftime("%Y-%m-%dT%H:%M"), soon.strftime("%Y-%m-%dT%H:%M")),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_reminded(task_id: int):
    with _lock, conn() as c:
        c.execute("UPDATE tasks SET reminded=1 WHERE id=?", (task_id,))
