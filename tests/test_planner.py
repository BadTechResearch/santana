"""Tests pour agent/planner.py (Plan-and-Execute)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.planner import needs_planning, get_planning_instruction


class TestNeedsPlanning:
    def test_message_court(self):
        """Messages courts (< 40 chars) → pas de planification."""
        assert not needs_planning("Salut ça va ?")
        assert not needs_planning("OK merci")
        assert not needs_planning("oui")

    def test_message_long(self):
        """Messages longs (> 120 chars) → planification."""
        long_msg = "J'ai besoin que tu analyses en détail le marché des cryptomonnaies en RDC, les opportunités, les risques, et les régulations actuelles. Peux-tu aussi comparer avec les pays voisins ?"
        assert needs_planning(long_msg)

    def test_mot_cle_analyse(self):
        """Mot-clé 'analyse' → planification."""
        assert needs_planning("Analyse le code de react_loop.py")
        assert needs_planning("peux-tu analyser ce problème ?")

    def test_mot_cle_architecture(self):
        """Mot-clé 'architecture' → planification."""
        assert needs_planning("Décris l'architecture de Santana")
        assert needs_planning("Quelle est l'architecture cible ?")

    def test_mot_cle_projet(self):
        """Mot-clé 'projet' → planification."""
        assert needs_planning("J'ai un projet de site web")

    def test_mot_cle_code(self):
        """Mot-clé 'code' → planification."""
        assert needs_planning("Peux-tu m'écrire du code pour scraper ?")

    def test_message_moyen_sans_mot_cle(self):
        """Message de taille moyenne sans mot-clé → pas de planification."""
        msg = "Quel temps fait-il à Kinshasa aujourd'hui ?"
        assert not needs_planning(msg)

    def test_message_frontiere_120(self):
        """Message juste en dessous de 120 chars sans mot-clé."""
        msg = "A" * 119
        assert not needs_planning(msg)
        # À 120+ chars → planification
        msg2 = "A" * 121
        assert needs_planning(msg2)

    def test_message_vide(self):
        """Message vide → pas de planification."""
        assert not needs_planning("")
        assert not needs_planning("   ")

    def test_mot_cle_guide(self):
        """Mot-clé 'guide' → planification."""
        assert needs_planning("Fais-moi un guide pour installer Docker")


class TestGetPlanningInstruction:
    def test_retourne_string(self):
        """get_planning_instruction retourne une string non vide."""
        instruction = get_planning_instruction("test")
        assert isinstance(instruction, str)
        assert len(instruction) > 50

    def test_contient_plan_and_execute(self):
        """L'instruction contient les sections PLAN, EXÉCUTE, SYNTHÈSE."""
        instruction = get_planning_instruction("test")
        assert "PLAN" in instruction
        assert "EXÉCUTE" in instruction
        assert "SYNTHÈSE" in instruction

    def test_contient_serie_3_etapes(self):
        """L'instruction mentionne les 3 étapes : 1, 2, 3."""
        instruction = get_planning_instruction("test")
        assert "1." in instruction
        assert "2." in instruction
        assert "3." in instruction
