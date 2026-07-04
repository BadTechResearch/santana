"""Sécurité pour Santana (F9).

Rate-limiting : limite le nombre d'appels par clé et par fenêtre de temps.
Audit des accès : log structuré de toutes les tentatives d'accès.
Stockage SQLite (metrics.db) via core/db.get_metrics_db().

(Migré JSON→SQLite le 20 juin 2026.)
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from core.db import get_metrics_db

logger = logging.getLogger(__name__)

MAX_AUDIT_ENTRIES = 5_000

_lock = threading.Lock()
# Cache mémoire pour éviter SQLite à chaque check
_cache = {}
_cache_ts = 0.0
_CACHE_TTL = 5.0


# ─── Rate-limiting (cache mémoire + SQLite) ─────────────────────────────

def _now_epoch() -> float:
    return time.time()


def _ensure_loaded():
    """Charge le cache depuis SQLite."""
    global _cache, _cache_ts
    if _cache and time.time() - _cache_ts < _CACHE_TTL:
        return
    try:
        conn = get_metrics_db()
        c = conn.cursor()
        c.execute("SELECT cle, timestamps FROM ratelimit")
        _cache = {row[0]: json.loads(row[1]) for row in c.fetchall()}
        _cache_ts = time.time()
    except Exception as e:
        logger.error("[SECURITE] Erreur chargement ratelimit: %s", e)
        _cache = {}


def _flush_ratelimit():
    """Sauvegarde le cache dans SQLite."""
    try:
        conn = get_metrics_db()
        for key, timestamps in _cache.items():
            conn.execute(
                "INSERT OR REPLACE INTO ratelimit (cle, timestamps) VALUES (?, ?)",
                (key, json.dumps(timestamps))
            )
        conn.commit()
    except Exception as e:
        logger.error("[SECURITE] Erreur sauvegarde ratelimit: %s", e)


def check_rate_limit(key: str, max_calls: int = 30, window_seconds: int = 60) -> bool:
    with _lock:
        _ensure_loaded()
        now = time.time()
        timestamps = _cache.get(key, [])
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= max_calls:
            return False
        timestamps.append(now)
        _cache[key] = timestamps
        _flush_ratelimit()
    return True


def get_all_rate_limits() -> dict:
    _ensure_loaded()
    now = time.time()
    return {
        k: [t for t in v if now - t < 60]
        for k, v in _cache.items()
    }


def get_tool_limit(tool_name: str) -> dict | None:
    return None  # Géré par cost_governor


def check_tool_rate_limit(tool_name: str, tokens: int = 0) -> tuple[bool, str]:
    limit_name = f"tool:{tool_name}"
    ok = check_rate_limit(limit_name, max_calls=30, window_seconds=60)
    if not ok:
        logger.warning("[SECURITE] Rate-limit: %s > 30 appels/60s", tool_name)
        return False, f"Trop d'appels à {tool_name} (30/60s)"
    return True, "ok"


# ─── Audit (SQLite) ─────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_access(utilisateur: str, action: str, statut: str) -> dict:
    ts = _now_iso()
    try:
        conn = get_metrics_db()
        conn.execute(
            "INSERT INTO securite_audit (timestamp, utilisateur, action, statut) VALUES (?, ?, ?, ?)",
            (ts, utilisateur, action, statut)
        )
        conn.execute(
            "DELETE FROM securite_audit WHERE id NOT IN (SELECT id FROM securite_audit ORDER BY id DESC LIMIT ?)",
            (MAX_AUDIT_ENTRIES,)
        )
        conn.commit()
    except Exception as e:
        logger.error("[SECURITE] Audit SQLite error: %s", e)

    logger.debug("[SECURITE] Audit: %s %s → %s", utilisateur, action, statut)
    return {"timestamp": ts, "utilisateur": utilisateur, "action": action, "statut": statut}
