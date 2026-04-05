import sqlite3
import time
import logging
import os
import threading
from duckscreeener.config.settings import KNOWLEDGE_DB

logger = logging.getLogger(__name__)

_db_conn = None
_db_lock = threading.Lock()


def get_db():
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = sqlite3.connect(KNOWLEDGE_DB, check_same_thread=False)
            _db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            _db_conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    source, text
                )
                """
            )
            _db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            _db_conn.commit()
        return _db_conn


def load_knowledge():
    get_db()


def store_knowledge(source, text):
    db = get_db()
    db.execute(
        "INSERT INTO knowledge (source, text, timestamp) VALUES (?, ?, ?)",
        (source, text, time.time()),
    )
    db.execute(
        "INSERT INTO knowledge_fts (source, text) VALUES (?, ?)",
        (source, text),
    )
    db.commit()
    logger.info(f"Knowledge stored from {source} ({len(text)} chars)")


def search_knowledge(query, limit=5):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT source, text FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
        return [{'source': r[0], 'text': r[1]} for r in rows]
    except Exception as e:
        logger.error(f"FTS5 search failed: {e}")
        return []


def count_knowledge():
    db = get_db()
    row = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()
    return row[0] if row else 0


def get_recent_knowledge(limit=3):
    db = get_db()
    rows = db.execute(
        "SELECT source, text, timestamp FROM knowledge ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [{'source': r[0], 'text': r[1], 'timestamp': r[2]} for r in rows]


def get_all_knowledge_by_source_prefix(prefix):
    db = get_db()
    rows = db.execute(
        "SELECT id, source, text, timestamp FROM knowledge WHERE source LIKE ?",
        (f"{prefix}%",)
    ).fetchall()
    return [{'id': r[0], 'source': r[1], 'text': r[2], 'timestamp': r[3]} for r in rows]


def save_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    db.commit()


def load_setting(key, default=None):
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def load_list_setting(key, default=None):
    val = load_setting(key, None)
    if val is None:
        return default if default is not None else []
    return [x.strip() for x in val.split(",") if x.strip()]


def save_list_setting(key, lst):
    save_setting(key, ",".join(lst))
