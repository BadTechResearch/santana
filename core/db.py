"""db.py — Gestionnaire de connexion SQLite thread-safe pour Santana.

Utilisation :
    with get_db() as conn:
        conn.execute(...)

Évite d'ouvrir/fermer une connexion à chaque appel mémoire.
Les connexions sont thread-local (une par thread).

Deux bases :
  - get_db()        → memory.db   (mémoire conversationnelle)
  - get_metrics_db() → metrics.db (métriques, audits, patterns)
"""
import os
import sqlite3
import logging
import threading
from core.utils import get_base_dir

BASE_DIR = get_base_dir()
# Nom historique DB_PATH conservé (pas MEMORY_DB) : plusieurs tests
# (test_context.py, test_memory.py, test_100_memoire.py, test_tools.py)
# monkeypatchent `core.db.DB_PATH` directement pour isoler leurs écritures
# dans un fichier temporaire — renommer la variable casse cette isolation
# silencieusement (get_db() doit relire l'attribut de module à chaque appel).
DB_PATH = os.path.join(BASE_DIR, "memory.db")
METRICS_DB = os.path.join(BASE_DIR, "metrics.db")

# Thread-local storage : chaque thread a sa propre connexion
_local = threading.local()


def get_db() -> sqlite3.Connection:
    """Retourne une connexion à memory.db (thread-local)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        try:
            _local.conn = sqlite3.connect(DB_PATH)
            _local.conn.execute("PRAGMA journal_mode=WAL")
            _local.conn.execute("PRAGMA busy_timeout=5000")
            _local.conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            logging.error(f"[DB] Erreur initialisation connexion: {e}")
            raise
    return _local.conn


def get_metrics_db() -> sqlite3.Connection:
    """Retourne une connexion à metrics.db avec auto-création des tables."""
    if not hasattr(_local, "metrics_conn") or _local.metrics_conn is None:
        try:
            _local.metrics_conn = sqlite3.connect(METRICS_DB)
            _local.metrics_conn.execute("PRAGMA journal_mode=WAL")
            _local.metrics_conn.execute("PRAGMA busy_timeout=5000")
            _local.metrics_conn.execute("PRAGMA foreign_keys=ON")
            # Créer toutes les tables au premier accès
            _init_metrics_tables(_local.metrics_conn)
        except sqlite3.Error as e:
            logging.error(f"[DB] Erreur initialisation metrics.db: {e}")
            raise
    return _local.metrics_conn


def _init_metrics_tables(conn: sqlite3.Connection):
    """Crée toutes les tables de metrics.db si elles n'existent pas."""
    tables = [
        # Sécurité (agent/securite.py)
        """CREATE TABLE IF NOT EXISTS ratelimit (
            cle TEXT PRIMARY KEY, timestamps TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS securite_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, utilisateur TEXT, action TEXT, statut TEXT
        )""",
        # Traçabilité (agent/tracabilite.py)
        """CREATE TABLE IF NOT EXISTS tracabilite (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, type TEXT, content TEXT, meta TEXT
        )""",
        # Souveraineté (agent/souverainete.py)
        """CREATE TABLE IF NOT EXISTS souverainete (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT, url TEXT, host TEXT, contexte TEXT, connu INTEGER
        )""",
        # Patterns (agent/patterns.py)
        """CREATE TABLE IF NOT EXISTS tool_state (
            key TEXT PRIMARY KEY, value TEXT
        )""",
        # Évaluations (agent/evaluator.py)
        """CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            score REAL, message TEXT, reponse TEXT,
            timestamp TEXT, metriques TEXT
        )""",
        # Workspace state (tools/tools.py)
        """CREATE TABLE IF NOT EXISTS ws (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
        )""",
        # Métriques mensuelles (metrics/recorder.py)
        """CREATE TABLE IF NOT EXISTS metrics (
            mois TEXT, provider TEXT,
            tokens_prompt INTEGER, tokens_completion INTEGER,
            cout REAL, appels INTEGER,
            PRIMARY KEY (mois, provider)
        )""",
        # Latence par message (Phase 4 — Monitoring)
        """CREATE TABLE IF NOT EXISTS message_latency (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            msg_type TEXT,
            ttft_ms INTEGER,
            total_ms INTEGER,
            tool_count INTEGER,
            flood_429_count INTEGER,
            token_count INTEGER,
            provider TEXT,
            user_msg_len INTEGER
        )""",
    ]
    for stmt in tables:
        try:
            conn.execute(stmt)
        except sqlite3.Error as e:
            logging.error(f"[DB] Erreur CREATE TABLE: {e}")
    conn.commit()


def close_db():
    """Ferme les connexions du thread courant."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except sqlite3.Error as e:
            logging.warning(f"[DB] Erreur fermeture memory.db: {e}")
        finally:
            _local.conn = None
    if hasattr(_local, "metrics_conn") and _local.metrics_conn is not None:
        try:
            _local.metrics_conn.close()
        except sqlite3.Error as e:
            logging.warning(f"[DB] Erreur fermeture metrics.db: {e}")
        finally:
            _local.metrics_conn = None
