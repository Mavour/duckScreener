import sqlite3
import time
import json
import logging
import threading
from datetime import datetime
from duckscreeener.config.settings import KNOWLEDGE_DB

logger = logging.getLogger(__name__)

_local = threading.local()
_schema_initialized = False
_schema_lock = threading.Lock()


def init_db():
    """Initialize database schema once at startup"""
    global _schema_initialized
    with _schema_lock:
        if _schema_initialized:
            return
        conn = sqlite3.connect(KNOWLEDGE_DB, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                source, text
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                token_address TEXT,
                source_type TEXT NOT NULL,
                entry_price REAL NOT NULL,
                signal_type TEXT,
                market_cap REAL,
                volume REAL,
                score INTEGER,
                narrative TEXT,
                analysis TEXT,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scan_signals_symbol ON scan_signals(symbol)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scan_signals_timestamp ON scan_signals(timestamp)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scan_signals_source_type ON scan_signals(source_type)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                exit_price REAL,
                change_pct REAL,
                result TEXT,
                checked_at REAL NOT NULL,
                FOREIGN KEY (signal_id) REFERENCES scan_signals(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                knowledge_id INTEGER PRIMARY KEY,
                embedding BLOB NOT NULL,
                FOREIGN KEY (knowledge_id) REFERENCES knowledge(id)
            )
            """
        )
        conn.commit()
        conn.close()
        _schema_initialized = True
        logger.info("Database schema initialized")


def get_db():
    """Get a thread-local database connection"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(KNOWLEDGE_DB, timeout=30)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def load_knowledge():
    init_db()


# ==================== Knowledge Base ====================

def store_knowledge(source, text):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO knowledge (source, text, timestamp) VALUES (?, ?, ?)",
        (source, text, time.time()),
    )
    db.execute(
        "INSERT INTO knowledge_fts (source, text) VALUES (?, ?)",
        (source, text),
    )
    db.commit()
    knowledge_id = cursor.lastrowid
    logger.info(f"Knowledge stored from {source} ({len(text)} chars) id={knowledge_id}")

    # Auto-generate embedding in background thread (non-blocking)
    if len(text) > 50:
        try:
            t = threading.Thread(
                target=_generate_embedding_async,
                args=(knowledge_id, text),
                daemon=True,
            )
            t.start()
        except Exception:
            pass


def _generate_embedding_async(knowledge_id, text):
    import time as time_module
    time_module.sleep(2)
    try:
        from duckscreeener.db.vector_search import store_embedding
        store_embedding(knowledge_id, text)
    except Exception:
        pass


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
    """Get recent knowledge entries, excluding scan signals"""
    db = get_db()
    rows = db.execute(
        """
        SELECT source, text, timestamp FROM knowledge
        WHERE source NOT LIKE 'scan:%'
          AND source NOT LIKE 'memecoin:%'
          AND source NOT LIKE 'gmgn:%'
          AND source NOT LIKE 'solana:%'
        ORDER BY id DESC LIMIT ?
        """, (limit,)
    ).fetchall()
    return [{'source': r[0], 'text': r[1], 'timestamp': r[2]} for r in rows]


def cleanup_old_scan_data():
    """Remove scan results and chat logs from knowledge table"""
    db = get_db()
    prefixes = ['scan:', 'memecoin:', 'gmgn:', 'solana:', 'user:']
    total_deleted = 0
    for prefix in prefixes:
        cursor = db.execute("DELETE FROM knowledge WHERE source LIKE ?", (f"{prefix}%",))
        total_deleted += cursor.rowcount
    db.commit()
    if total_deleted > 0:
        logger.info(f"Cleaned up {total_deleted} old entries from knowledge table")
    return total_deleted


def cleanup_old_signals(max_days=30):
    """Delete signals and outcomes older than max_days"""
    import time
    db = get_db()
    cutoff = time.time() - (max_days * 86400)
    # Delete outcomes first
    db.execute(
        "DELETE FROM signal_outcomes WHERE signal_id IN (SELECT id FROM scan_signals WHERE timestamp < ?)",
        (cutoff,)
    )
    cursor = db.execute("DELETE FROM scan_signals WHERE timestamp < ?", (cutoff,))
    db.commit()
    deleted = cursor.rowcount
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} signals older than {max_days} days")
    return deleted


def get_all_knowledge_by_source_prefix(prefix):
    db = get_db()
    rows = db.execute(
        "SELECT id, source, text, timestamp FROM knowledge WHERE source LIKE ?",
        (f"{prefix}%",)
    ).fetchall()
    return [{'id': r[0], 'source': r[1], 'text': r[2], 'timestamp': r[3]} for r in rows]


# ==================== Scan Signals (Structured) ====================

