"""
Loop Engineering — Auto-évolution frugale de Santana.

3 phases synchronisées avec le cycle de vie d'une réponse :
1. Pulse   → après chaque réponse, 3 métriques frugales
2. Digest  → hebdomadaire, archive et répare
3. Adapt   → si pattern d'erreur, skill correctif automatique

Conception : Option B (Santana écrit son propre hook)
"""

import os
import json
import logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PULSE_FILE = os.path.join(BASE_DIR, "..", "workspace", "pulse.json")
DIGEST_FILE = os.path.join(BASE_DIR, "..", "workspace", "digest.json")
MAX_CONSECUTIVE_ERRORS = 3
DIGEST_INTERVAL = 7  # jours

logger = logging.getLogger(__name__)


# ─── État persistant ──────────────────────────────────────────

def _load_state() -> dict:
    """Charge l'état depuis le fichier pulse.json."""
    if os.path.exists(PULSE_FILE):
        try:
            with open(PULSE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            # Migration : adapt_triggers doit être un dict, pas une liste
            if isinstance(state.get("adapt_triggers"), list):
                state["adapt_triggers"] = {}
                logger.warning("[EVOLVE] Migration adapt_triggers: list → dict")
            # Migration : recent_errors doit être une liste de dicts
            if isinstance(state.get("recent_errors"), dict):
                state["recent_errors"] = list(state["recent_errors"].values())
                logger.warning("[EVOLVE] Migration recent_errors: dict → list")
            return state
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"[EVOLVE] Load error: {e}")
    return {}


def _save_state(state: dict) -> None:
    """Sauvegarde l'état dans pulse.json."""
    try:
        os.makedirs(os.path.dirname(PULSE_FILE), exist_ok=True)
        with open(PULSE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        logger.error(f"[EVOLVE] Save error: {e}")


# ─── Phase 1 : Pulse ──────────────────────────────────────────

def pulse(response: str, user_message: str, tools_used: list) -> None:
    """Enregistre le pouls après chaque réponse. 3 métriques max."""
    now = datetime.now().isoformat()
    state = _load_state()
    # Migrer l'ancien format (dict) → int si nécessaire
    old_count = state.get("tools_count", 0)
    if isinstance(old_count, dict):
        old_count = sum(old_count.values()) if old_count else 0
    state["total_responses"] = (state.get("total_responses") or 0) + 1
    state["last_activity"] = now
    state["tools_count"] = old_count + len(tools_used or [])

    log = state.setdefault("interaction_log", [])
    # tools_used peut être un set[str] (noms d'outils) ou une list[dict] avec clé "name"
    if tools_used:
        if isinstance(next(iter(tools_used)), str):
            tool_names = list(tools_used)
        else:
            tool_names = [t.get("name", "?") for t in tools_used]
    else:
        tool_names = []
    log.append({
        "timestamp": now,
        "user_msg_len": len(user_message),
        "response_len": len(response),
        "tools": tool_names,
    })
    if len(log) > 100:
        state["interaction_log"] = log[-100:]

    _save_state(state)
    _check_digest_needed(state)


def pulse_error(tool_name: str, error_preview: str) -> None:
    """Enregistre une erreur outil pour détection de pattern."""
    state = _load_state()
    recent = state.setdefault("recent_errors", [])
    recent.append({
        "tool": tool_name,
        "error": error_preview[:200],
        "timestamp": datetime.now().isoformat(),
    })
    if len(recent) > 50:
        state["recent_errors"] = recent[-50:]
    _save_state(state)
    _check_adapt_trigger(state)


# ─── Phase 2 : Digest ─────────────────────────────────────────

def _check_digest_needed(state: dict) -> None:
    """Vérifie si un digest hebdomadaire est nécessaire."""
    last_digest_str = state.get("last_digest")
    if last_digest_str:
        try:
            last_digest = datetime.fromisoformat(last_digest_str)
            if (datetime.now() - last_digest).days < DIGEST_INTERVAL:
                return
        except (ValueError, TypeError):
            pass
    logger.info(f"[EVOLVE] Digest hebdomadaire requis (dernier: {last_digest_str})")
    state["digest_pending"] = True
    _save_state(state)


def run_digest() -> str:
    """Exécute le digest : archive, nettoie, résout les triggers."""
    state = _load_state()
    now = datetime.now().isoformat()

    history = state.setdefault("digest_history", [])
    history.append({
        "timestamp": now,
        "total_responses": state.get("total_responses", 0),
        "tools_count": state.get("tools_count", 0),
        "triggers": dict(state.get("adapt_triggers", {})),
    })
    if len(history) > 52:
        state["digest_history"] = history[-52:]

    triggers = state.get("adapt_triggers", {})
    resolved = []
    skills_created = []
    for tool, trigger in list(triggers.items()):
        skill_name = f"evite-erreur-{tool}"
        resolved.append(tool)
        skills_created.append(skill_name)

    state["recent_errors"] = []
    state["adapt_triggers"] = {}
    state["digest_pending"] = False
    state["last_digest"] = now

    _save_state(state)

    msg = (
        f"Digest {now} : "
        f"{state.get('total_responses', 0)} réponses, "
        f"{state.get('tools_count', 0)} outils, "
        f"{len(resolved)} triggers traités"
    )
    if skills_created:
        msg += f", skills créées: {', '.join(skills_created)}"
    return msg


# ─── Phase 3 : Adapt ──────────────────────────────────────────

def _check_adapt_trigger(state: dict) -> None:
    """Phase Adapt : détection de pattern → création de skill."""
    errors = state.get("recent_errors", [])
    # Compter erreurs consécutives par outil
    tool_error_count: dict[str, int] = {}
    for err in errors:
        t = err.get("tool", "unknown")
        tool_error_count[t] = tool_error_count.get(t, 0) + 1

    for tool, count in tool_error_count.items():
        if count >= MAX_CONSECUTIVE_ERRORS:
            logger.warning(
                f"[EVOLVE] Pattern : {count} erreurs consécutives sur {tool}"
            )
            triggers = state.setdefault("adapt_triggers", {})
            if tool not in triggers:
                triggers[tool] = {
                    "consecutive_errors": count,
                    "error": errors[-1].get("error", "") if errors else "",
                    "detected_at": datetime.now().isoformat(),
                }
                _save_state(state)


# ─── Requêtes ─────────────────────────────────────────────────

def get_pulse_summary() -> str:
    """Résumé lisible du pouls (pour injection dans prompt si pertinent)."""
    state = _load_state()
    total = state.get("total_responses", 0)
    last = state.get("last_activity", "jamais")
    tools = state.get("tools_count", 0)
    errs = len(state.get("recent_errors", []))
    pending = state.get("digest_pending", False)

    summary = f"Pouls: {total} réponses, {tools} outils, {errs} erreurs"
    if pending:
        summary += " [Digest en attente]"
    return summary


def get_state() -> dict:
    """Retourne l'état complet (pour debug/inspection)."""
    return _load_state()
