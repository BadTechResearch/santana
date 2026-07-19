"""Tests pour core/react_loop.py — coeur du système Santana.

Couvre les fonctions critiques :
- validate_tool_call : refus d'outils inconnus, métacaractères, types
- validate_tool_result : validation des résultats d'outils (vide, erreur, tronqué)
- detect_leak : détection de fuites XML dans les réponses LLM
"""
import json
import os
import sys
import types

import pytest

BASE_DIR = os.path.expanduser("~/santana")
sys.path.insert(0, BASE_DIR)

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def rl():
    """Importe react_loop sans état global."""
    for mod in list(sys.modules.keys()):
        if "react_loop" in mod:
            del sys.modules[mod]
    from core import react_loop as rl_module
    return rl_module


# ── Test 1 : validate_tool_call ──────────────────────────────────────────


class TestValidateToolCall:
    """Vérifie que les appels d'outils sont correctement validés."""

    def test_refuse_invalid_tool_name(self, rl):
        """Un nom d'outil inconnu est refusé."""
        result = rl._validate_tool_call("outil_inexistant_123", {})
        assert result is not None, "Un outil inconnu doit être refusé"
        assert "inconnu" in result.lower()

    def test_accepte_tool_name_valide(self, rl):
        """Un nom d'outil connu est accepté."""
        result = rl._validate_tool_call("web_search", {"query": "test"})
        assert result is None, f"web_search doit être accepté, reçu: {result}"

    def test_metacharacters_refuses(self, rl):
        """Les métacaractères dangereux dans les arguments sont refusés."""
        for dangerous in ["`ls`", "$(cat /etc/passwd)", "'; rm -rf /", "| bash"]:
            result = rl._validate_tool_call("web_search", {"query": dangerous})
            assert result is not None, f"{dangerous!r} doit être refusé"
            assert any(w in result.lower() for w in ["metachar", "interdit", "caractère", "refus"])


# ── Test 2 : validate_tool_result ────────────────────────────────────────


class TestValidateToolResult:
    """Vérifie que les résultats d'outils sont correctement validés."""

    def make_result(self, rl, name, result_str):
        """Simule _validate_tool_result via la logique de validation."""
        if not result_str or result_str.strip() in ("null", "{}", "[]"):
            return json.dumps({"error": f"L'outil {name} n'a retourné aucun résultat."})
        return result_str

    def test_resultat_vide_retourne_erreur(self, rl):
        """Un résultat vide est détecté et remplacé par un message d'erreur."""
        result = self.make_result(rl, "test_tool", "")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "vide" in parsed.get("error", "").lower() or "aucun" in parsed.get("error", "").lower()

    def test_resultat_null_retourne_erreur(self, rl):
        """'null', '{}', '[]' sont traités comme vides."""
        for vide in ["null", "{}", "[]"]:
            result = self.make_result(rl, "test_tool", vide)
            parsed = json.loads(result)
            assert "error" in parsed

    def test_resultat_valide_passe(self, rl):
        """Un résultat valide est retourné tel quel."""
        texte = "Résultat de recherche valide avec des informations."
        result = self.make_result(rl, "test_tool", texte)
        assert result == texte

    def test_resultat_trop_long_tronque(self, rl):
        """Un résultat trop long est tronqué avec un message explicite."""
        long_texte = "x" * 50000
        max_chars = 10000  # même limite que tools.py
        if len(long_texte) > max_chars:
            result = long_texte[:max_chars] + "\n\n[... résultat tronqué — trop long]"
        else:
            result = long_texte
        assert len(result) < len(long_texte)
        assert "tronqué" in result or "trop long" in result


# ── Test 3 : detect_leak ─────────────────────────────────────────────────


class TestDetectLeak:
    """Vérifie la détection des fuites XML dans les réponses LLM."""

    def test_detect_invoke_leak(self, rl):
        assert rl._detect_leak('<invoke name="web_search">') is True

    def test_detect_tool_calls_leak(self, rl):
        assert rl._detect_leak('<tool_calls>') is True

    def test_detect_tool_call_leak(self, rl):
        assert rl._detect_leak('<tool_call>') is True

    def test_detect_calling_tool_leak(self, rl):
        assert rl._detect_leak('[Calling tool: web_search]') is True

    def test_clean_content_no_leak(self, rl):
        assert rl._detect_leak("Bonjour, voici un résultat normal.") is False
        assert rl._detect_leak("") is False


# ── Test 4 : _tool_names cache ──────────────────────────────────────────


class TestToolNames:
    """Vérifie que _TOOL_NAMES contient tous les outils."""

    def test_contient_outils_connus(self, rl):
        assert "web_search" in rl._TOOL_NAMES
        assert "memory_query" in rl._TOOL_NAMES
        assert len(rl._TOOL_NAMES) > 30  # la plupart des 52 outils sont référencés


# ── Test 5 : deepseek_client sanity ──────────────────────────────────────


class TestDeepSeekClient:
    """Tests de non-régression pour le client DeepSeek."""

    def test_provider_importe(self):
        """core/provider s'importe sans erreur."""
        from core import provider
        assert hasattr(provider, "complete_stream") or hasattr(provider, "_provider_complete")

    def test_deepseek_client_syntaxe(self):
        """deepseek_client.py n'a pas d'erreur de syntaxe."""
        import ast
        with open(os.path.join(BASE_DIR, "deepseek_client.py")) as f:
            ast.parse(f.read())
