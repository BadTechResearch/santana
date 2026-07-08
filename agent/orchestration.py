"""Orchestration autonome — F7 de la roadmap Santana.

Enregistrement des résultats d'outils, détection d'échecs,
auto-réparation et notification.
Stockage SQLite (metrics.db) via core/db.get_metrics_db().

(Condensé le 20 juin 2026 : supprimé health_check, detect_propagation,
suggest_specialist, delegate_to, get_delegations, complete_delegation —
tous morts. Gardé : record_tool_result, tenter_reparation,
get_failure_status et leurs helpers.)
"""

import os, json
import logging
import threading
import sqlite3
import subprocess
from datetime import datetime

from core.db import get_metrics_db

logger = logging.getLogger(__name__)
_STATE_LOCK = threading.Lock()

STATE_KEY = "orchestration_failures"

FAILURE_THRESHOLD = 3

TOOL_COMPONENT = {
    "web_search": "reseau",
    "social_search": "reseau",
    "web_navigate": "navigate_server",
    "web_screenshot": "navigate_server",
    "vm_exec": "vm",
    "vm_exec_script": "vm",
    "run_code": "sandbox",
    "memory_query": "memory_db",
    "atlas": "memory_db",
}

COMPONENT_SERVICE = {
    "navigate_server": "santana-navigate",
}

# ─── Helpers JSON ────────────────────────────────────────────────────────────

def _load_failures() -> dict:
    """Charge l'état depuis SQLite (metrics.db)."""
    with _STATE_LOCK:
        try:
            conn = get_metrics_db()
            c = conn.cursor()
            c.execute("SELECT value FROM tool_state WHERE key=?", (STATE_KEY,))
            row = c.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.warning("[ORCHESTRATION] Load failures error: %s", e)
    return {"outils": {}, "reparations": []}


def _save_failures(state: dict) -> None:
    """Persiste l'état dans SQLite."""
    try:
        conn = get_metrics_db()
        conn.execute(
            "INSERT OR REPLACE INTO tool_state (key, value) VALUES (?, ?)",
            (STATE_KEY, json.dumps(state, ensure_ascii=False))
        )
        conn.commit()
    except Exception as e:
        logger.warning("[ORCHESTRATION] Save failures error: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-RÉPARATION (F12)
# ═══════════════════════════════════════════════════════════════════════════════

def _notifier_serge(message: str) -> bool:
    try:
        import urllib.request
        token = os.getenv("TELEGRAM_TOKEN", "").strip()
        chat_id = os.getenv("CHAT_ID", "0").strip()
        if not token or chat_id in ("", "0"):
            logger.warning("[ORCHESTRATION] Notif Serge impossible: TELEGRAM_TOKEN/CHAT_ID absent")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": int(chat_id), "text": message, "parse_mode": "MarkdownV2"}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = json.loads(r.read()).get("ok", False)
        return bool(ok)
    except Exception as e:
        logger.error("[ORCHESTRATION] Notif Serge échec: %s", e)
        return False


def tenter_reparation(tool_name: str, erreur: str = "") -> dict:
    composant = TOOL_COMPONENT.get(tool_name, "inconnu")
    actions: list[str] = []
    restart_ok = None

    logger.error(
        "[ORCHESTRATION] Auto-réparation déclenchée pour '%s' (composant=%s) après %d échecs: %s",
        tool_name, composant, FAILURE_THRESHOLD, erreur[:120],
    )
    actions.append(f"log: {FAILURE_THRESHOLD} échecs consécutifs de '{tool_name}'")

    service = COMPONENT_SERVICE.get(composant)
    if service:
        try:
            r = subprocess.run(
                ["systemctl", "--user", "restart", service],
                capture_output=True, text=True, timeout=20,
            )
            restart_ok = (r.returncode == 0)
            actions.append(
                f"restart {service}: {'réussi' if restart_ok else 'échec (' + r.stderr.strip()[:80] + ')'}"
            )
        except Exception as e:
            restart_ok = False
            actions.append(f"restart {service}: exception {e}")

    msg = (
        f"⚠️ Santana — auto-réparation\n"
        f"• Outil : `{tool_name}`\n"
        f"• Erreur : `{erreur[:200] or 'n/a'}`\n"
    )
    if restart_ok is True:
        msg += f"• ✅ Redémarrage automatique réussi"
    elif restart_ok is False:
        msg += f"• ❌ Redémarrage échoué — intervention requise"
    else:
        msg += "• ℹ️ Pas de redémarrage automatique"
    notifie = _notifier_serge(msg)
    actions.append("notification Serge: " + ("envoyée" if notifie else "échec/indispo"))

    rapport = {
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name,
        "composant": composant,
        "erreur": erreur[:200],
        "actions": actions,
        "notifie": notifie,
        "restart": restart_ok,
    }
    data = _load_failures()
    data.setdefault("reparations", []).append(rapport)
    data["reparations"] = data["reparations"][-200:]
    data.setdefault("outils", {})
    if tool_name in data["outils"]:
        data["outils"][tool_name]["consecutifs"] = 0
    _save_failures(data)

    try:
        from agent.tracabilite import log_action as _log_action
        _log_action("auto_reparation", f"Réparation outil {tool_name}", rapport)
    except Exception as _te:
        logger.debug("[ORCHESTRATION] tracabilite indisponible: %s", _te)

    return rapport


def record_tool_result(tool_name: str, success: bool, erreur: str = "") -> dict:
    if not tool_name:
        return {"tool": tool_name, "consecutifs": 0, "reparation_declenchee": False}

    data = _load_failures()
    outils = data.setdefault("outils", {})
    etat = outils.setdefault(tool_name, {
        "consecutifs": 0, "total_echecs": 0, "total_appels": 0, "derniere_erreur": "",
    })
    etat["total_appels"] += 1

    reparation_declenchee = False
    rapport = None

    if success:
        etat["consecutifs"] = 0
    else:
        etat["consecutifs"] += 1
        etat["total_echecs"] += 1
        etat["derniere_erreur"] = (erreur or "")[:200]
        logger.warning(
            "[ORCHESTRATION] Échec outil '%s' (%d consécutif·s)",
            tool_name, etat["consecutifs"],
        )

    _save_failures(data)

    if not success and etat["consecutifs"] >= FAILURE_THRESHOLD:
        reparation_declenchee = True
        rapport = tenter_reparation(tool_name, erreur)

    result = {
        "tool": tool_name,
        "consecutifs": 0 if reparation_declenchee else etat["consecutifs"],
        "reparation_declenchee": reparation_declenchee,
    }
    if rapport:
        result["rapport"] = rapport
    return result


def get_failure_status() -> dict:
    data = _load_failures()
    outils = data.get("outils", {})
    en_alerte = {
        name: etat for name, etat in outils.items()
        if etat.get("consecutifs", 0) > 0
    }
    return {
        "outils_suivis": len(outils),
        "outils_en_echec": en_alerte,
        "seuil": FAILURE_THRESHOLD,
        "reparations_recentes": data.get("reparations", [])[-20:],
        "total_reparations": len(data.get("reparations", [])),
    }
