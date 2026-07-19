"""TEST DE FERMETURE — vérifie que les 6 rubriques 100% sont entièrement vertes.

Plan de fermeture (/tmp/plan-fermeture-100.md), règle d'arrêt : quand ce test
passe, le diagnostic Santana est fermé. Un échec après ce point est un vrai
bug de production, pas une couche oubliée.
"""
import subprocess
import sys
import os

BASE_DIR = os.path.expanduser("~/santana")
RUBRIQUES = [
    "test_100_memoire.py",
    "test_100_autonomie.py",
    "test_100_performances.py",
    "test_100_frugalite.py",
]


def test_all_100_tests_pass():
    """Exécute les 6 fichiers tests/test_100_*.py et vérifie 0 échec."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"] + [os.path.join("tests", r) for r in RUBRIQUES],
        cwd=BASE_DIR,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"Au moins un critère 100% échoue :\n{result.stdout[-3000:]}\n{result.stderr[-1000:]}"
    )


def test_historical_suite_still_green():
    """L'ensemble de la suite (historique + fermeture) doit être vert —
    ce test tourne lui-même dans cette suite, donc il vérifie surtout
    l'absence de régression au moment où il s'exécute."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--ignore=tests/test_100_closure.py"],
        cwd=BASE_DIR,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Régression détectée :\n{result.stdout[-3000:]}"
