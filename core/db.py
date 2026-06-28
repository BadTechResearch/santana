"""
db.py — Gestionnaire de connexion SQLite thread-safe pour Santana.

Utilisation :
    with get_db() as conn:
        conn.execute(...)

Évite d'ouvrir/fermer une connexion à chaque appel mémoire.
Les connexions sont thread-local (une par thread).
"""
import os
import sqlite3
import logging
import threading

DB_PATH = os.path.expanduser("~/santana/memory.db")

# Thread-local storage : chaque thread a sa propre connexion
_local = threading.local()


def get_db() -> sqlite3.Connection:
    """Retourne une connexion SQLite (thread-local, auto-créée au premier appel)."""
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


def close_db():
    """Ferme la connexion du thread courant si elle existe."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except sqlite3.Error as e:
            logging.warning(f"[DB] Erreur fermeture connexion: {e}")
        finally:
            _local.conn = None
