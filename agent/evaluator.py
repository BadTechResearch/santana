"""evaluator.py — Auto-évaluation passive des réponses de Santana.

Évalue la qualité de chaque réponse (pertinence, ton, structure, troncature).
Stocke les scores en mémoire pour analyse et amélioration continue.
Pas de boucle corrective active — phase passive seulement.
"""

import json
import logging
import os
import re
import sqlite3
from datetime import datetime

BASE_DIR = os.path.expanduser("~/santana")


class EvaluationResult:
    """Résultat d'une évaluation de réponse."""

    def __init__(self, score: float, details: dict):
        self.score = score          # 0.0 à 1.0
        self.details = details      # {critere: note, ...}
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "details": self.details,
            "timestamp": self.timestamp,
        }

    def __repr__(self) -> str:
        return f"Eval({self.score:.2f}/{len(self.details)} critères)"


# ── Critères d'évaluation ─────────────────────────────────────────────

def _check_troncature(response: str) -> tuple[float, str]:
    """Vérifie si la réponse semble tronquée."""
    if not response:
        return 0.0, "réponse vide"
    # Indices de troncature
    troncature_signes = [
        response.endswith("[...]"),
        response.endswith("..."),
        response.endswith("…"),
        response.rstrip().endswith("..."),
        bool(re.search(r'\[.*\.\.\..*\]$', response)),
    ]
    if any(troncature_signes):
        return 0.3, "réponse probablement tronquée"
    # Phrases complètes : se termine par un point, point d'exclamation, etc.
    if response.rstrip() and response.rstrip()[-1] in ".!?":
        return 1.0, "terminaison correcte"
    return 0.7, "terminaison incertaine"


def _check_pertinence(response: str, query: str = "") -> tuple[float, str]:
    """Évalue si la réponse répond au sujet (basé sur présence de mots-clés)."""
    if not query:
        return 0.8, "pas de requête de référence"
    # Extraire les mots significatifs de la requête
    mots_requete = set(re.findall(r'\b\w+\b', query.lower()))
    mots_stop = {"le", "la", "les", "de", "du", "des", "un", "une", "et", "ou",
                 "pour", "sur", "dans", "avec", "est", "sont", "a", "ont", "je",
                 "tu", "il", "elle", "nous", "vous", "ils", "elles", "ce", "cet",
                 "cette", "ces", "mon", "ton", "son", "ma", "ta", "sa", "mes",
                 "tes", "ses", "qui", "que", "quoi", "dont", "ou"}
    mots_utiles = mots_requete - mots_stop
    if not mots_utiles:
        return 0.7, "pas assez de mots-clés dans la requête"
    # Compter les présences
    mots_trouves = sum(1 for m in mots_utiles if m in response.lower())
    ratio = mots_trouves / len(mots_utiles)
    if ratio >= 0.4:
        return min(1.0, ratio + 0.3), f"{mots_trouves}/{len(mots_utiles)} mots-clés présents"
    elif ratio >= 0.2:
        return 0.5, f"{mots_trouves}/{len(mots_utiles)} mots-clés (partiel)"
    return 0.3, f"{mots_trouves}/{len(mots_utiles)} mots-clés (faible)"


def _check_structure(response: str) -> tuple[float, str]:
    """Évalue la structure : présence de sections, listes, etc."""
    if not response or len(response) < 50:
        return 0.6, "réponse courte"
    score = 0.5
    raisons = []
    if re.search(r'## |### ', response):
        score += 0.2
        raisons.append("titres présents")
    if re.search(r'^- |^\* ', response, re.MULTILINE):
        score += 0.15
        raisons.append("listes présentes")
    if '|' in response and '---' in response:
        score += 0.15
        raisons.append("tableau présent")
    if not raisons:
        raisons.append("structure basique")
    return min(1.0, score), ", ".join(raisons)


def _check_ton(response: str) -> tuple[float, str]:
    """Vérifie que le ton respecte les règles (pas de flagornerie)."""
    if not response:
        return 0.5, "réponse vide"
    # Indices de flagornerie
    flagornerie = [
        "excellente question", "très bonne question", "great question",
        "je suis heureux", "je suis ravi", "i'd be happy",
        "c'est une excellente", "absolument", "parfaitement raison",
    ]
    for f in flagornerie:
        if f in response.lower():
            return 0.4, f"flagornerie détectée: '{f}'"
    # Ton direct
    if response.strip().startswith("**"):
        return 0.9, "ton direct (gras d'entrée)"
    return 0.8, "ton approprié"


