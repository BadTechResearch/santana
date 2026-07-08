


_LAST_AUDIT_STATUS = []
_LAST_AUDIT_TIME = 0


def _check_metrics_integrity() -> list:
    """Vérifie la cohérence interne des métriques Santana."""
    anomalies = []
    try:
        from core.db import get_metrics_db
        conn = get_metrics_db()

        # 1. Table metrics non vide
        m = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        from datetime import datetime
        if m == 0 and datetime.now().day > 1:
            anomalies.append("Table metrics VIDE — record_usage() n'écrit pas dans metrics.db")

        # 2. token_count non nul dans message_latency
        zeros = conn.execute(
            "SELECT COUNT(*) FROM message_latency WHERE token_count = 0 AND total_ms > 1000"
        ).fetchone()[0]
        if zeros > 10:
            anomalies.append(f"{zeros} entrées message_latency avec token_count=0")

        # 3. Souveraineté vs message_latency
        api_calls = conn.execute(
            "SELECT COUNT(*) FROM souverainete WHERE host='api.deepseek.com'"
        ).fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM message_latency").fetchone()[0]
        if messages > 5 and api_calls < messages:
            anomalies.append(f"Souveraineté ({api_calls}) < messages ({messages})")

        # 4. Erreurs en croissance
        errs = conn.execute("SELECT SUM(count) FROM errors").fetchone()[0] or 0
        if errs > 100:
            anomalies.append(f"{errs} erreurs cumulées")

    except Exception as e:
        anomalies.append(f"Erreur vérification métriques: {e}")

    return anomalies


def _run_audit_watchdog():
    """Exécute périodiquement les vérifications d'intégrité."""
    global _LAST_AUDIT_STATUS, _LAST_AUDIT_TIME
    try:
        anomalies = _check_metrics_integrity()
        _LAST_AUDIT_STATUS = anomalies
        _LAST_AUDIT_TIME = __import__('time').time()
        for a in anomalies:
            logger.warning("[AUDIT] ⚠️ %s", a)
        if not anomalies:
            logger.debug("[AUDIT] ✅ Toutes les métriques cohérentes")
    except Exception as e:
        logger.error("[AUDIT] Échec watchdog intégrité: %s", e)


def get_audit_report() -> str:
    """Retourne le rapport d'audit formaté pour /audit."""
    checks = []
    try:
        from core.db import get_metrics_db
        conn = get_metrics_db()

        # Métriques
        m = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        checks.append(("✅" if m > 0 else "⚠️", f"metrics.db écritures: {m}"))

        zeros = conn.execute(
            "SELECT COUNT(*) FROM message_latency WHERE token_count = 0 AND total_ms > 1000"
        ).fetchone()[0]
        checks.append(("✅" if zeros < 10 else "⚠️", f"token_count=0: {zeros}"))

        from core import provider_manager as pm
        prov = pm.get_active_provider()
        checks.append(("✅", f"Provider: {prov}"))

        errs = conn.execute("SELECT SUM(count) FROM errors").fetchone()[0] or 0
        checks.append(("✅" if errs < 5 else "⚠️", f"Erreurs outils: {errs}"))

        api = conn.execute(
            "SELECT COUNT(*) FROM souverainete WHERE host='api.deepseek.com'"
        ).fetchone()[0]
        msgs = conn.execute("SELECT COUNT(*) FROM message_latency").fetchone()[0]
        ratio = f"{api}/{msgs}" if msgs else "N/A"
        checks.append(("✅" if api >= msgs else "⚠️", f"API/Message ratio: {ratio}"))

        from tools.cost_governor import get_status
        cost = get_status()
        checks.append(("✅", f"Budget: ${cost['cout_cumule_reel']:.4f} / ${cost['budget']:.2f} ({cost['niveau']})"))

    except Exception as e:
        checks.append(("❌", f"Erreur audit: {e}"))

    footer = ""
    if _LAST_AUDIT_STATUS:
        footer = "\n⚠️ Anomalies detectees:" if _LAST_AUDIT_STATUS else "\n✅ Auto-verification: OK"

    header = f"📊 **Audit Santana**\n"
    result = header + "\n".join(f"{s} {t}" for s, t in checks) + footer
    return result

