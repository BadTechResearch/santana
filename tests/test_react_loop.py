"""Tests pour core/react_loop.py : react_loop, connaissances.

Note : build_system_prompt et load_soul_file sont maintenant
dans agent/orchestrator.py. Les tests ici les importent depuis là-bas.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_DIR = tempfile.mkdtemp(suffix="_santana_react_test")
os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"

# Patcher BASE_DIR de react_loop et SOUL_DIR de l'orchestrator
from core import react_loop as rl_mod
rl_mod.BASE_DIR = TEST_DIR

from agent import orchestrator as orch_mod
orch_mod.BASE_DIR = TEST_DIR
orch_mod.SOUL_DIR = os.path.join(TEST_DIR, "soul")

SOUL_DIR = os.path.join(TEST_DIR, "soul")
os.makedirs(SOUL_DIR, exist_ok=True)


def teardown_module():
    import shutil
    shutil.rmtree(TEST_DIR, ignore_errors=True)


# ─── load_soul_file (maintenant dans agent/orchestrator) ─────────────────

class TestLoadSoulFile:
    def test_fichier_inexistant(self):
        assert orch_mod.load_soul_file("inexistant.md") == ""

    def test_fichier_existant(self):
        with open(os.path.join(SOUL_DIR, "SOUL.md"), "w") as f:
            f.write("Tu es Santana, un assistant.")
        assert "Santana" in orch_mod.load_soul_file("SOUL.md")

    def test_fichier_vide(self):
        with open(os.path.join(SOUL_DIR, "VIDE.md"), "w") as f:
            f.write("   ")
        assert orch_mod.load_soul_file("VIDE.md").strip() == ""


# ─── load_knowledge ────────────────────────────────────────────────────────────

class TestLoadKnowledge:
    def test_sans_dossier_knowledge(self):
        from routes import common as common_mod
        common_mod.BASE_DIR = TEST_DIR
        from routes.common import load_knowledge
        kdir = os.path.join(TEST_DIR, "knowledge")
        if os.path.exists(kdir):
            import shutil
            shutil.rmtree(kdir)
        assert load_knowledge() == ""

    def test_avec_fichier_knowledge(self):
        from routes import common as common_mod
        common_mod.BASE_DIR = TEST_DIR
        from routes.common import load_knowledge
        kdir = os.path.join(TEST_DIR, "knowledge")
        os.makedirs(kdir, exist_ok=True)
        with open(os.path.join(kdir, "regles.md"), "w") as f:
            f.write("Règle 1: toujours répondre en français.")
        result = load_knowledge()
        assert "français" in result or "francais" in result or "Règle" in result


# ─── build_system_prompt (maintenant dans agent/orchestrator) ─────────────

class TestBuildSystemPrompt:
    def test_sans_soul(self):
        """Sans SOUL.md, retourne le prompt par défaut."""
        prompt = orch_mod.build_system_prompt()
        assert "Santana" in prompt
        assert "SINBAD" in prompt

    def test_avec_soul_et_user(self):
        with open(os.path.join(SOUL_DIR, "SOUL.md"), "w") as f:
            f.write("Personnalité: calme et précis")
        with open(os.path.join(SOUL_DIR, "USER.md"), "w") as f:
            f.write("Serge aime le café")
        prompt = orch_mod.build_system_prompt()
        assert "café" in prompt or "cafe" in prompt

    def test_contient_outils(self):
        prompt = orch_mod.build_system_prompt()
        assert "web_search" in prompt
        assert "memory_query" in prompt

    def test_contient_max_6(self):
        prompt = orch_mod.build_system_prompt()
        assert "développée" in prompt


# ─── strip_dsml (dupliqué dans react_loop, vérifier cohérence) ────────────────

class TestReactLoopStripDsml:
    """Vérifie que la fonction strip_dsml dans react_loop fonctionne comme celle
    d'utils. Les deux versions doivent être identiques."""

    def test_react_strip_dsml_fonctionne(self):
        from core.utils import strip_dsml as utils_clean
        text_with_tags = "<|DSML|>Bonjour<|/DSML|> monde"
        result = rl_mod.strip_dsml(text_with_tags)
        assert "DSML" not in result.upper() or not result.upper()
        # Vérifier cohérence
        assert result == utils_clean(text_with_tags)
