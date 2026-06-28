"""Définition formelle du 100% — rubrique AUTONOMIE.

Plan de fermeture (/tmp/plan-fermeture-100.md). Distingue explicitement
l'infrastructure disponible (outils LLM) de l'automatisme réel (déclenchement
sans sollicitation de Serge).
"""
import ast
import inspect
import os

import pytest

BASE_DIR = os.path.expanduser("~/santana")
GUARDIAN_PATH = os.path.join(BASE_DIR, "tools", "guardian.py")


def test_guardian_exists():
    assert os.path.exists(GUARDIAN_PATH), "tools/guardian.py n'existe pas"
    with open(GUARDIAN_PATH) as f:
        lines = f.readlines()
    non_empty = [l for l in lines if l.strip()]
    assert len(non_empty) > 50, f"guardian.py trop court ({len(non_empty)} lignes non-vides)"


def test_guardian_not_noop():
    """Le module doit contenir une vraie logique, pas juste `pass`."""
    with open(GUARDIAN_PATH) as f:
        tree = ast.parse(f.read(), filename=GUARDIAN_PATH)

    func_defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert func_defs, "Aucune fonction définie dans guardian.py"

    trivial = 0
    for fn in func_defs:
        body = [n for n in fn.body if not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)]
        if len(body) <= 1 and all(isinstance(n, ast.Pass) for n in body):
            trivial += 1
    assert trivial < len(func_defs), "Toutes les fonctions de guardian.py sont des no-op"


def test_proactive_trigger():
    """Au moins un déclencheur temporel réel (boucle + sleep, ou cron/timer dédié)."""
    with open(GUARDIAN_PATH) as f:
        src = f.read()
    has_loop_trigger = ("asyncio.sleep" in src and ("while True" in src or "while not" in src))
    has_external_trigger = os.path.exists(os.path.join(BASE_DIR, "scripts", "guardian_cron.sh"))
    assert has_loop_trigger or has_external_trigger, "Aucun déclencheur temporel trouvé"


def test_guardian_imported():
    """santana.py importe vraiment guardian, sans retomber silencieusement sur un no-op."""
    santana_path = os.path.join(BASE_DIR, "santana.py")
    with open(santana_path) as f:
        src = f.read()
    assert "from tools.guardian import" in src
    assert "pas encore implémenté" not in src.lower() and "not yet implemented" not in src.lower()

    # L'import doit réellement réussir (pas de ImportError silencieux)
    import importlib
    mod = importlib.import_module("tools.guardian")
    assert hasattr(mod, "start_guardian")
    assert hasattr(mod, "start_watchdog")


def test_guardian_consults_decision_and_patterns():
    """Le guardian s'appuie sur les modules decision/patterns existants, pas une logique parallèle."""
    with open(GUARDIAN_PATH) as f:
        src = f.read()
    assert "agent.decision" in src or "agent.patterns" in src


def test_autonomy_documented():
    """Le niveau d'autonomie réel (automatique vs à la demande) est documenté."""
    arch_path = os.path.join(BASE_DIR, "ARCHITECTURE.md")
    claude_md_path = os.path.join(BASE_DIR, "CLAUDE.md")
    found = False
    for p in (arch_path, claude_md_path):
        if os.path.exists(p):
            with open(p) as f:
                content = f.read().lower()
            if "guardian" in content and ("automatique" in content or "autonomie" in content):
                found = True
    assert found, "Aucune doc ne décrit le niveau d'autonomie réel (ARCHITECTURE.md ou CLAUDE.md)"
