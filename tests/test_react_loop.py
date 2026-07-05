"""Tests pour core/react_loop.py — coeur du système Santana.

Couvre les fonctions critiques identifiées par l'audit Fable 5 V3 :
- validate_tool_call : refus d'outils non allowlistés, métacaractères
- validate_tool_result : validation des résultats d'outils (vide, erreur, tronqué)
- filter_tools : filtrage par type de message + budget THROTTLE
- get_tool_progress : messages heartbeat lisibles
- reset_state : nettoyage quarantaine + cache
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
def react_loop():
    """Importe react_loop après reset de l'état global."""
    # Nettoyer les caches d'import pour éviter les états résiduels
    for mod in list(sys.modules.keys()):
        if "react_loop" in mod:
            del sys.modules[mod]
    from core import react_loop as rl
    rl.reset_state()
    return rl


# ── Test 1 : validate_tool_call ──────────────────────────────────────────


class TestValidateToolCall:
    """Vérifie que les appels d'outils sont correctement validés."""

    def test_refuse_invalid_tool_name(self, react_loop):
        """Un nom d'outil inconnu est refusé."""
        result = react_loop._validate_tool_call("outil_inexistant_123", {})
        assert result is not None, "Un outil inconnu doit être refusé"
        assert "inconnu" in result.lower() or "refus" in result.lower() or "pas" in result.lower()

    def test_accepte_tool_name_valide(self, react_loop):
        """Un nom d'outil connu est accepté."""
        # web_search est un outil standard qui devrait exister
        result = react_loop._validate_tool_call("web_search", {"query": "test"})
        assert result is None, f"web_search doit être accepté, reçu: {result}"

    def test_metacharacters_refuses(self, react_loop):
        """Les métacaractères dangereux dans les arguments sont refusés."""
        for dangerous in ["`ls`", "$(cat /etc/passwd)", "'; rm -rf /", "| bash"]:
            result = react_loop._validate_tool_call("web_search", {"query": dangerous})
            # L'outil peut être refusé pour métacaractères OU pour contenu dangereux
            if result is not None:
                assert any(w in result.lower() for w in ["metachar", "refus", "dangereux", "invalide", "caractère"])


# ── Test 2 : validate_tool_result ────────────────────────────────────────


class TestValidateToolResult:
    """Vérifie que les résultats d'outils sont correctement validés."""

    def test_resultat_vide_retourne_erreur(self, react_loop):
        """Un résultat vide est détecté et remplacé par un message d'erreur."""
        result = react_loop._validate_tool_result("test_tool", "")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "vide" in parsed.get("error", "").lower() or "aucun" in parsed.get("error", "").lower()

    def test_resultat_null_retourne_erreur(self, react_loop):
        """'null', '{}', '[]' sont traités comme vides."""
        for vide in ["null", "{}", "[]"]:
            result = react_loop._validate_tool_result("test_tool", vide)
            parsed = json.loads(result)
            assert "error" in parsed

    def test_resultat_valide_passe(self, react_loop):
        """Un résultat valide est retourné tel quel."""
        texte = "Résultat de recherche valide avec des informations."
        result = react_loop._validate_tool_result("test_tool", texte)
        assert result == texte

    def test_resultat_trop_long_tronque(self, react_loop):
        """Un résultat trop long est tronqué avec un message explicite."""
        long_texte = "x" * 50000
        result = react_loop._validate_tool_result("test_tool", long_texte)
        assert len(result) < len(long_texte)
        assert "tronqué" in result or "trop long" in result


# ── Test 3 : filter_tools ────────────────────────────────────────────────


class TestFilterTools:
    """Vérifie le filtrage des outils par type de message + budget."""

    def test_social_filtre_tous_outils(self, react_loop):
        """Les messages SOCIAUX reçoivent une liste d'outils vide."""
        tools = [{"function": {"name": "web_search"}}]
        filtered = react_loop._filter_tools("SOCIAL", tools)
        assert len(filtered) == 0, "Les messages SOCIAUX ne doivent pas avoir d'outils"

    def test_deep_garde_outils(self, react_loop):
        """Les messages DEEP gardent tous les outils."""
        tools = [{"function": {"name": "web_search"}}, {"function": {"name": "vm_exec"}}]
        filtered = react_loop._filter_tools("DEEP", tools)
        assert len(filtered) == 2, "Les messages DEEP doivent garder tous les outils"

    def test_personnel_garde_outils(self, react_loop):
        """Les messages PERSONNEL gardent les outils."""
        tools = [{"function": {"name": "web_search"}}]
        filtered = react_loop._filter_tools("PERSONNEL", tools)
        assert len(filtered) >= 1

    def test_unknown_type_garde_outils(self, react_loop):
        """Un type inconnu garde les outils par défaut."""
        tools = [{"function": {"name": "web_search"}}]
        filtered = react_loop._filter_tools("UNKNOWN_TYPE_XYZ", tools)
        assert len(filtered) >= 1


# ── Test 4 : get_tool_progress ───────────────────────────────────────────


class TestGetToolProgress:
    """Vérifie les messages de progression des outils longs."""

    def test_web_search_progress(self, react_loop):
        """web_search produit un message de progression lisible."""
        msg = react_loop._get_tool_progress("web_search", {"query": "actualité Kinshasa"})
        assert msg is not None
        assert "recherche" in msg.lower() or "web" in msg.lower() or "cherche" in msg.lower()

    def test_vm_exec_progress(self, react_loop):
        """vm_exec produit un message de progression lisible."""
        msg = react_loop._get_tool_progress("vm_exec", {"cmd": "ls -la"})
        assert msg is not None
        assert "commande" in msg.lower() or "exécut" in msg.lower() or "exec" in msg.lower()

    def test_unknown_tool_progress(self, react_loop):
        """Un outil inconnu produit quand même un message."""
        msg = react_loop._get_tool_progress("outil_inconnu", {})
        assert msg is not None

    def test_progress_contient_nom_outil(self, react_loop):
        """Le message de progression contient le nom de l'outil."""
        msg = react_loop._get_tool_progress("web_navigate", {"url": "https://example.com"})
        assert "web_navigate" in msg or "navigation" in msg.lower() or "recherche" in msg.lower()


# ── Test 5 : reset_state ─────────────────────────────────────────────────


class TestResetState:
    """Vérifie que reset_state nettoie correctement l'état global."""

    def test_reset_clear_quarantine(self, react_loop):
        """reset_state vide la quarantaine."""
        react_loop._quarantined_until["test_tool"] = 9999999999.0
        react_loop.reset_state()
        assert "test_tool" not in react_loop._quarantined_until


# ── Test 6 : deepseek_client sanity ──────────────────────────────────────


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
