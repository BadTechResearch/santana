"""Pattern Detection — F5 de la roadmap Santana.

Détection de routines, anomalies, modélisation utilisateur,
et correction lock-in (erreurs corrigées ne se reproduisent pas).

Stockage dans ~/santana/pattern_data.json
"""

import json
import logging
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

BASE_DIR = os.path.expanduser("~/santana")
DB_PATH = os.path.join(BASE_DIR, "metrics.db")
STATE_KEY = "pattern_data"


def _load() -> dict:
    """Charge depuis SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT value FROM tool_state WHERE key=?", (STATE_KEY,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception as e:
        logger.warning("[PATTERNS] Load error: %s", e)
    return {"interactions": [], "preferences": {}, "corrections": []}


def _save(data: dict) -> None:
    """Sauvegarde atomique dans SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute(
            "INSERT OR REPLACE INTO tool_state (key, value) VALUES (?, ?)",
            (STATE_KEY, json.dumps(data, ensure_ascii=False))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("[PATTERNS] Save error: %s", e)


# ─── 1. Analyse de routine ───────────────────────────────────────────────────


def record_interaction(timestamp: str, sujet: str, type_message: str) -> dict:
    """Enregistre une interaction utilisateur.

    Args:
        timestamp: Horodatage ISO (ex: "2026-06-14T10:30:00")
        sujet: Sujet ou mots-clés de l'interaction
        type_message: Type (question, commande, discussion, erreur, etc.)

    Returns:
        dict avec statut et nombre total d'interactions
    """
    data = _load()
    data.setdefault("interactions", [])

    # Normaliser le timestamp
    try:
        dt = datetime.fromisoformat(timestamp)
        ts_iso = dt.isoformat()
    except (ValueError, TypeError):
        ts_iso = timestamp or datetime.now().isoformat()

    entry = {
        "timestamp": ts_iso,
        "sujet": sujet.lower().strip(),
        "type_message": type_message.lower().strip(),
    }
    data["interactions"].append(entry)

    # Garder au maximum 5000 interactions
    if len(data["interactions"]) > 5000:
        data["interactions"] = data["interactions"][-5000:]

    _save(data)
    logger.debug("[PATTERNS] Interaction enregistrée: %s", sujet[:50])
    return {"status": "ok", "total_interactions": len(data["interactions"])}


def detect_routines(min_occurrences: int = 3) -> dict:
    """Détecte les séquences répétitives (même heure, même sujet).

    Regroupe les interactions par sujet et par heure approximative (fenêtre de 30 min),
    puis détecte celles qui apparaissent au moins min_occurrences fois
    sur des jours différents.

    Args:
        min_occurrences: Nombre minimum d'occurrences pour qualifier une routine

    Returns:
        dict avec routines détectées et statistiques
    """
    data = _load()
    interactions = data.get("interactions", [])

    if len(interactions) < min_occurrences:
        return {"routines": [], "total_interactions": len(interactions), "note": "Pas assez d'interactions"}

    # Grouper par (sujet, heure_approximative, jour_semaine)
    # heure_approximative = heure arrondie à 30 min (0 ou 30)
    groups = defaultdict(list)  # key: (sujet, heure_bloc, jour_semaine) -> list of timestamps

    for entry in interactions:
        try:
            dt = datetime.fromisoformat(entry["timestamp"])
        except (ValueError, TypeError):
            continue

        sujet = entry["sujet"]
        hour = dt.hour
        minute = dt.minute
        # Arrondir à la demi-heure la plus proche
        hour_bloc = f"{hour:02d}:{'30' if minute >= 30 else '00'}"
        jour = dt.strftime("%A")  # Monday, Tuesday, etc.
        key = (sujet, hour_bloc)
        groups[key].append(entry["timestamp"])

    routines = []
    for (sujet, hour_bloc), timestamps in groups.items():
        # Compter les jours distincts
        jours_distincts = set()
        for ts in timestamps:
            try:
                dt = datetime.fromisoformat(ts)
                jours_distincts.add(dt.strftime("%Y-%m-%d"))
            except (ValueError, TypeError):
                pass

        if len(jours_distincts) >= min_occurrences:
            routines.append({
                "sujet": sujet,
                "heure": hour_bloc,
                "occurrences": len(timestamps),
                "jours_distincts": len(jours_distincts),
                "derniere_occurrence": timestamps[-1] if timestamps else None,
            })

    # Trier par nombre d'occurrences décroissant
    routines.sort(key=lambda r: r["occurrences"], reverse=True)

    return {
        "routines": routines,
        "total_interactions": len(interactions),
        "seuil_min": min_occurrences,
    }


# ─── 2. Détection d'anomalie ─────────────────────────────────────────────────


def detect_anomalie(sujet: str, timestamp: str | None = None) -> dict:
    """Compare le comportement actuel aux patterns connus.

    Retourne un score d'anomalie entre 0.0 (normal) et 1.0 (très anormal).

    Logique :
    - Si le sujet n'a jamais été vu → anomalie forte (0.8)
    - Si le sujet est connu mais à une heure inhabituelle → anomalie modérée (0.5)
    - Si le sujet est connu et dans sa plage horaire → normal (0.0-0.2)
    - Si le type de message est "erreur" → bonus d'anomalie (+0.1)

    Args:
        sujet: Sujet de l'interaction actuelle
        timestamp: Horodatage ISO (défaut: maintenant)

    Returns:
        dict avec score_anomalie, raison, et contexte
    """
    sujet = sujet.lower().strip()
    if timestamp is None:
        dt = datetime.now()
        ts_iso = dt.isoformat()
    else:
        try:
            dt = datetime.fromisoformat(timestamp)
            ts_iso = dt.isoformat()
        except (ValueError, TypeError):
            dt = datetime.now()
            ts_iso = dt.isoformat()

    data = _load()
    interactions = data.get("interactions", [])

    if not interactions:
        return {
            "score_anomalie": 1.0,
            "raison": "Aucun historique — première interaction",
            "timestamp": ts_iso,
        }

    # Récupérer toutes les interactions avec le même sujet
    sujet_interactions = [
        i for i in interactions
        if i["sujet"] == sujet or sujet in i["sujet"] or i["sujet"] in sujet
    ]

    if not sujet_interactions:
        # Sujet jamais vu
        return {
            "score_anomalie": 0.8,
            "raison": f"Sujet inconnu: '{sujet[:80]}'",
            "timestamp": ts_iso,
            "total_interactions": len(interactions),
            "contexte": "Aucune interaction similaire trouvée",
        }

    # Vérifier si l'heure actuelle est dans la plage habituelle pour ce sujet
    current_hour_bloc = f"{dt.hour:02d}:{'30' if dt.minute >= 30 else '00'}"
    current_day = dt.strftime("%A")

    heures_connues = set()
    for entry in sujet_interactions:
        try:
            edt = datetime.fromisoformat(entry["timestamp"])
            eh = f"{edt.hour:02d}:{'30' if edt.minute >= 30 else '00'}"
            heures_connues.add(eh)
        except (ValueError, TypeError):
            pass

    if current_hour_bloc in heures_connues:
        score = 0.0  # Normal — sujet connu à cette heure
        raison = f"Sujet connu à {current_hour_bloc} ({len(heures_connues)} plages horaires connues)"
    else:
        # Sujet connu mais à une heure inhabituelle
        heures_list = sorted(heures_connues)
        score = 0.5
        raison = (
            f"Sujet connu mais heure inhabituelle (actuel: {current_hour_bloc}, "
            f"connu: {', '.join(heures_list[:5])})"
        )

    # Ajustement basé sur la fréquence récente
    recentes = [i for i in sujet_interactions if i["timestamp"] >= (dt - timedelta(hours=24)).isoformat()]
    if recentes:
        score = max(0.0, score - 0.1 * len(recentes))  # Plus le sujet est récent, moins c'est anormal

    score = round(min(1.0, max(0.0, score)), 3)

    return {
        "score_anomalie": score,
        "raison": raison,
        "timestamp": ts_iso,
        "plages_horaires_connues": sorted(heures_connues),
        "occurrences_sujet": len(sujet_interactions),
        "total_interactions": len(interactions),
    }


# ─── Sections 3-4 supprimées le 20 juin 2026 : record_preference,
# get_user_model, record_correction, get_corrections — tous morts.
