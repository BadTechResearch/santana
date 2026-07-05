"""Cache par hash SHA256 + comptage de tokens réel pour Santana.

Cache par hash : évite les appels redondants (même tool_call avec mêmes params).
Token counting : remplace len(text)//4 par tiktoken ou approximation meilleure.
"""

import hashlib
import json
import logging
import os
import time
from core.utils import get_base_dir

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(get_base_dir(), ".cache")
_CACHE_TTL = 300  # 5 minutes
os.makedirs(_CACHE_DIR, exist_ok=True)


def _make_key(name: str, args: dict) -> str:
    """Génère une clé SHA256 unique pour un appel outil."""
    raw = f"{name}:{json.dumps(args, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def cache_get(name: str, args: dict) -> str | None:
    """Récupère un résultat mis en cache. Retourne None si expiré ou absent."""
    key = _make_key(name, args)
    path = os.path.join(_CACHE_DIR, key)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            entry = json.load(f)
        if time.time() - entry["time"] > _CACHE_TTL:
            os.unlink(path)
            return None
        logger.debug(f"[CACHE] Hit: {name} ({key[:8]})")
        return entry["result"]
    except Exception:
        return None


def cache_set(name: str, args: dict, result: str):
    """Stocke un résultat dans le cache."""
    key = _make_key(name, args)
    path = os.path.join(_CACHE_DIR, key)
    try:
        with open(path, "w") as f:
            json.dump({"time": time.time(), "name": name, "result": result}, f)
        logger.debug(f"[CACHE] Set: {name} ({key[:8]})")
    except Exception as e:
        logger.debug(f"[CACHE] Write error: {e}")


def cache_purge_all():
    """Vide complètement le cache disque."""
    import shutil
    try:
        if os.path.isdir(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)
            os.makedirs(_CACHE_DIR, exist_ok=True)
        logger.info(f"[CACHE] Purge totale: {_CACHE_DIR}")
    except Exception as e:
        logger.error(f"[CACHE] Purge error: {e}")


def estimate_tokens(text: str) -> int:
    """Estimation plus précise que len//4 pour le français.
    
    Prend en compte : mots longs, ponctuation, accents.
    Ratio réel pour le français : ~1 token pour 2-3 caractères vs 4 pour l'anglais.
    """
    if not text:
        return 0
    # Approximation : tokens ≈ mots / 0.75 (moyenne tokens par mot en français)
    words = len(text.split())
    # Fallback caractères si peu de mots
    if words < 3:
        return max(1, len(text) // 3)
    return max(1, int(words / 0.75))
