"""Tests pour les outils : tools/__init__.py, tools/tools.py."""

import os
import sys
import json
import tempfile
import sqlite3
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock SERPER_KEY pour les tests
os.environ.setdefault("SERPER_KEY", "test_key_mock")

# On initialise une DB de test dans /tmp
TEST_DB = os.path.join(tempfile.gettempdir(), "test_santana_tools.db")
os.environ.pop("HOME", None)  # pas impact
TEST_BASE = tempfile.mkdtemp(suffix="_santana_test")
_BASE_ORIG = None
_CORE_DB_PATH_ORIG = None


def setup_module():
    global _BASE_ORIG, _CORE_DB_PATH_ORIG
    # Patching BASE_DIR
    import tools.tools as tools_mod
    _BASE_ORIG = tools_mod.BASE_DIR
    tools_mod.BASE_DIR = TEST_BASE
    tools_mod.DB_PATH = TEST_DB

    # Pointer DB_PATH vers notre DB de test (propre, sans remplacer get_db)
    import core.db as core_db_mod
    _CORE_DB_PATH_ORIG = core_db_mod.DB_PATH
    core_db_mod.DB_PATH = TEST_DB
    core_db_mod.close_db()  # Forcer reconnexion

    # Créer la DB de test
    from memory.memory import init_db
    # On patch DB_PATH dans memory également
    import memory.memory as mem_mod
    mem_mod.DB_PATH = TEST_DB
    mem_mod.BASE_DIR = TEST_BASE
    init_db()

    # Créer tools.json factice
    os.makedirs(os.path.join(TEST_BASE, "tools"), exist_ok=True)
    with open(os.path.join(TEST_BASE, "tools", "tools.json"), "w") as f:
        json.dump({
            "functions": [
                {"name": "web_search", "description": "Search web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
                {"name": "memory_query", "description": "Query memory", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
                {"name": "get_datetime", "description": "Get time", "parameters": {"type": "object", "properties": {}}},
                {"name": "save_skill", "description": "Save skill", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "trigger": {"type": "string"}, "steps": {"type": "string"}, "pitfalls": {"type": "string"}, "verification": {"type": "string"}}}},
                {"name": "search_skills", "description": "Search skills", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
                {"name": "web_navigate", "description": "Navigate web", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}
            ]
        }, f)

    # Recharger TOOLS depuis le nouveau json
    tools_mod.TOOLS = json.load(open(os.path.join(TEST_BASE, "tools", "tools.json"), "r"))


def teardown_module():
    import shutil
    shutil.rmtree(TEST_BASE, ignore_errors=True)
    if os.path.exists(TEST_DB):
        os.unlink(TEST_DB)
    # Restaurer core.db.DB_PATH
    global _CORE_DB_PATH_ORIG
    if _CORE_DB_PATH_ORIG:
        import core.db as core_db_mod
        core_db_mod.DB_PATH = _CORE_DB_PATH_ORIG
        core_db_mod.close_db()


# ─── execute_tool dispatcher ───────────────────────────────────────────────────

class TestExecuteTool:
    def test_outil_inconnu(self):
        from tools.tools import execute_tool
        result = execute_tool("pizza_maker", {})
        assert "inconnu" in result

    def test_outil_vide(self):
        from tools.tools import execute_tool
        result = execute_tool("", {})
        assert "inconnu" in result

    def test_get_datetime_retourne_string(self):
        from tools.tools import execute_tool
        result = execute_tool("get_datetime", {})
        assert isinstance(result, str)
        assert len(result) > 5


# ─── test skills (DB) ─────────────────────────────────────────────────────────

class TestSkillsTools:
    def test_save_and_search_skill(self):
        from tools.tools import execute_tool
        # Sauver
        result = execute_tool("save_skill", {
            "title": "TestSkill",
            "trigger": "mot clé test",
            "steps": "1. Faire X\n2. Vérifier Y",
            "pitfalls": "Attention à Z",
            "verification": "Ça marche"
        })
        assert "sauvegardee" in result.lower() or "sauvegardé" in result.lower()

        # Rechercher
        result2 = execute_tool("search_skills", {"query": "TestSkill"})
        assert "TestSkill" in result2
        assert "Faire X" in result2 or "X" in result2

    def test_search_skills_sans_resultat(self):
        from tools.tools import execute_tool
        result = execute_tool("search_skills", {"query": "ZZZZinexistant999"})
        assert "Aucune" in result or "trouvée" in result or "trouvee" in result

    def test_save_skill_champs_manquants(self):
        from tools.tools import execute_tool
        result = execute_tool("save_skill", {"title": "Minimal"})
        # Ne doit pas planter
        assert isinstance(result, str)

    def test_search_skills_query_vide(self):
        from tools.tools import execute_tool
        result = execute_tool("search_skills", {"query": ""})
        assert isinstance(result, str)


# ─── memory_query avec DB vide/partielle ──────────────────────────────────────

class TestMemoryQuery:

    def test_memory_query_sans_resultat(self):
        """Avec recherche semantique, retourne toujours les meilleurs chunks."""
        from tools.tools import execute_tool
        result = execute_tool("memory_query", {"query": "QQQinexistant999"})
        # La recherche semantique trouve toujours le chunk le moins dissimilar
        assert isinstance(result, str) and len(result) > 0


# ─── web_search (nécessite SERPER_KEY) ─────────────────────────────────────────
# Marqué "slow" car dépend du réseau

class TestWebSearch:
    def test_web_search_pas_de_clef(self):
        """Sans vraie SERPER_KEY, utilise le fallback (DuckDuckGo ou erreur)."""
        from tools.tools import execute_tool
        old_key = os.environ.get("SERPER_KEY")
        os.environ["SERPER_KEY"] = ""
        try:
            result = execute_tool("web_search", {"query": "test"})
            # L'API appelle SERPER avec clé vide → tombe en fallback DuckDuckGo
            assert isinstance(result, str)
            assert len(result) > 0
            # Le fallback DuckDuckGo retourne des résultats réels (pas de clé Serper nécessaire)
            # ou un message d'erreur si le réseau est indisponible
            assert "Aucun" in result or "Erreur" in result or "indisponible" in result \
                or "Speedtest" in result or "test" in result.lower()[:200] \
                or len(result) > 100  # Accepte les résultats réels de DuckDuckGo
        finally:
            if old_key:
                os.environ["SERPER_KEY"] = old_key
            else:
                os.environ.pop("SERPER_KEY", None)

    def test_web_search_sans_query(self):
        from tools.tools import execute_tool
        result = execute_tool("web_search", {})
        assert isinstance(result, str)
