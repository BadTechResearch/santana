"""Souveraineté — Surveillance des appels externes de Santana (F10).

Audit en temps réel : chaque appel à une API externe est enregistré pour
traçabilité. Stockage SQLite (metrics.db) via core/db.get_metrics_db().

(Migré JSON→SQLite le 20 juin 2026.)
"""

import logging
import sqlite3
from datetime import datetime, timezone

from core.db import get_metrics_db

logger = logging.getLogger(__name__)

MAX_ENTRIES = 2_000


def _host_of(url: str) -> str:
    from urllib.parse import urlparse
    try:
        return urlparse(url).netloc or url[:80]
    except Exception:
        return url[:80]


def _known_hosts() -> set[str]:
    return {
        "api.deepseek.com",
        "google.serper.dev",
        "api.telegram.org",
        "api.github.com",
    }


def surveiller_appel_externe(url: str, contexte: str = "") -> dict:
    """Enregistre un appel externe en SQLite (O(1) au lieu de O(n) JSON)."""
    host = _host_of(url)
    connu = 1 if host in _known_hosts() else 0
    ts = datetime.now(timezone.utc).isoformat()

    try:
        conn = get_metrics_db()
        conn.execute(
            "INSERT INTO souverainete (timestamp, url, host, contexte, connu) VALUES (?, ?, ?, ?, ?)",
            (ts, url[:200], host, contexte[:100], connu)
        )
        # Rotation O(1) : supprimer les plus vieilles si trop d'entrées
        conn.execute(
            "DELETE FROM souverainete WHERE id NOT IN (SELECT id FROM souverainete ORDER BY id DESC LIMIT ?)",
            (MAX_ENTRIES,)
        )
        conn.commit()
    except Exception as e:
        logger.warning("[SOUVERAINETE] SQLite error: %s", e)

    logger.debug("[SOUVERAINETE] Appel externe: %s (%s)", host, contexte)
    return {
        "url": url[:200],
        "host": host,
        "connu": bool(connu),
        "statut": "surveille",
    }