def store_signal(symbol, entry_price, source_type, signal_type=None,
                 token_address=None, market_cap=None, volume=None,
                 score=None, narrative=None, analysis=None):
    """Store a scan signal in structured format for backtesting.
    If symbol already exists, skip (keep original timestamp).
    """
    db = get_db()
    existing = db.execute(
        "SELECT id, timestamp FROM scan_signals WHERE symbol = ? AND source_type = ? ORDER BY timestamp ASC LIMIT 1",
        (symbol.upper(), source_type)
    ).fetchone()
    if existing:
        logger.info(f"Signal for {symbol} already exists (first scan: {datetime.fromtimestamp(existing[1]).strftime('%H:%M')}), skipping")
        return existing[0]

    ts = time.time()
    cursor = db.execute(
        """
        INSERT INTO scan_signals
            (symbol, token_address, source_type, entry_price, signal_type,
             market_cap, volume, score, narrative, analysis, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol.upper(),
            token_address,
            source_type,
            entry_price,
            signal_type,
            market_cap,
            volume,
            score,
            narrative,
            analysis,
            ts,
        )
    )
    db.commit()
    signal_id = cursor.lastrowid
    logger.info(
        f"Signal stored: {symbol} @ ${entry_price} ({source_type}/{signal_type}) id={signal_id}"
    )
    return signal_id


def get_first_scan_time(symbol, source_type):
    """Get the timestamp of the first scan for a symbol"""
    db = get_db()
    row = db.execute(
        "SELECT timestamp FROM scan_signals WHERE symbol = ? AND source_type = ? ORDER BY timestamp ASC LIMIT 1",
        (symbol.upper(), source_type)
    ).fetchone()
    if row:
        return datetime.fromtimestamp(row[0]).strftime("%H:%M")
    return datetime.now().strftime("%H:%M")


def get_signals(source_types=None, since=None, limit=100):
    """Get scan signals for backtesting"""
    db = get_db()
    query = "SELECT * FROM scan_signals WHERE 1=1"
    params = []

    if source_types:
        placeholders = ", ".join(["?"] * len(source_types))
        query += f" AND source_type IN ({placeholders})"
        params.extend(source_types)

    if since:
        query += " AND timestamp >= ?"
        params.append(since)

    query += " ORDER BY timestamp DESC"
    if limit:
        query += f" LIMIT {limit}"

    rows = db.execute(query, params).fetchall()
    columns = [desc[0] for desc in db.execute("SELECT * FROM scan_signals LIMIT 1").description]
    return [dict(zip(columns, row)) for row in rows]


def get_latest_signal(symbol, source_types=None):
    """Get the most recent signal for a symbol"""
    db = get_db()
    query = "SELECT * FROM scan_signals WHERE symbol = ?"
    params = [symbol.upper()]

    if source_types:
        placeholders = ", ".join(["?"] * len(source_types))
        query += f" AND source_type IN ({placeholders})"
        params.extend(source_types)

    query += " ORDER BY timestamp DESC LIMIT 1"
    row = db.execute(query, params).fetchone()
    if not row:
        return None

    columns = [desc[0] for desc in db.execute("SELECT * FROM scan_signals LIMIT 1").description]
    return dict(zip(columns, row))


def record_outcome(signal_id, exit_price, change_pct, result):
    """Record the outcome of a signal"""
    db = get_db()
    db.execute(
        """
        INSERT INTO signal_outcomes (signal_id, exit_price, change_pct, result, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (signal_id, exit_price, change_pct, result, time.time())
    )
    db.commit()
    logger.info(f"Outcome recorded for signal {signal_id}: {result} ({change_pct:+.1f}%)")


def get_signal_stats(since=None):
    """Get aggregate stats from signal outcomes"""
    db = get_db()
    query = """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN result = 'SUCCESS' THEN 1 ELSE 0 END) as successes,
            SUM(CASE WHEN result = 'FAILED' THEN 1 ELSE 0 END) as failures,
            SUM(CASE WHEN result = 'PENDING' THEN 1 ELSE 0 END) as pending,
            AVG(CASE WHEN result IN ('SUCCESS', 'FAILED') THEN change_pct END) as avg_change
        FROM signal_outcomes
    """
    params = []
    if since:
        query += " WHERE checked_at >= ?"
        params.append(since)

    row = db.execute(query, params).fetchone()
    if not row:
        return None

    total = row[0] or 0
    successes = row[1] or 0
    failures = row[2] or 0
    pending = row[3] or 0
    avg_change = row[4] or 0
    win_rate = (successes / (successes + failures) * 100) if (successes + failures) > 0 else 0

    return {
        'total': total,
        'successes': successes,
        'failures': failures,
        'pending': pending,
        'win_rate': win_rate,
        'avg_change': avg_change,
    }


def get_pattern_analysis():
    """Analyze which signal types perform best"""
    db = get_db()
    rows = db.execute(
        """
        SELECT
            s.signal_type,
            s.source_type,
            s.narrative,
            COUNT(o.id) as total_checked,
            SUM(CASE WHEN o.result = 'SUCCESS' THEN 1 ELSE 0 END) as successes,
            AVG(o.change_pct) as avg_change
        FROM scan_signals s
        JOIN signal_outcomes o ON s.id = o.signal_id
        GROUP BY s.signal_type, s.source_type, s.narrative
        HAVING total_checked >= 2
        ORDER BY avg_change DESC
        """
    ).fetchall()

    patterns = []
    for row in rows:
        patterns.append({
            'signal_type': row[0],
            'source_type': row[1],
            'narrative': row[2],
            'total': row[3],
            'successes': row[4],
            'win_rate': (row[4] / row[3] * 100) if row[3] > 0 else 0,
            'avg_change': row[5],
        })
    return patterns


# ==================== Settings ====================

def save_setting(key, value):
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    db.commit()


def load_setting(key, default=None):
    init_db()
    db = get_db()
    try:
        row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default


def load_list_setting(key, default=None):
    val = load_setting(key, None)
    if val is None:
        return default if default is not None else []
    return [x.strip() for x in val.split(",") if x.strip()]


def save_list_setting(key, lst):
    save_setting(key, ",".join(lst))


def get_user_language(user_id):
    """Get language preference for a specific user"""
    from duckscreeener.config.settings import BOT_LANGUAGE
    return load_setting(f"user_lang_{user_id}", BOT_LANGUAGE)


def set_user_language(user_id, lang):
    """Set language preference for a specific user"""
    save_setting(f"user_lang_{user_id}", lang)