"""Guardian — autonomie réelle de Santana.

Jusqu'ici, `agent/decision.py`, `agent/patterns.py` et `agent/proactive.py`
n'étaient consultés que sur demande explicite, via les outils LLM
(decision_analyze, pattern_analyze, proactive_suggest) — jamais déclenchés
sans que Serge ou le LLM n'initie l'appel. Ce module connecte cette
infrastructure déjà construite à un vrai déclencheur temporel : une boucle
de fond, indépendante de toute conversation, qui s'exécute toutes les
GUARDIAN_INTERVAL_SECONDS.

Deux responsabilités distinctes :
- start_watchdog(wd_ctx)  : santé interne réelle (DB, outils en échec
  consécutif) — complète le ping systemd brut de santana.py:_watchdog_ping(),
  qui confirme seulement que le process tourne, pas qu'il fonctionne.
- start_guardian()        : évalue périodiquement une opportunité de
  suggestion proactive à partir des routines détectées, et l'envoie à Serge
  sur Telegram SANS qu'il l'ait demandée — la seule action vraiment autonome
  de Santana à ce jour.
"""
import asyncio
import logging
import os

import requests

logger = logging.getLogger(__name__)

GUARDIAN_INTERVAL_SECONDS = int(os.getenv("GUARDIAN_INTERVAL_SECONDS", "1800"))  # 30 min
WATCHDOG_INTERVAL_SECONDS = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "60"))
_HEALTH_FAILURES_BEFORE_ALERT = 3


def _send_telegram(text: str) -> bool:
    """Envoie un message Telegram à Serge, indépendamment de la boucle
    react_loop — c'est ce qui rend l'action proactive (pas une réponse)."""
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("[GUARDIAN] TELEGRAM_TOKEN/CHAT_ID absents de .env — message non envoyé")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.error(f"[GUARDIAN] Envoi Telegram échoué: {e}")
        return False


def _check_internal_health() -> tuple[bool, str]:
    """Santana peut être 'vivant' (process actif, ping systemd OK) tout en
    étant cassé (DB inaccessible, outil bloqué en échec répété). Vérifie le
    second cas, que le ping systemd brut ne détecte jamais."""
    try:
        from core.db import get_db
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
    except Exception as e:
        return False, f"DB inaccessible: {e}"

    try:
        from agent.orchestration import get_failure_status
        st = get_failure_status()
        for name, etat in st.get("outils_en_echec", {}).items():
            if etat.get("consecutifs", 0) >= 3:
                return False, f"Outil '{name}' en échec depuis {etat['consecutifs']} appels consécutifs"
    except Exception:
        pass  # module non disponible : ne bloque pas le watchdog pour autant

    return True, "ok"


async def start_watchdog(wd_ctx=None):
    """Boucle de health-check interne. `wd_ctx` (sd_notify) est accepté pour
    compatibilité avec l'appel existant dans santana.py mais n'est PAS pingé
    ici — le ping systemd brut est déjà géré par `_watchdog_ping()` dans
    santana.py. Ce watchdog a un rôle complémentaire : alerter si Santana est
    vivant mais cassé, ce que le ping systemd ne peut pas voir."""
    consecutive_failures = 0
    while True:
        try:
            healthy, reason = await asyncio.to_thread(_check_internal_health)
            if healthy:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.error(f"[GUARDIAN][WATCHDOG] Santé dégradée ({consecutive_failures}x): {reason}")
                if consecutive_failures == _HEALTH_FAILURES_BEFORE_ALERT:
                    _send_telegram(
                        f"⚠️ Santana : santé interne dégradée depuis "
                        f"{_HEALTH_FAILURES_BEFORE_ALERT} vérifications consécutives — {reason}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[GUARDIAN][WATCHDOG] Erreur health-check: {e}")
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)



