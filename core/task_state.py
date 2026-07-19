"""task_state.py — Pile d'exécution persistante pour Santana.

Permet à Santana de savoir où elle s'est arrêtée entre deux messages.
Stocké dans la table ws (metrics.db) — même mécanisme que tool_workspace_state.
"""

import logging
import json
from datetime import datetime
from core.db import get_db

logger = logging.getLogger(__name__)

# Niveaux de sévérité (pour status rapide)
STATUS_ACTIVE = "▶️"
STATUS_DONE = "✅"
STATUS_FAILED = "❌"
STATUS_STALLED = "⏸️"


def set_task(label: str, step: str = "", detail: str = "", status: str = ""):
    """Enregistre la tâche en cours.
    
    Args:
        label: Nom court de la tâche (ex: "Audit Santana")
        step: Étape actuelle (ex: "Fix tests flaky")
        detail: Contexte libre
        status: Émoji de statut (▶️/✅/❌/⏸️)
    """
    try:
        now = datetime.now().isoformat(timespec="seconds")
        value = json.dumps({
            "label": label,
            "step": step,
            "detail": detail,
            "status": status or STATUS_ACTIVE,
            "updated_at": now,
        }, ensure_ascii=False)
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO ws (key, value, updated_at) VALUES (?, ?, ?)",
            ("current_task", value, now)
        )
        conn.commit()
        logger.info("[TASK] %s %s — %s", status or STATUS_ACTIVE, label, step)
    except Exception as e:
        logger.debug("[TASK] Erreur écriture: %s", e)


def get_task() -> dict | None:
    """Retourne la tâche en cours, ou None."""
    try:
        conn = get_db()
        row = conn.execute("SELECT value FROM ws WHERE key='current_task'").fetchone()
        if row:
            return json.loads(row[0])
        return None
    except Exception as e:
        logger.debug("[TASK] Erreur lecture: %s", e)
        return None


def clear_task():
    """Supprime current_task (tâche terminée)."""
    try:
        conn = get_db()
        conn.execute("DELETE FROM ws WHERE key='current_task'")
        conn.commit()
        logger.debug("[TASK] Tâche effacée")
    except Exception as e:
        logger.debug("[TASK] Erreur effacement: %s", e)


def resume_prompt() -> str:
    """Retourne un fragment de contexte pour injecter dans le prompt si 
    une tâche était en cours."""
    task = get_task()
    if not task:
        return ""
    label = task.get("label", "")
    step = task.get("step", "")
    detail = task.get("detail", "")
    updated = task.get("updated_at", "")
    parts = [f"[REPRISE] Tâche interrompue : {label}"]
    if step:
        parts.append(f"Étape : {step}")
    if detail:
        parts.append(f"Contexte : {detail[:200]}")
    if updated:
        parts.append(f"Dernière mise à jour : {updated}")
    return "\n".join(parts)
