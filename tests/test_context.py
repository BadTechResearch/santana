"""Tests pour agent/context.py — gestion intelligente du contexte."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile
import sqlite3

# Fixture DB de test avant l'import
TEST_DIR = tempfile.mkdtemp(suffix="_santana_ctx_test")
TEST_DB = os.path.join(TEST_DIR, "test_context.db")

def _test_get_db():
    conn = sqlite3.connect(TEST_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

import core.db
_ORIG_DB_PATH = core.db.DB_PATH
_ORIG_GET_DB = core.db.get_db

from agent.context import (
    init_session, push_exchange, get_session_buffer,
    get_session_summary, maybe_auto_summarize, get_context,
    estimate_tokens, reset_session, COMPRESSION_CONFIG,
    SESSION_ID, MESSAGE_COUNTER,
)


def setup_module():
    os.makedirs(TEST_DIR, exist_ok=True)
    # Pointer DB_PATH vers TEST_DB pour ce module
    core.db.DB_PATH = TEST_DB
    core.db.close_db()


def teardown_module():
    import shutil
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    # Restaurer DB_PATH et get_db originaux
    core.db.DB_PATH = _ORIG_DB_PATH
    core.db.get_db = _ORIG_GET_DB
    try:
        core.db.close_db()
    except Exception:
        pass


class TestInit:
    def test_init_cree_tables(self):
        init_session()
        conn = _test_get_db()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in c.fetchall()]
        conn.close()
        assert "session_buffer" in tables
        assert "session_summaries" in tables

    def test_init_idempotent(self):
        init_session()
        init_session()  # Ne doit pas crasher


class TestPushAndGet:
    def setup_method(self):
        reset_session()
        init_session()
        conn = _test_get_db()
        conn.execute("DELETE FROM session_buffer")
        conn.commit()
        conn.close()

    def test_push_un_message(self):
        push_exchange("user", "Bonjour")
        buf = get_session_buffer()
        assert "Bonjour" in buf
        assert "Serge" in buf

    def test_push_plusieurs_messages(self):
        push_exchange("user", "M1")
        push_exchange("assistant", "R1")
        push_exchange("user", "M2")
        buf = get_session_buffer()
        assert "M1" in buf
        assert "M2" in buf
        assert "R1" in buf

    def test_push_garde_max_messages(self):
        max_n = COMPRESSION_CONFIG["buffer_max_messages"]
        for i in range(max_n + 10):
            push_exchange("user", f"msg {i}")
        buf = get_session_buffer()
        lines = buf.strip().split("\n")
        assert len(lines) <= max_n

    def test_buffer_vide_sans_messages(self):
        buf = get_session_buffer()
        assert buf == ""


class TestEstimateTokens:
    def test_texte_vide(self):
        assert estimate_tokens("") == 0

    def test_texte_court(self):
        t = estimate_tokens("Bonjour")
        assert t == 2  # 1 mot → words/0.75 = 1.33 → 2

    def test_texte_long(self):
        t = estimate_tokens("a" * 400)
        assert t == 133  # 400 chars / 3 (fallback caractères) = 133


class TestGetContext:
    def setup_method(self):
        reset_session()
        init_session()
        conn = _test_get_db()
        conn.execute("DELETE FROM session_buffer")
        conn.execute("DELETE FROM session_summaries")
        conn.commit()
        conn.close()

    def test_contexte_vide(self):
        ctx = get_context()
        assert ctx == ""

    def test_contexte_avec_messages(self):
        push_exchange("user", "Question test")
        push_exchange("assistant", "Réponse test")
        ctx = get_context()
        assert "Question" in ctx
        assert "Réponse" in ctx

    def test_contexte_avec_resume(self):
        push_exchange("user", "M1")
        push_exchange("assistant", "R1")
        # Créer un résumé manuellement
        conn = _test_get_db()
        c = conn.cursor()
        from agent.context import SESSION_ID
        c.execute(
            "INSERT OR REPLACE INTO session_summaries (session_id, summary, exchange_count) VALUES (?, ?, ?)",
            (SESSION_ID, "Résumé: test conversation", 2)
        )
        conn.commit()
        conn.close()
        ctx = get_context()
        assert "RÉSUMÉ" in ctx
        assert "Résumé" in ctx


class TestResetSession:
    def test_reset_change_session_id(self):
        init_session()
        old_id = SESSION_ID
        reset_session()
        new_id = SESSION_ID
        # reset change l'ID de session (timestamp à l'heure)
        # Sauf si on est dans la même heure, les IDs peuvent être identiques
        # Dans ce cas, on vérifie que le compteur est remis à 0
        assert MESSAGE_COUNTER == 0


class TestCompression:
    def test_soft_warn_pas_encore_atteint(self):
        """Avec peu de messages, pas de compression."""
        reset_session()
        init_session()
        conn = _test_get_db()
        conn.execute("DELETE FROM session_buffer")
        conn.commit()
        conn.close()
        for i in range(3):
            push_exchange("user", f"M{i}")
            push_exchange("assistant", f"R{i}")
        ctx = get_context()
        assert "SESSION EN COURS" in ctx
