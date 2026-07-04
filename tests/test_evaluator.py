"""Tests pour agent/evaluator.py — auto-évaluation passive des réponses Santana."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agent.evaluator import (
    evaluate_response,
    evaluator_summary,
    get_evaluation_stats,
    log_evaluation,
    EvaluationResult,
)


@pytest.fixture(autouse=True)
def _isolate_eval_file(tmp_path, monkeypatch):
    """Empêche les tests d'écrire dans le vrai metrics.db.

    agent/evaluator.py utilise désormais core.db.get_metrics_db() (connexion
    partagée, schéma auto-créé) — on isole en repointant core.db.METRICS_DB
    vers un fichier temporaire et en forçant une nouvelle connexion
    thread-locale, plutôt que de monkeypatcher un EVAL_DB qui n'existe plus.
    """
    import core.db as db
    import agent.evaluator as evaluator
    monkeypatch.setattr(db, "METRICS_DB", str(tmp_path / "test_eval.db"))
    monkeypatch.setattr(db, "_local", __import__("threading").local())
    monkeypatch.setattr(evaluator, "_EVAL_HISTORY", [])


class TestEvaluationResult:
    def test_creation(self):
        r = EvaluationResult(0.85, {"troncature": {"note": 1.0, "commentaire": "ok"}})
        assert r.score == 0.85
        assert "troncature" in r.details
        assert r.timestamp is not None

    def test_to_dict(self):
        r = EvaluationResult(0.5, {"test": {"note": 0.5, "commentaire": "moyen"}})
        d = r.to_dict()
        assert d["score"] == 0.5
        assert d["details"]["test"]["note"] == 0.5


class TestCheckTroncature:
    def test_reponse_normale(self):
        from agent.evaluator import _check_troncature
        note, _ = _check_troncature("Voici une réponse complète qui se termine par un point.")
        assert note == 1.0

    def test_reponse_tronquee(self):
        from agent.evaluator import _check_troncature
        note, _ = _check_troncature("Ceci est une réponse qui a été coupée[...]")
        assert note <= 0.4

    def test_reponse_vide(self):
        from agent.evaluator import _check_troncature
        note, _ = _check_troncature("")
        assert note == 0.0


class TestCheckFlagornerie:
    def test_flagornerie_detectee(self):
        from agent.evaluator import _check_ton
        note, msg = _check_ton("Excellente question ! Laisse-moi t'aider.")
        assert note <= 0.5
        assert "flagornerie" in msg

    def test_ton_direct(self):
        from agent.evaluator import _check_ton
        note, _ = _check_ton("**Non, tu as tort sur ce point.**")
        assert note >= 0.8


class TestEvaluateResponse:
    def test_reponse_complete(self):
        result = evaluate_response(
            "**Analyse.** Le secteur minier congolais domine l'économie.",
            "économie congolaise"
        )
        assert isinstance(result, EvaluationResult)
        assert 0.0 <= result.score <= 1.0
        assert len(result.details) >= 4

    def test_reponse_vide(self):
        result = evaluate_response("", "test")
        assert result.score < 0.5

    def test_sans_requete(self):
        result = evaluate_response("Bonjour.")
        assert result.score >= 0.4


class TestEvaluatorSummary:
    def test_resume_contient_score(self):
        r = evaluate_response("Réponse test.", "test")
        s = evaluator_summary(r)
        assert str(int(r.score * 100)) in s

    def test_resume_contient_emoji(self):
        r = evaluate_response("Réponse test.", "test")
        s = evaluator_summary(r)
        assert "✅" in s or "⚠️" in s or "❌" in s


class TestEvaluationHistory:
    def test_log_and_stats(self):
        # Reset
        from agent.evaluator import _EVAL_HISTORY
        _EVAL_HISTORY.clear()

        log_evaluation(EvaluationResult(0.9, {"a": {"note": 0.9, "c": "ok"}}))
        log_evaluation(EvaluationResult(0.5, {"a": {"note": 0.5, "c": "bof"}}))
        stats = get_evaluation_stats()
        assert stats["total"] == 2
        assert 0.6 < stats["moyenne"] < 0.8

    def test_max_history(self):
        from agent.evaluator import _EVAL_HISTORY
        _EVAL_HISTORY.clear()
        for i in range(150):
            log_evaluation(EvaluationResult(0.5, {"test": {"note": 0.5, "c": ""}}))
        assert len(_EVAL_HISTORY) <= 100

    def test_stats_empty(self):
        from agent.evaluator import _EVAL_HISTORY
        _EVAL_HISTORY.clear()
        stats = get_evaluation_stats()
        assert stats["total"] == 0
        assert stats["moyenne"] == 0.0
