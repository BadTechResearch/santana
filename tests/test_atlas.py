"""Tests pour atlas_engine/atlas.py — fonctions de mémoire persistante.

Couverture :
- Fonctions pures de détection (sans modèle, sans DB)
- Fonctions de scoring (is_important, classification)
- Extraction d'entités (personnes, dates, émotions)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import re
from atlas_engine.atlas import (
    _contains_decision,
    _contains_important_info,
    _contains_idea,
    _is_important,
    _extract_persons,
    _extract_dates,
    _detect_emotion,
)


# ═══════════════════════════════════════════════════════════════════
# _contains_decision
# ═══════════════════════════════════════════════════════════════════

class TestContainsDecision:
    def test_je_decide(self):
        assert _contains_decision("Je décide de lancer le projet X")

    def test_je_choisis(self):
        assert _contains_decision("Je choisis Python pour ce projet")

    def test_on_va_faire(self):
        assert _contains_decision("OK on va faire une migration vers v3")

    def test_je_veux_absolument(self):
        assert _contains_decision("Je veux absolument finir ça cette semaine")

    def test_c_est_decide(self):
        assert _contains_decision("C'est décidé, on arrête le legacy")

    def test_j_ai_decide(self):
        assert _contains_decision("J'ai décidé de changer de stack")

    def test_nouveau_projet(self):
        assert _contains_decision("Nouveau projet : refonte du dashboard")

    def test_on_change(self):
        assert _contains_decision("On change de direction pour ce sprint")

    def test_je_lance(self):
        assert _contains_decision("Je lance le déploiement demain")

    def test_banal_pas_decision(self):
        assert not _contains_decision("Il fait beau aujourd'hui")

    def test_question_pas_decision(self):
        assert not _contains_decision("Quel temps fait-il ?")


# ═══════════════════════════════════════════════════════════════════
# _contains_important_info
# ═══════════════════════════════════════════════════════════════════

class TestContainsImportantInfo:
    def test_date_numerique(self):
        assert _contains_important_info("Rendez-vous le 15/06/2026")

    def test_date_texte(self):
        assert _contains_important_info("On se voit le 15 mars 2026")

    def test_aujourdhui(self):
        assert _contains_important_info("Aujourd'hui je commence le sprint")

    def test_demain(self):
        assert _contains_important_info("Demain c'est la release")

    def test_grand_chiffre(self):
        assert _contains_important_info("Budget : 5000€ pour le projet")

    def test_montant_monetaire(self):
        assert _contains_important_info("Budget total 5000$")

    def test_deux_noms_propres(self):
        assert _contains_important_info("Marie et Paul sont d'accord")

    def test_mot_cle_btr(self):
        assert _contains_important_info("Il faut mettre à jour le livre mémoire")

    def test_info_personnelle(self):
        assert _contains_important_info("Ma femme veut partir en voyage")

    def test_phrase_banale(self):
        assert not _contains_important_info("Je vais bien merci")

    def test_un_seul_nom_propre_stoplist(self):
        assert not _contains_important_info("Merci beaucoup pour ton aide")


# ═══════════════════════════════════════════════════════════════════
# _contains_idea
# ═══════════════════════════════════════════════════════════════════

class TestContainsIdea:
    def test_et_si_on(self):
        assert _contains_idea("Et si on ajoutait une API REST ?")

    def test_j_ai_une_idee(self):
        assert _contains_idea("J'ai une idée pour le nouveau module")

    def test_je_pense(self):
        assert _contains_idea("Je pense qu'on devrait refaire l'UI")

    def test_on_pourrait(self):
        assert _contains_idea("On pourrait essayer une approche différente")

    def test_bonne_idee(self):
        assert _contains_idea("C'est une bonne idée de stocker en local")

    def test_pas_idee(self):
        assert not _contains_idea("Je vais chercher du pain")


# ═══════════════════════════════════════════════════════════════════
# _is_important (scoring combiné)
# ═══════════════════════════════════════════════════════════════════

class TestIsImportant:
    def test_decision_seule_sauvegarde(self):
        """Une décision seule suffit à marquer comme important."""
        assert _is_important("Je lance le projet.", "OK je m'en occupe.")

    def test_info_seule_sauvegarde(self):
        assert _is_important("Le rendez-vous du 15 mars 2026 est confirmé.", "Noté.")

    def test_idee_longue_sauvegarde(self):
        assert _is_important(
            "Et si on ajoutait une fonctionnalité de recherche vectorielle ?",
            "Bonne idée, ça peut servir."
        )

    def test_salutation_banale_ignore(self):
        assert not _is_important("Merci !", "De rien.")

    def test_trop_court_ignore(self):
        assert not _is_important("Ok", "Super")

    def test_ok_court_ignore(self):
        assert not _is_important("ok", "parfait")


# ═══════════════════════════════════════════════════════════════════
# _extract_persons
# ═══════════════════════════════════════════════════════════════════

class TestExtractPersons:
    def test_conjoint(self):
        result = _extract_persons("Ma femme Sophie arrive demain")
        assert any(r["name"].lower() == "sophie" and r["relation"] == "conjoint" for r in result)

    def test_enfant(self):
        result = _extract_persons("Mon fils Léo a 5 ans")
        assert any(r["name"].lower() == "léo" and r["relation"] == "enfant" for r in result)

    def test_famille(self):
        result = _extract_persons("Maman vient dîner ce soir")
        assert any("maman" in r["name"].lower() for r in result)

    def test_fratrie(self):
        result = _extract_persons("Mon frère Marc est en ville")
        assert any(r["name"].lower() == "marc" and r["relation"] == "fratrie" for r in result)

    def test_pas_de_personne(self):
        result = _extract_persons("Il fait beau aujourd'hui")
        assert result == []

    def test_stoplist_exclue(self):
        result = _extract_persons("Je suis content du résultat")
        assert not any(r["name"].lower() == "content" for r in result)

    def test_deduplication(self):
        result = _extract_persons("Ma femme Sophie et mon épouse Sophie")
        assert sum(1 for r in result if r["name"].lower() == "sophie") == 1


# ═══════════════════════════════════════════════════════════════════
# _extract_dates
# ═══════════════════════════════════════════════════════════════════

class TestExtractDates:
    def test_date_complete(self):
        result = _extract_dates("Rendez-vous le 15 mars 2026")
        assert any("15" in d and "mars" in d for d in result)

    def test_aujourdhui(self):
        result = _extract_dates("Aujourd'hui je commence")
        assert any("aujourd" in d for d in result)

    def test_relatif(self):
        result = _extract_dates("Dans 3 jours on déploie")
        assert any("jours" in d or "3" in d for d in result)

    def test_aucune_date(self):
        result = _extract_dates("Ceci est un message banal")
        assert result == []

    def test_deduplication(self):
        result = _extract_dates("Le 15 mars 2026 et encore le 15 mars 2026")
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════
# _detect_emotion
# ═══════════════════════════════════════════════════════════════════

class TestDetectEmotion:
    def test_colere(self):
        assert _detect_emotion("Je suis en colère") == "colere"

    def test_frustration(self):
        assert _detect_emotion("J'en ai marre de cette latence") == "frustration"

    def test_tristesse(self):
        assert _detect_emotion("Je suis triste du résultat") == "tristesse"

    def test_joie(self):
        assert _detect_emotion("C'est génial !") == "joie"

    def test_fierte(self):
        assert _detect_emotion("Je suis fier de ce qu'on a accompli") == "fierte"

    def test_fatigue(self):
        assert _detect_emotion("Je suis crevé après cette journée") == "fatigue"

    def test_excitation(self):
        assert _detect_emotion("J'ai hâte de commencer !") == "excitation"

    def test_neutre(self):
        assert _detect_emotion("Le serveur est en ligne.") == "neutre"

    def test_premiere_emotion_gagne(self):
        """La première émotion détectée est retournée (ordre du dict)."""
        result = _detect_emotion("Je suis en colère et fatigué")
        # 'colere' vient avant 'fatigue' dans le dict
        assert result == "colere"
