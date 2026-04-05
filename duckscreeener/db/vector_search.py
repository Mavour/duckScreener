import logging
import math
import json
import time
import requests
from duckscreeener.config.settings import OPENROUTER_API_KEY
from duckscreeener.db.database import get_db

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5:free"
EMBEDDING_DIM = 768
_last_embedding_time = 0
_embedding_cooldown = 10


def generate_embedding(text):
    """Generate embedding via OpenRouter API"""
    try:
        url = "https://openrouter.ai/api/v1/embeddings"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": EMBEDDING_MODEL,
            "input": text[:8000],
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        embedding = data.get("data", [{}])[0].get("embedding", [])
        if embedding:
            return embedding
    except Exception as e:
        logger.warning(f"Embedding generation failed: {e}")
    return None


def _serialize_embedding(embedding):
    """Convert float list to bytes for SQLite storage"""
    return json.dumps(embedding).encode('utf-8')


def _deserialize_embedding(blob):
    """Convert bytes back to float list"""
    return json.loads(blob.decode('utf-8'))


def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0
    return dot / (norm_a * norm_b)


def store_embedding(knowledge_id, text):
    """Generate and store embedding for a knowledge entry"""
    global _last_embedding_time

    now = time.time()
    if now - _last_embedding_time < _embedding_cooldown:
        logger.debug(f"Embedding rate-limited, skipping {knowledge_id}")
        return

    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            knowledge_id INTEGER PRIMARY KEY,
            embedding BLOB NOT NULL,
            FOREIGN KEY (knowledge_id) REFERENCES knowledge(id)
        )
        """
    )
    db.commit()

    existing = db.execute(
        "SELECT 1 FROM knowledge_embeddings WHERE knowledge_id = ?",
        (knowledge_id,)
    ).fetchone()
    if existing:
        return

    embedding = generate_embedding(text)
    if embedding:
        _last_embedding_time = time.time()
        db.execute(
            "INSERT INTO knowledge_embeddings (knowledge_id, embedding) VALUES (?, ?)",
            (knowledge_id, _serialize_embedding(embedding)),
        )
        db.commit()
        logger.info(f"Embedding stored for knowledge {knowledge_id}")


def search_semantic(query, limit=5):
    """Search knowledge base using semantic similarity"""
    db = get_db()

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            knowledge_id INTEGER PRIMARY KEY,
            embedding BLOB NOT NULL,
            FOREIGN KEY (knowledge_id) REFERENCES knowledge(id)
        )
        """
    )
    db.commit()

    query_embedding = generate_embedding(query)
    if not query_embedding:
        logger.warning("Semantic search failed, falling back to FTS5")
        from duckscreeener.db.database import search_knowledge
        return search_knowledge(query, limit)

    # First narrow down with FTS5 to avoid loading all embeddings
    from duckscreeener.db.database import get_db
    db = get_db()
    try:
        fts_rows = db.execute(
            "SELECT id FROM knowledge_fts WHERE knowledge_fts MATCH ? LIMIT ?",
            (query, limit * 4)
        ).fetchall()
    except Exception:
        fts_rows = []

    if fts_rows:
        # Only compute similarity for FTS5 candidates
        candidate_ids = [r[0] for r in fts_rows]
        placeholders = ", ".join(["?"] * len(candidate_ids))
        rows = db.execute(
            f"SELECT ke.knowledge_id, ke.embedding, k.source, k.text, k.timestamp "
            f"FROM knowledge_embeddings ke JOIN knowledge k ON ke.knowledge_id = k.id "
            f"WHERE ke.knowledge_id IN ({placeholders})",
            candidate_ids
        ).fetchall()
    else:
        # Fallback: load all embeddings
        rows = db.execute(
            "SELECT ke.knowledge_id, ke.embedding, k.source, k.text, k.timestamp "
            "FROM knowledge_embeddings ke JOIN knowledge k ON ke.knowledge_id = k.id"
        ).fetchall()

    if not rows:
        from duckscreeener.db.database import search_knowledge
        return search_knowledge(query, limit)

    results = []
    for row in rows:
        knowledge_id = row[0]
        embedding = _deserialize_embedding(row[1])
        source = row[2]
        text = row[3]
        timestamp = row[4]

        similarity = cosine_similarity(query_embedding, embedding)
        results.append({
            'knowledge_id': knowledge_id,
            'source': source,
            'text': text,
            'timestamp': timestamp,
            'similarity': similarity,
        })

    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:limit]