def _check_longueur(response: str, query: str = "") -> tuple[float, str]:
    """Vérifie si la réponse est adaptée à la complexité de la question."""
    if not response:
        return 0.3, "réponse vide"
    len_resp = len(response)
    len_query = len(query) if query else 0
    if len_query < 20 and len_resp > 2000:
        return 0.5, f"question courte ({len_query}c) → réponse longue ({len_resp}c)"
    if len_query > 200 and len_resp < 100:
        return 0.3, f"question longue ({len_query}c) → réponse trop courte ({len_resp}c)"
    if len_resp < 20:
        return 0.4, "réponse trop courte"
    return 0.9, f"longueur adaptée ({len_resp}c)"


# ── Évaluation principale ─────────────────────────────────────────────

def evaluate_response(response: str, query: str = "") -> EvaluationResult:
    """Évalue une réponse de Santana selon plusieurs critères.

    Args:
        response: La réponse texte de Santana
        query: La requête utilisateur (optionnelle, pour pertinence)

    Returns:
        EvaluationResult avec score global et détails par critère
    """
    criteres = {
        "troncature": _check_troncature(response),
        "pertinence": _check_pertinence(response, query),
        "structure": _check_structure(response),
        "ton": _check_ton(response),
        "longueur": _check_longueur(response, query),
    }

    details = {k: {"note": v[0], "commentaire": v[1]} for k, v in criteres.items()}
    score = sum(v[0] for v in criteres.values()) / len(criteres)

    return EvaluationResult(score, details)


def evaluator_summary(result: EvaluationResult) -> str:
    """Génère un résumé lisible de l'évaluation."""
    emoji = "✅" if result.score >= 0.7 else "⚠️" if result.score >= 0.4 else "❌"
    lines = [
        f"**Évaluation : {emoji} {result.score:.0%}**",
    ]
    for critere, info in result.details.items():
        note = info["note"]
        emoji_c = "✅" if note >= 0.7 else "⚠️" if note >= 0.4 else "❌"
        lines.append(f"- {critere}: {emoji_c} {note:.0%} ({info['commentaire']})")
    return "\n".join(lines)


# ── Stockage des évaluations (SQLite, metrics.db) ─────────────────────

EVAL_DB = os.path.join(BASE_DIR, "metrics.db")
_EVAL_HISTORY: list[EvaluationResult] = []


def _load_history():
    """Charge l'historique depuis SQLite au démarrage."""
    global _EVAL_HISTORY
    try:
        conn = sqlite3.connect(EVAL_DB, timeout=5)
        c = conn.cursor()
        c.execute("SELECT score, message, reponse, timestamp, metriques FROM evaluations ORDER BY id DESC LIMIT 100")
        rows = c.fetchall()
        conn.close()
        _EVAL_HISTORY = []
        for score, message, reponse, ts, metriques in rows:
            details = json.loads(metriques) if metriques else {}
            result = EvaluationResult(score, details)
            result.timestamp = ts or ""
            _EVAL_HISTORY.append(result)
        _EVAL_HISTORY.reverse()
    except Exception as e:
        logging.warning(f"[EVAL] Load error: {e}")
        _EVAL_HISTORY = []


def _save_history():
    """Sauvegarde l'historique dans SQLite."""
    try:
        conn = sqlite3.connect(EVAL_DB, timeout=5)
        # Clear et réinsérer (max 100)
        conn.execute("DELETE FROM evaluations")
        for e in _EVAL_HISTORY[-100:]:
            d = e.to_dict()
            conn.execute(
                "INSERT INTO evaluations (score, message, reponse, timestamp, metriques) VALUES (?, ?, ?, ?, ?)",
                (d["score"], d.get("message", ""), d.get("reponse", ""),
                 d.get("timestamp", ""), json.dumps(d.get("details", {})))
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.warning(f"[EVAL] Save error: {e}")


# Charger au démarrage
_load_history()


def log_evaluation(result: EvaluationResult):
    """Stocke une évaluation en mémoire et sur disque."""
    _EVAL_HISTORY.append(result)
    # Garder max 100 évaluations
    while len(_EVAL_HISTORY) > 100:
        _EVAL_HISTORY.pop(0)
    _save_history()


def get_evaluation_stats() -> dict:
    """Retourne les stats des 100 dernières évaluations."""
    if not _EVAL_HISTORY:
        return {"moyenne": 0.0, "total": 0, "par_critere": {}}
    scores = [e.score for e in _EVAL_HISTORY]
    moyenne = sum(scores) / len(scores)
    # Stats par critère
    criteres = {}
    for e in _EVAL_HISTORY:
        for c, info in e.details.items():
            if c not in criteres:
                criteres[c] = []
            criteres[c].append(info["note"])
    par_critere = {c: sum(v)/len(v) for c, v in criteres.items()}
    return {
        "moyenne": round(moyenne, 3),
        "total": len(_EVAL_HISTORY),
        "par_critere": {c: round(v, 3) for c, v in par_critere.items()},
    }
