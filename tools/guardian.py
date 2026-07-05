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



