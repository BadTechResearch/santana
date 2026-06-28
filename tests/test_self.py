"""Tests pour agent/self.py — auto-connaissance dynamique de Santana."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.self import (
    scan_soul, scan_registry, scan_agent, scan_tests, scan_git, scan_system,
    build_identity, build_context, build_report,
)


class TestScanSoul:
    def test_retourne_dict(self):
        r = scan_soul()
        assert isinstance(r, dict)
        assert "SOUL.md" in r
        assert "RULES.md" in r

    def test_fichier_existant(self):
        r = scan_soul()
        soul = r.get("SOUL.md")
        assert soul is not None
        assert soul["taille"] > 0


class TestScanRegistry:
    def test_retourne_nombre_outils(self):
        r = scan_registry()
        assert isinstance(r, dict)
        assert r["total"] > 0

    def test_outils_sont_des_strings(self):
        r = scan_registry()
        for t in r["outils"]:
            assert isinstance(t, str)


class TestScanAgent:
    def test_retourne_modules(self):
        r = scan_agent()
        assert isinstance(r, dict)
        assert "orchestrator" in r
        assert "context" in r or "evaluator" in r or "self" in r

    def test_module_a_fonctions(self):
        r = scan_agent()
        if "orchestrator" in r:
            assert len(r["orchestrator"]["fonctions_publiques"]) > 0


class TestScanTests:
    def test_retourne_total(self):
        r = scan_tests()
        assert isinstance(r, dict)
        assert r["total"] >= 100  # On a 127 tests

    def test_fichiers_sont_listes(self):
        r = scan_tests()
        assert len(r["fichiers"]) > 0


class TestBuildIdentity:
    def test_retourne_toutes_cles(self):
        r = build_identity()
        for key in ["soul", "outils", "agent_modules", "tests", "git", "systeme"]:
            assert key in r, f"Clé manquante: {key}"

    def test_horodatage_present(self):
        r = build_identity()
        assert "horodatage" in r
        assert len(r["horodatage"]) > 10


class TestBuildContext:
    def test_retourne_string(self):
        r = build_context()
        assert isinstance(r, str)
        assert len(r) > 100

    def test_contient_outils(self):
        r = build_context()
        assert "OUTILS" in r

    def test_contient_tests(self):
        r = build_context()
        assert "TESTS" in r

    def test_contient_systeme(self):
        r = build_context()
        assert "SYSTEME" in r


class TestBuildReport:
    def test_retourne_markdown(self):
        r = build_report()
        assert isinstance(r, str)
        assert r.startswith("#")

    def test_contient_sections(self):
        r = build_report()
        for section in ["Personnalité", "Outils", "Modules", "Tests", "Git", "Système"]:
            assert section in r, f"Section manquante: {section}"
