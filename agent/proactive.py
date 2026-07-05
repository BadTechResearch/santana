"""Proactive Engineering — F6 de la roadmap Santana.

Calibrage, timing, escalade et génération de suggestions proactives.
Stocke l'historique dans ~/santana/proactive_data.json
"""

import json
import logging
import os
import time
from datetime import datetime, time as dtime

logger = logging.getLogger(__name__)

BASE_DIR = os.path.expanduser("~/santana")
PROACTIVE_DB = os.path.join(BASE_DIR, "proactive_data.json")

# ─── Configuration ────────────────────────────────────────────────────────────

SUGGESTION_LIMIT_PER_HOUR = 1        # Max 1 suggestion par heure
URGENCE_SEUIL_BYPASS = 0.85          # Si urgence > ce seuil → pas de limite

FENETRE_MATIN = (dtime(8, 0), dtime(10, 0))    # 8h-10h
FENETRE_APREM = (dtime(14, 0), dtime(16, 0))   # 14h-16h

# Paliers d'escalade
SEUIL_ESCALADE_2 = 0.50   # Proposition directe
SEUIL_ESCALADE_3 = 0.70   # Notification
SEUIL_ESCALADE_4 = 0.85   # Alerte externe


# ─── Helpers JSON ────────────────────────────────────────────────────────────

