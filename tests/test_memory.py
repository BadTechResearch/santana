"""Tests pour memory/memory.py : SQLite persistence."""

import os
import sys
import tempfile
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_DIR = tempfile.mkdtemp(suffix="_santana_mem_test")
TEST_DB = os.path.join(TEST_DIR, "test_memory.db")

import core.db
_ORIG_DB_PATH = core.db.DB_PATH

from memory import memory as mem_mod


def setup_module():
    global _ORIG_BASE_DIR
    _ORIG_BASE_DIR = mem_mod.BASE_DIR
    mem_mod.BASE_DIR = TEST_DIR
    # Fermer toute connexion résiduelle d'un module précédent
    core.db.close_db()
    os.makedirs(TEST_DIR, exist_ok=True)
    # Pointer DB_PATH vers TEST_DB pour ce module
    core.db.DB_PATH = TEST_DB
    core.db.close_db()  # Forcer reconnexion
    # Créer les tables
    conn = core.db.get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        trigger_condition TEXT,
        steps TEXT,
        pitfalls TEXT,
        verification TEXT,
        usage_count INTEGER DEFAULT 1,
        success_rate REAL DEFAULT 1.0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()


def teardown_module():
    import shutil
    core.db.close_db()
    # Restaurer DB_PATH et BASE_DIR originaux AVANT rm tree
    core.db.DB_PATH = _ORIG_DB_PATH
    mem_mod.BASE_DIR = _ORIG_BASE_DIR
    shutil.rmtree(TEST_DIR, ignore_errors=True)


class TestMemory:
    def setup_method(self):
        """Nettoyer la DB avant chaque test."""
        conn = core.db.get_db()
        conn.execute("DELETE FROM memory")
        conn.execute("DELETE FROM skills")
        conn.commit()

    def test_init_db_cree_tables(self):
        """Les tables doivent etre creees par init_db."""
        conn = core.db.get_db()
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in c.fetchall()]
        assert "memory" in tables

    def test_save_and_recover(self):
        """save_message + get_recent_memory : cycle complet."""
        mem_mod.save_message("user", "Bonjour test")
        msgs = mem_mod.get_recent_memory(50)
        assert any(m["role"] == "user" and "Bonjour" in m["content"] for m in msgs)

    def test_rotate_memory_garde_max(self):
        """rotate_memory limite le nombre de souvenirs a 500 max."""
        # Ajouter 510 messages
        for i in range(510):
            mem_mod.save_message("user", f"msg {i}")
        mem_mod.rotate_memory(max_souvenirs=500)
        assert mem_mod.count_memory() <= 500

    def test_seed_initial_skills_avec_fichier(self):
        """seed_initial_skills lit les .md et cree des entrees en DB."""
        # Creer un fichier .md dans skills/
        skills_dir = os.path.join(TEST_DIR, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        with open(os.path.join(skills_dir, "mon_test.md"), "w") as f:
            f.write("# Mon Test\nÉtape 1: faire ceci\n")
        mem_mod.seed_initial_skills()

        conn = core.db.get_db()
        c = conn.cursor()
        c.execute("SELECT title FROM skills WHERE title='Mon Test'")
        assert c.fetchone() is not None

    def test_count_empty_db(self):
        """count_memory retourne 0 si la table est vide."""
        conn = core.db.get_db()
        conn.execute("DELETE FROM memory")
        conn.commit()
        assert mem_mod.count_memory() == 0

    def test_save_long_content(self):
        """save_message gère du contenu long sans erreur."""
        long_text = "A" * 10000
        mem_mod.save_message("user", long_text)
        msgs = mem_mod.get_recent_memory(50)
        found = any(m["role"] == "user" and len(m["content"]) >= 10000 for m in msgs)
        assert found, "Le long contenu devrait être sauvegardé"

    def test_get_recent_vide(self):
        """get_recent_memory retourne [] sur DB vide."""
        conn = core.db.get_db()
        conn.execute("DELETE FROM memory")
        conn.commit()
        msgs = mem_mod.get_recent_memory(50)
        assert msgs == []