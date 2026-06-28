"""
Traçabilité pour Santana (F8).

Log structuré des actions. Stockage SQLite (metrics.db).

(Migré JSON→SQLite le 20 juin 2026.)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BASE_DIR = os.path.expanduser("~/santana")
DB_PATH = os.path.join(BASE_DIR, "metrics.db")
MAX_ENTRIES = 10_000
TRUNCATE_LENGTH = 200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_action(
    action_type: str,
    content: str,
    metadata: dict | None = None,
) -> dict:
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    truncated = content[:TRUNCATE_LENGTH] if len(content) > TRUNCATE_LENGTH else content
    ts = _now_iso()

    entry = {
        "timestamp": ts,
        "type": action_type,
        "content": truncated,
        "content_full_length": len(content),
        "metadata": metadata or {},
    }

    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute(
            "INSERT INTO tracabilite (timestamp, type, content, meta) VALUES (?, ?, ?, ?)",
            (ts, action_type, truncated, json.dumps(metadata or {}))
        )
        conn.execute(
            "DELETE FROM tracabilite WHERE id NOT IN (SELECT id FROM tracabilite ORDER BY id DESC LIMIT ?)",
            (MAX_ENTRIES,)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("[TRACABILITE] SQLite error: %s", e)

    logger.debug("[TRACABILITE] Logged %s: %s", action_type, truncated[:80])
    return entry