def _load() -> dict:
    """Charge proactive_data.json ou retourne un dict vide."""
    try:
        if os.path.exists(PROACTIVE_DB):
            with open(PROACTIVE_DB, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.warning("[PROACTIVE] Load error: %s", e)
    return {"suggestions": []}


def _save(data: dict) -> None:
    """Sauvegarde dans proactive_data.json."""
    try:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(PROACTIVE_DB, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning("[PROACTIVE] Save error: %s", e)


# ─── 1. Calibrage ────────────────────────────────────────────────────────────

def can_suggest(urgence_score: float = 0.0, now: float | None = None) -> tuple[bool, str]:
    """Détermine si Santana peut émettre une suggestion proactive.

    1 suggestion max par heure, sauf si urgence_score > 0.85
    (dans ce cas, peut suggérer même si le quota horaire est dépassé).

    Args:
        urgence_score: Score d'urgence (0.0 à 1.0) du signal actuel
        now: Timestamp Unix (défaut: time.time())

    Returns:
        (peut_suggerer: bool, raison: str)
    """
    if now is None:
        now = time.time()

    data = _load()
    suggestions = data.get("suggestions", [])

    # Si urgence critique → bypass immédiat
    if urgence_score > URGENCE_SEUIL_BYPASS:
        return True, f"Urgence critique ({urgence_score:.2f} > {URGENCE_SEUIL_BYPASS}) — bypass du quota horaire"

    # Vérifier le quota horaire
    une_heure = 3600  # secondes
    seuil_horaire = now - une_heure

    suggestions_recentes = [
        s for s in suggestions
        if s.get("timestamp", 0) > seuil_horaire
    ]

    if len(suggestions_recentes) >= SUGGESTION_LIMIT_PER_HOUR:
        # Calculer quand le quota sera réinitialisé
        plus_recente = max(s["timestamp"] for s in suggestions_recentes)
        temps_restant = int(plus_recente + une_heure - now)
        minutes_restantes = max(1, temps_restant // 60)
        return False, (
            f"Quota horaire atteint ({len(suggestions_recentes)}/{SUGGESTION_LIMIT_PER_HOUR}). "
            f"Prochaine suggestion possible dans ~{minutes_restantes} min"
        )

    # Vérifier aussi la dernière suggestion (même si hors fenêtre d'une heure,
    # éviter le spam immédiat après reset)
    if suggestions:
        derniere = suggestions[-1]
        temps_depuis = now - derniere.get("timestamp", 0)
        if temps_depuis < 120:  # minimum 2 minutes entre deux suggestions
            return False, f"Trop tôt depuis la dernière suggestion ({int(temps_depuis)}s, minimum 120s)"

    return True, "Quota disponible"


# ─── 2. Timing ───────────────────────────────────────────────────────────────

def _est_dans_fenetre(heure: dtime, fenetre: tuple[dtime, dtime]) -> bool:
    """Vérifie si une heure est dans une fenêtre [début, fin[."""
    return fenetre[0] <= heure < fenetre[1]


def is_good_timing(timestamp: datetime | None = None) -> tuple[bool, str]:
    """Vérifie si l'heure actuelle est dans une fenêtre de réceptivité.

    Fenêtres : 8h-10h (matin) et 14h-16h (après-midi).

    Args:
        timestamp: Datetime à vérifier (défaut: maintenant)

    Returns:
        (bon_timing: bool, raison: str)
    """
    if timestamp is None:
        dt = datetime.now()
    elif isinstance(timestamp, datetime):
        dt = timestamp
    else:
        try:
            dt = datetime.fromisoformat(str(timestamp))
        except (ValueError, TypeError):
            dt = datetime.now()

    heure = dt.time()
    jour = dt.strftime("%A")
    heure_str = dt.strftime("%H:%M")

    # Week-end : toujours bon timing (réceptivité étendue)
    if jour in ("Saturday", "Sunday"):
        return True, f"Week-end ({jour}) — réceptivité étendue, pas de restriction horaire"

    if _est_dans_fenetre(heure, FENETRE_MATIN):
        return True, f"Fenêtre matin (8h-10h) — {heure_str}"

    if _est_dans_fenetre(heure, FENETRE_APREM):
        return True, f"Fenêtre après-midi (14h-16h) — {heure_str}"

    # Hors fenêtre
    if heure < FENETRE_MATIN[0]:
        return False, f"Hors fenêtre — avant 8h ({heure_str})"
    elif heure < FENETRE_APREM[0]:
        return False, f"Hors fenêtre — entre 10h et 14h ({heure_str})"
    else:
        return False, f"Hors fenêtre — après 16h ({heure_str})"


# ─── 3. Escalade ─────────────────────────────────────────────────────────────

def get_escalade_level(importance_score: float, urgent: bool = False) -> int:
    """Détermine le palier d'escalade d'une suggestion.

    Palier 1 : suggestion discrète (inline, pas de message séparé)
    Palier 2 : proposition directe (message dédié)
    Palier 3 : notification
    Palier 4 : alerte externe

    Args:
        importance_score: Score d'importance (0.0 à 1.0)
        urgent: Flag d'urgence manuel

    Returns:
        Niveau d'escalade (1 à 4)
    """
    if urgent:
        # Si explicitement urgent → minimum niveau 3
        score_base = max(importance_score, SEUIL_ESCALADE_3)
    else:
        score_base = importance_score

    if score_base >= SEUIL_ESCALADE_4:
        return 4
    elif score_base >= SEUIL_ESCALADE_3:
        return 3
    elif score_base >= SEUIL_ESCALADE_2:
        return 2
    else:
        return 1


def get_escalade_label(level: int) -> str:
    """Retourne le label lisible d'un niveau d'escalade."""
    labels = {
        1: "Suggestion discrète (inline)",
        2: "Proposition directe (message dédié)",
        3: "Notification",
        4: "Alerte externe",
    }
    return labels.get(level, f"Niveau {level}")


# ─── 4. Suggestion Builder ───────────────────────────────────────────────────

def build_suggestion(trigger: str, contexte: dict | None = None) -> dict:
    """Construit une suggestion proactive à partir d'un déclencheur.

    Args:
        trigger: Le déclencheur (pattern détecté, décision, anomalie, etc.)
        contexte: Contexte supplémentaire (optionnel)

    Returns:
        dict avec suggestion, niveau d'escalade, timestamp, etc.
    """
    if contexte is None:
        contexte = {}

    now = datetime.now()
    importance = contexte.get("importance_score", 0.5)
    urgent = contexte.get("urgent", False)
    sujet = contexte.get("sujet", trigger[:80])

    # Déterminer le niveau d'escalade
    level = get_escalade_level(importance, urgent)

    # Construire le message de suggestion selon le niveau
    prefix_map = {
        1: "💡 *Petite suggestion* :",
        2: "📌 *Proposition* :",
        3: "🔔 *À noter* :",
        4: "🚨 *Alerte* :",
    }

    # Générer la suggestion selon le type de trigger
    suggestion_text = _generate_suggestion_text(trigger, contexte)

    prefix = prefix_map.get(level, "💡 *Suggestion* :")

    # Enregistrer dans l'historique
    _record_suggestion(
        sujet=sujet,
        urgence_score=importance,
        escalade_level=level,
        suggestion=suggestion_text,
    )

    return {
        "suggestion": f"{prefix} {suggestion_text}",
        "niveau_escalade": level,
        "niveau_label": get_escalade_label(level),
        "sujet": sujet,
        "importance": importance,
        "urgent": urgent,
        "timestamp": now.isoformat(),
        "fenetre_receptive": is_good_timing(now)[0],
    }


def _generate_suggestion_text(trigger: str, contexte: dict) -> str:
    """Génère le texte de suggestion basé sur le type de déclencheur."""
    trigger_type = contexte.get("trigger_type", "general")

    if trigger_type == "routine":
        routine_info = contexte.get("routine", {})
        sujet = routine_info.get("sujet", trigger[:60])
        heure = routine_info.get("heure", "cette heure")
        return f"J'ai remarqué que vous travaillez souvent sur *{sujet}* à {heure}. Voulez-vous que je prépare quelque chose ?"

    elif trigger_type == "decision":
        decision = contexte.get("decision", "surveiller")
        score = contexte.get("importance_score", 0.0)
        if decision == "agir" and score > 0.7:
            return f"Ce sujet semble important (score: {score:.2f}). Je peux vous aider à agir dessus maintenant."
        elif decision == "surveiller":
            return f"Je surveille ce sujet pour vous. Je vous tiendrai au courant si ça évolue."
        else:
            return f"Ce sujet est noté. Je reste disponible si vous voulez en reparler."

    elif trigger_type == "anomalie":
        score = contexte.get("anomalie_score", 0.5)
        if score > 0.7:
            return f"Comportement inhabituel détecté (anomalie: {score:.2f}). Voulez-vous que j'investigue ?"
        else:
            return f"Léger écart par rapport à vos habitudes. Rien d'inquiétant, je garde un œil."

    elif trigger_type == "correction":
        erreur = contexte.get("erreur", "")
        return f"Je note cette correction pour ne pas reproduire l'erreur « {erreur[:60]} » à l'avenir."

    elif trigger_type == "preference":
        pref = contexte.get("preference", {})
        cle = pref.get("cle", "")
        valeur = pref.get("valeur", "")
        return f"J'ai enregistré votre préférence *{cle}* = *{valeur}*. Je m'y adapterai."

    else:
        # Suggestion générique : BLOQUÉE — 10 suggestions identiques dans l'historique
        # (audit Fable 5, 05/07). Un silence vaut mieux que du bruit inutile.
        return ""  # chaîne vide = ne rien envoyer


def _record_suggestion(sujet: str, urgence_score: float, escalade_level: int, suggestion: str) -> None:
    """Enregistre une suggestion dans l'historique."""
    data = _load()
    data.setdefault("suggestions", [])

    entry = {
        "timestamp": time.time(),
        "timestamp_iso": datetime.now().isoformat(),
        "sujet": sujet[:200],
        "urgence_score": round(urgence_score, 3),
        "escalade_level": escalade_level,
        "suggestion": suggestion[:500],
    }
    data["suggestions"].append(entry)

    # Garder au maximum 1000 suggestions
    if len(data["suggestions"]) > 1000:
        data["suggestions"] = data["suggestions"][-1000:]

    _save(data)
    logger.debug("[PROACTIVE] Suggestion enregistrée: niveau %d — %s", escalade_level, sujet[:50])


# ─── 5. Fonction orchestrateur ───────────────────────────────────────────────

def evaluate_proactive_opportunity(
    trigger: str,
    contexte: dict | None = None,
    urgence_score: float = 0.0,
    importance_score: float = 0.5,
    urgent: bool = False,
    now: datetime | None = None,
) -> dict:
    """Évalue si Santana doit émettre une suggestion proactive.

    Combine calibrage, timing, escalade et suggestion builder
    en une seule fonction pratique.

    Args:
        trigger: Le déclencheur (sujet, message, etc.)
        contexte: Contexte additionnel (trigger_type, routine, decision, etc.)
        urgence_score: Score d'urgence du signal (pour bypass quota)
        importance_score: Score d'importance (pour niveau d'escalade)
        urgent: Flag d'urgence manuel
        now: Datetime actuel (défaut: maintenant)

    Returns:
        dict complet avec décision et suggestion si applicable
    """
    if contexte is None:
        contexte = {}

    if now is None:
        now = datetime.now()

    contexte.setdefault("importance_score", importance_score)
    contexte.setdefault("urgent", urgent)
    contexte.setdefault("sujet", trigger[:80])

    now_ts = now.timestamp()

    # Étape 1 : Timing
    is_good, timing_reason = is_good_timing(now)

    # Étape 2 : Calibrage
    can_sug, calib_reason = can_suggest(urgence_score, now_ts)

    # Étape 3 : Escalade
    level = get_escalade_level(importance_score, urgent)

    # Cas spécial : urgence > 0.85 bypass le timing aussi
    if urgence_score > URGENCE_SEUIL_BYPASS:
        is_good = True
        timing_reason = f"Urgence critique ({urgence_score:.2f}) — bypass des fenêtres de réceptivité"

    # Étape 4 : Décision
    if can_sug and is_good:
        result = build_suggestion(trigger, contexte)
        # Bloquer les suggestions vides/génériques (audit Fable 5)
        if not result.get("suggestion", "").strip():
            return {"action": "ignorer", "blocages": ["suggestion vide/générique"]}
        result["calibrage_ok"] = True
        result["calibrage_raison"] = calib_reason
        result["timing_ok"] = True
        result["timing_raison"] = timing_reason
        result["action"] = "suggerer"
        return result

    # Ne peut pas suggérer — expliquer pourquoi
    blocages = []
    if not is_good:
        blocages.append(f"Timing: {timing_reason}")
    if not can_sug:
        blocages.append(f"Calibrage: {calib_reason}")

    return {
        "action": "ne_pas_suggerer",
        "calibrage_ok": can_sug,
        "calibrage_raison": calib_reason,
        "timing_ok": is_good,
        "timing_raison": timing_reason,
        "niveau_escalade": level,
        "niveau_label": get_escalade_label(level),
        "importance": importance_score,
        "urgence": urgence_score,
        "blocages": blocages,
        "timestamp": now.isoformat(),
    }


# ─── Stats retirées — get_proactive_stats était la seule fonction morte
# dans ce fichier. Les 4 helpers (can_suggest, is_good_timing, etc.)
# sont conservés car appelés par evaluate_proactive_opportunity.
