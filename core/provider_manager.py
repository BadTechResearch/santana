"""Gestionnaire intelligent de providers LLM pour Santana.

Gère :
- L'état actif du provider (deepseek ou groq)
- Le retry automatique ×2 avant fallback pour DeepSeek
- Le health check périodique de DeepSeek quand on est sur Groq
- La configuration dynamique (max_tokens, max_chars) par provider
- Le basculement automatique détecté par la couche transport (provider.py)
"""

import logging
import json
import os
import time
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# ─── État global du gestionnaire ──────────────────────────────────────
_active_provider: str = "deepseek"          # "deepseek" ou "groq"
_deepseek_last_healthy: Optional[float] = None   # timestamp dernier succès DeepSeek
_groq_since: Optional[float] = None               # timestamp du passage sur Groq

# ─── Configuration par provider ───────────────────────────────────────
# Ces valeurs sont utilisées par :
#   - core/provider.py  → truncation + max_tokens
#   - core/react_loop.py → choix de max_tokens, outils
#   - tools/telegram_stream.py → tag provider
PROVIDER_CONFIGS = {
    "deepseek": {
        "label":           "DeepSeek",
        "max_payload_chars": 4_000_000,   # DeepSeek gère 1M tokens sans limite HTTP
        "max_tokens":      32000,          # génération longue possible
        "retry_count":     2,              # 2 tentatives avant fallback
        "retry_delay":     1.0,            # secondes, doublé à chaque retry
        "context_window":  1_000_000,      # tokens
    },
    "groq": {
        "label":           "Groq",
        "max_payload_chars": 180_000,       # ~128K tokens avec marge JSON overhead
        "max_tokens":      8000,            # Groq limite à 8K output
        "retry_count":     1,               # 1 seule tentative
        "retry_delay":     0.5,
        "context_window":  128_000,
    },
}


# ─── API publique ─────────────────────────────────────────────────────

def get_active_provider() -> str:
    """Retourne le nom du provider actuellement actif"""
    return _active_provider


def set_active_provider(name: str):
    """Bascule le provider actif et logue le changement.

    Appelé par core/provider.py après un succès ou un fallback.
    """
    global _active_provider, _groq_since
    name = name.lower()
    if name not in ("deepseek", "groq"):
        logger.warning("[PROVIDER-MGR] Nom de provider inconnu: %s — ignoré", name)
        return
    if name == _active_provider:
        return
    old = _active_provider
    _active_provider = name
    if name == "groq":
        _groq_since = time.time()
        logger.warning(
            "[PROVIDER-MGR] ⚠️ Basculement %s → %s (mode dégradé, payload limité à %d chars)",
            old, name,
            PROVIDER_CONFIGS["groq"]["max_payload_chars"],
        )
    else:
        _groq_since = None
        logger.info("[PROVIDER-MGR] ✅ Retour %s ← %s (DeepSeek de nouveau opérationnel)", name, old)


def get_provider_config(provider: Optional[str] = None) -> dict:
    """Retourne la configuration du provider spécifié ou de l'actif."""
    name = provider or _active_provider
    return PROVIDER_CONFIGS.get(name, PROVIDER_CONFIGS["deepseek"])


def get_provider_label(provider: Optional[str] = None) -> str:
    """Retourne le label affichable du provider."""
    return get_provider_config(provider)["label"]


def get_groq_duration() -> Optional[float]:
    """Retourne le temps écoulé depuis le passage sur Groq, ou None."""
    if _groq_since is None:
        return None
    return time.time() - _groq_since


def probe_deepseek() -> bool:
    """Appel test minimal à DeepSeek.

    Utilise la clé de l'environnement, timeout 5s.
    Retourne True si DeepSeek répond HTTP 200.
    Idempotent — peut être appelé fréquemment.
    """
    key = os.getenv('DEEPSEEK_API_KEY', '')
    if not key:
        return False
    try:
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
            timeout=5,
        )
        ok = resp.status_code == 200
        if ok:
            global _deepseek_last_healthy
            _deepseek_last_healthy = time.time()
            logger.debug("[PROVIDER-MGR] Probe DeepSeek: ✅ OK")
        else:
            logger.debug("[PROVIDER-MGR] Probe DeepSeek: ❌ HTTP %d", resp.status_code)
        return ok
    except requests.exceptions.Timeout:
        logger.debug("[PROVIDER-MGR] Probe DeepSeek: ⏱️ timeout 5s")
        return False
    except requests.exceptions.ConnectionError:
        logger.debug("[PROVIDER-MGR] Probe DeepSeek: 🔌 connection refused")
        return False
    except Exception as e:
        logger.debug("[PROVIDER-MGR] Probe DeepSeek: ❌ %s", e)
        return False


def record_deepseek_success():
    """Enregistre un succès DeepSeek (appelé par provider.py)."""
    global _deepseek_last_healthy
    _deepseek_last_healthy = time.time()
