"""
recorder.py — Enregistrement des métriques d'appels d'outils pour Santana.

Décorateur @track() :
    Appliqué aux fonctions outils, capture automatiquement :
    - nom outil, succès/échec, latence, type d'erreur
    - écrit dans metrics.db (base dédiée, thread-local)

Utilisation :
    @track()
    def tool_vm_exec(command: str) -> str:
        ...

Ou avec options :
    @track(skip_on=KeyboardInterrupt)
    def my_tool(...):
        ...
"""

import os
import time
import logging
import sqlite3
import threading
import functools
from typing import Callable, Optional, Type

logger = logging.getLogger("metrics.recorder")

# Chemin de la base de métriques dédiée
METRICS_DB_PATH = os.path.expanduser("~/santana/metrics.db")

# Thread-local storage pour les connexions metrics.db
_local = threading.local()


def _get_metrics_db() -> sqlite3.Connection:
    """Retourne une connexion thread-local vers metrics.db."""
    if not hasattr(_local, "conn") or _local.conn is None:
        try:
            _local.conn = sqlite3.connect(METRICS_DB_PATH)
            _local.conn.execute("PRAGMA journal_mode=WAL")
            _local.conn.execute("PRAGMA busy_timeout=5000")
            _local.conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logger.error(f"[METRICS] Erreur initialisation connexion: {e}")
            raise
    return _local.conn


def _close_metrics_db():
    """Ferme la connexion metrics.db du thread courant."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except sqlite3.Error as e:
            logger.warning(f"[METRICS] Erreur fermeture connexion: {e}")
        finally:
            _local.conn = None


def init_metrics_db():
    """Crée les tables metrics.db si elles n'existent pas.

    Appeler au démarrage de Santana (une fois par thread).
    """
    try:
        conn = _get_metrics_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name   TEXT NOT NULL,
                success     INTEGER NOT NULL DEFAULT 1,
                latency_ms  REAL NOT NULL DEFAULT 0.0,
                error_type  TEXT,
                timestamp   TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS errors (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name   TEXT NOT NULL,
                error_type  TEXT NOT NULL,
                message     TEXT,
                count       INTEGER NOT NULL DEFAULT 1,
                first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(tool_name, error_type)
            );

            CREATE TABLE IF NOT EXISTS improvements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                patch_id    TEXT NOT NULL UNIQUE,
                problem     TEXT NOT NULL,
                solution    TEXT NOT NULL,
                risk        TEXT NOT NULL DEFAULT 'medium',
                test_status TEXT NOT NULL DEFAULT 'pending',
                applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name);
            CREATE INDEX IF NOT EXISTS idx_tool_calls_timestamp ON tool_calls(timestamp);
            CREATE INDEX IF NOT EXISTS idx_errors_tool ON errors(tool_name, error_type);
        """)
        conn.commit()
        logger.info("[METRICS] Base initialisée")
    except sqlite3.Error as e:
        logger.error(f"[METRICS] Erreur initialisation schéma: {e}")


def record_tool_call(tool_name: str, success: bool, latency_ms: float,
                     error_type: Optional[str] = None):
    """Enregistre un appel outil dans tool_calls.

    Args:
        tool_name: Nom de l'outil
        success: True si succès, False si échec
        latency_ms: Durée d'exécution en millisecondes
        error_type: Type d'erreur (None si succès)
    """
    try:
        conn = _get_metrics_db()
        conn.execute(
            "INSERT INTO tool_calls (tool_name, success, latency_ms, error_type) VALUES (?, ?, ?, ?)",
            (tool_name, 1 if success else 0, round(latency_ms, 2), error_type)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"[METRICS] Écriture tool_calls échouée: {e}")


def record_error(tool_name: str, error_type: str, message: str):
    """Incrémente ou crée une entrée dans la table errors.

    Utilise UPSERT (INSERT ... ON CONFLICT) pour compter les occurrences.

    Args:
        tool_name: Nom de l'outil en erreur
        error_type: Type/catégorie de l'erreur
        message: Message d'erreur brut
    """
    try:
        conn = _get_metrics_db()
        conn.execute(
            """INSERT INTO errors (tool_name, error_type, message, count, first_seen, last_seen)
               VALUES (?, ?, ?, 1, datetime('now'), datetime('now'))
               ON CONFLICT(tool_name, error_type) DO UPDATE SET
                   count = count + 1,
                   last_seen = datetime('now'),
                   message = excluded.message
               WHERE tool_name = excluded.tool_name AND error_type = excluded.error_type""",
            (tool_name, error_type, (message or "")[:500])
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"[METRICS] Écriture errors échouée: {e}")


def get_consecutive_failures(tool_name: str) -> int:
    """Compte le nombre d'échecs consécutifs pour un outil donné.

    Fonctionne en parcourant les entrées tool_calls par timestamp décroissant
    et en s'arrêtant au premier succès.

    Args:
        tool_name: Nom de l'outil

    Returns:
        Nombre d'échecs consécutifs (0 si aucun)
    """
    try:
        conn = _get_metrics_db()
        rows = conn.execute(
            """SELECT success FROM tool_calls
               WHERE tool_name = ?
               ORDER BY id DESC LIMIT 50""",
            (tool_name,)
        ).fetchall()
        consecutive = 0
        for row in rows:
            if row["success"] == 0:
                consecutive += 1
            else:
                break
        return consecutive
    except sqlite3.Error as e:
        logger.error(f"[METRICS] Erreur lecture tool_calls: {e}")
        return 0


# ── Décorateur @track ────────────────────────────────────────────────────────

def track(skip_on: Optional[Type[BaseException]] = None):
    """Décorateur pour tracer automatiquement les appels d'outils.

    Capture :
        - nom de la fonction (tool_name)
        - succès/échec
        - latence en ms
        - type d'erreur

    La fonction décorée s'exécute normalement. Si une exception est levée,
    elle est enregistrée comme échec puis propagée.

    Args:
        skip_on: Type d'exception à ignorer (ne pas enregistrer comme échec)

    Usage :
        @track()
        def tool_vm_exec(command: str) -> str:
            ...

        @track(skip_on=KeyboardInterrupt)
        def my_loop(...):
            ...
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tool_name = func.__name__
            # Enlever le préfixe _tool_ pour normaliser (les doublons _tool_web_search → web_search)
            if tool_name.startswith("_tool_"):
                tool_name = tool_name[1:]  # → tool_web_search
            t_start = time.time()
            try:
                result = func(*args, **kwargs)
                latency = (time.time() - t_start) * 1000
                record_tool_call(tool_name, True, latency)
                return result
            except Exception as e:
                latency = (time.time() - t_start) * 1000
                if skip_on and isinstance(e, skip_on):
                    # Ne pas enregistrer cette exception comme échec métier
                    raise
                error_type = type(e).__name__
                record_tool_call(tool_name, False, latency, error_type)
                record_error(tool_name, error_type, str(e))
                raise  # propager l'exception pour que l'appelant puisse la gérer
        return wrapper
    return decorator
