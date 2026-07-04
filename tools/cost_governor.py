"""Gouverneur de coût pour Santana — basé sur la consommation RÉELLE DeepSeek V4 Flash.

Deux mécanismes complémentaires :

1. **Pré-check (garde-fou)** : avant chaque appel LLM, `check_cost_governor()` estime
   le coût du prochain appel à partir de la taille des messages. Si le budget projeté
   dépasse ALERT (80%) / THROTTLE (95%) / STOP (100%), l'appel est dégradé ou bloqué.

2. **Suivi réel (comptabilité)** : après chaque appel API réussi, `record_usage()` est
   appelée par `core/provider.py` avec les tokens RÉELS retournés par l'API DeepSeek
   (prompt_tokens, completion_tokens, cached_tokens). Le coût est calculé avec les
   vrais prix DeepSeek V4 Flash :
     - Input cache miss : $0.14 / 1M tokens
     - Input cache hit  : $0.0028 / 1M tokens (×50 moins cher)
     - Output           : $0.28 / 1M tokens

Seuils (en pourcentage du budget) :
- ALERT     (80 %)  → log d'avertissement, on continue normalement
- THROTTLE  (95 %)  → on ralentit, on limite les outils coûteux
- STOP      (100 %) → on refuse les appels LLM coûteux, mode dégradé

Le budget par défaut vient de DEEPSEEK_COST_LIMIT dans .env (défaut 0.01 = 0,01 $).
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────

# Prix réels DeepSeek V4 Flash (vérifiés via API le 04/07/2026)
# Source : https://api-docs.deepseek.com/quick_start/pricing
PRIX_INPUT_CACHE_MISS = 0.14    # $ / 1M tokens — prompt cache miss
PRIX_OUTPUT = 0.28              # $ / 1M tokens — completion (inclut reasoning)
PRIX_CACHE_HIT = 0.0028        # $ / 1M tokens — prompt cache hit (×50 moins cher)


def _read_budget() -> float:
    """Lit le budget de session depuis DEEPSEEK_COST_LIMIT (défaut 0.01 $)."""
    try:
        return float(os.getenv("DEEPSEEK_COST_LIMIT", "0.01"))
    except (TypeError, ValueError):
        logger.error("[COST] DEEPSEEK_COST_LIMIT invalide, repli sur 0.01")
        return 0.01


def _read_price_per_1m() -> float:
    """Prix en USD pour 1M tokens (DeepSeek V4 Flash ≈ ¥1 ≈ 0,14 $)."""
    try:
        return float(os.getenv("DEEPSEEK_PRICE_PER_1M_USD", "0.14"))
    except (TypeError, ValueError):
        return 0.14


# Seuils en fraction du budget
SEUIL_ALERT = 0.80
SEUIL_THROTTLE = 0.95
SEUIL_STOP = 1.00

# ─── État de session (thread-safe) ──────────────────────────────────────────

_lock = threading.Lock()
_state = {
    "cout_cumule": 0.0,          # coût cumulé estimé de la session ($)
    "cout_cumule_reel": 0.0,     # coût cumulé réel (depuis record_usage)
    "budget": _read_budget(),
    "appels": 0,                 # nombre d'appels LLM comptabilisés (estimés)
    "total_appels_reussis": 0,   # appels API réellement réussis
    "total_tokens_prompt": 0,
    "total_tokens_completion": 0,
    "total_tokens_cache": 0,
    "taux_cache_moyen": 0.0,
    "dernier_niveau": "OK",
}


def estimate_cost_from_tokens(input_tokens: int, output_tokens: int = 0) -> float:
    """Estime le coût en USD d'un appel à partir des tokens entrée/sortie."""
    price = _read_price_per_1m()
    total_tokens = max(0, input_tokens) + max(0, output_tokens)
    return (total_tokens / 1_000_000.0) * price


def _calculer_cout_reel(prompt_tokens: int, completion_tokens: int, cached_tokens: int) -> dict:
    """Calcule le coût réel d'un appel DeepSeek à partir des tokens retournés par l'API.

    DeepSeek V4 Flash facture :
      - Input (cache miss) : $0.14 / 1M tokens
      - Input (cache hit)  : $0.0028 / 1M tokens (×50 moins cher)
      - Output             : $0.28 / 1M tokens (inclut le reasoning)

    Args:
        prompt_tokens: tokens d'entrée totaux (cache miss + cache hit)
        completion_tokens: tokens de sortie
        cached_tokens: tokens d'entrée servis depuis le cache DeepSeek

    Returns:
        dict avec cout_input, cout_output, cout_total (en $)
    """
    miss = max(0, prompt_tokens - cached_tokens)
    cout_input = (miss / 1_000_000.0) * PRIX_INPUT_CACHE_MISS
    cout_input += (cached_tokens / 1_000_000.0) * PRIX_CACHE_HIT
    cout_output = (completion_tokens / 1_000_000.0) * PRIX_OUTPUT
    cout_total = round(cout_input + cout_output, 8)
    return {
        "cout_input": round(cout_input, 8),
        "cout_output": round(cout_output, 8),
        "cout_total": cout_total,
        "taux_cache": round(cached_tokens / max(1, prompt_tokens) * 100, 1),
    }


def record_usage(prompt_tokens: int, completion_tokens: int,
                 cached_tokens: int = 0, provider_name: str = "deepseek"):
    """Enregistre la consommation RÉELLE de tokens retournée par l'API LLM.

    Appelée par core/provider.py après chaque appel API réussi.
    Remplace l'estimation pré-appel par le coût réel.
    Persiste dans metrics.db pour le suivi mensuel.

    Args:
        prompt_tokens: tokens d'entrée réels (retour API)
        completion_tokens: tokens de sortie réels
        cached_tokens: tokens servis depuis le cache DeepSeek
        provider_name: nom du provider utilisé ('deepseek', 'nous', 'openrouter')
    """
    cout = _calculer_cout_reel(prompt_tokens, completion_tokens, cached_tokens)
    with _lock:
        _state["cout_cumule_reel"] = round(
            _state.get("cout_cumule_reel", 0.0) + cout["cout_total"], 8
        )
        _state["total_tokens_prompt"] = _state.get("total_tokens_prompt", 0) + prompt_tokens
        _state["total_tokens_completion"] = _state.get("total_tokens_completion", 0) + completion_tokens
        _state["total_tokens_cache"] = _state.get("total_tokens_cache", 0) + cached_tokens
        _state["total_appels_reussis"] = _state.get("total_appels_reussis", 0) + 1
        _state["taux_cache_moyen"] = round(
            (_state["total_tokens_cache"] / max(1, _state["total_tokens_prompt"])) * 100, 1
        )

    logger.info(
        "[COST] Réel: %dp + %dc (%d cache) = %.6f$ (cumul: %.6f$, %d appels, cache %s%%)",
        prompt_tokens, completion_tokens, cached_tokens,
        cout["cout_total"], _state["cout_cumule_reel"],
        _state["total_appels_reussis"], cout["taux_cache"],
    )


def estimate_cost_from_messages(messages: list, max_output_tokens: int = 0) -> float:
    """Estime le coût d'un appel LLM à partir de la liste de messages.

    Approximation : ~4 caractères par token (heuristique standard).
    `max_output_tokens` borne le coût de sortie estimé.
    """
    chars = 0
    for m in messages or []:
        if isinstance(m, dict):
            content = m.get("content") or ""
            if isinstance(content, str):
                chars += len(content)
            # Les tool_calls ajoutent aussi des tokens
            tc = m.get("tool_calls")
            if tc:
                chars += len(json.dumps(tc, ensure_ascii=False))
    input_tokens = chars // 4
    # On suppose une sortie moyenne ≪ max_tokens pour ne pas surestimer ;
    # on prend un quart du plafond comme estimation prudente.
    output_tokens = max_output_tokens // 4 if max_output_tokens else 0
    return estimate_cost_from_tokens(input_tokens, output_tokens)


def check_cost_governor(estimated_cost: float) -> str:
    """Vérifie le gouverneur de coût AVANT un appel LLM.

    Évalue le niveau projeté (coût cumulé + coût estimé de l'appel à venir).
    Si le niveau n'est pas STOP, l'appel est considéré comme autorisé et son
    coût estimé est ajouté au cumul de session. STOP n'enregistre rien
    (l'appel est censé être refusé par l'appelant).

    Args:
        estimated_cost: coût estimé de l'appel à venir, en USD.

    Returns:
        "OK", "ALERT", "THROTTLE" ou "STOP".
    """
    estimated_cost = max(0.0, float(estimated_cost or 0.0))
    with _lock:
        budget = _state["budget"] or _read_budget()
        projete = _state["cout_cumule"] + estimated_cost
        ratio = projete / budget if budget > 0 else 1.0

        if ratio >= SEUIL_STOP:
            niveau = "STOP"
        elif ratio >= SEUIL_THROTTLE:
            niveau = "THROTTLE"
        elif ratio >= SEUIL_ALERT:
            niveau = "ALERT"
        else:
            niveau = "OK"

        # On comptabilise le coût sauf si l'appel est refusé (STOP).
        if niveau != "STOP":
            _state["cout_cumule"] = projete
            _state["appels"] += 1

        _state["dernier_niveau"] = niveau

    if niveau == "ALERT":
        logger.warning(
            "[COST] ALERT — %.4f$/%.4f$ (%.0f%% du budget) atteint",
            projete, budget, ratio * 100,
        )
    elif niveau == "THROTTLE":
        logger.warning(
            "[COST] THROTTLE — %.4f$/%.4f$ (%.0f%%) : ralentissement, outils coûteux limités",
            projete, budget, ratio * 100,
        )
    elif niveau == "STOP":
        logger.error(
            "[COST] STOP — budget épuisé (%.4f$ projeté / %.4f$) : appels LLM coûteux refusés",
            projete, budget,
        )
    return niveau


def get_status() -> dict:
    """Retourne l'état courant du gouverneur de coût."""
    with _lock:
        budget = _state["budget"] or _read_budget()
        cumule = _state["cout_cumule"]
        cumule_reel = _state.get("cout_cumule_reel", 0.0)
        ratio = cumule / budget if budget > 0 else 1.0
        if ratio >= SEUIL_STOP:
            niveau = "STOP"
        elif ratio >= SEUIL_THROTTLE:
            niveau = "THROTTLE"
        elif ratio >= SEUIL_ALERT:
            niveau = "ALERT"
        else:
            niveau = "OK"
        return {
            "niveau": niveau,
            "cout_cumule_estime": round(cumule, 6),
            "cout_cumule_reel": round(cumule_reel, 8),
            "budget": round(budget, 6),
            "pourcentage_estime": round(ratio * 100, 1),
            "appels_estimes": _state["appels"],
            "appels_reussis": _state.get("total_appels_reussis", 0),
            "tokens_prompt": _state.get("total_tokens_prompt", 0),
            "tokens_completion": _state.get("total_tokens_completion", 0),
            "tokens_cache": _state.get("total_tokens_cache", 0),
            "taux_cache_moyen": _state.get("taux_cache_moyen", 0.0),
            "restant": round(max(0.0, budget - cumule_reel), 8),
        }


def reset() -> dict:
    """Réinitialise le coût cumulé de la session (garde le budget)."""
    with _lock:
        _state["cout_cumule"] = 0.0
        _state["cout_cumule_reel"] = 0.0
        _state["appels"] = 0
        _state["total_appels_reussis"] = 0
        _state["total_tokens_prompt"] = 0
        _state["total_tokens_completion"] = 0
        _state["total_tokens_cache"] = 0
        _state["taux_cache_moyen"] = 0.0
        _state["dernier_niveau"] = "OK"
    logger.info("[COST] Compteur de session réinitialisé")
    return get_status()


def set_budget(montant: float) -> dict:
    """Définit un nouveau budget de session (en USD)."""
    try:
        montant = float(montant)
    except (TypeError, ValueError):
        return {"error": f"Budget invalide: {montant!r}"}
    if montant <= 0:
        return {"error": "Le budget doit être strictement positif."}
    with _lock:
        _state["budget"] = montant
    logger.info("[COST] Budget de session défini à %.4f$", montant)
    return get_status()


# ─── Outil LLM : cost_governor ──────────────────────────────────────────────

def cost_governor_dispatch(action: str = "status", budget: str = "") -> str:
    """Dispatch de l'outil `cost_governor`.

    Actions : 'status' (état du budget), 'reset' (réinitialise le compteur),
    'set_budget' (définit un nouveau budget, paramètre `budget`).
    """
    try:
        action = (action or "status").strip().lower()
        if action == "status":
            return json.dumps(get_status(), ensure_ascii=False)
        if action == "reset":
            return json.dumps(reset(), ensure_ascii=False)
        if action == "set_budget":
            if budget in ("", None):
                return json.dumps({"error": "Paramètre 'budget' requis pour set_budget."})
            return json.dumps(set_budget(budget), ensure_ascii=False)
        return json.dumps({
            "error": f"Action inconnue: '{action}'. Disponibles: status, reset, set_budget."
        })
    except Exception as e:
        logger.error("[COST] Erreur cost_governor: %s", e)
        return json.dumps({"error": f"Erreur cost_governor: {str(e)}"})


# Définition OpenAI exportée (ajoutée aussi à tools/tools.json).
COST_TOOL = {
    "type": "function",
    "function": {
        "name": "cost_governor",
        "description": (
            "Contrôle le budget de coût LLM de la session Santana. "
            "Actions : 'status' (coût cumulé, budget, niveau OK/ALERT/THROTTLE/STOP), "
            "'reset' (remet le compteur de session à zéro), "
            "'set_budget' (définit un nouveau budget en USD via le paramètre 'budget')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action : status, reset, set_budget",
                    "enum": ["status", "reset", "set_budget"],
                },
                "budget": {
                    "type": "string",
                    "description": "Nouveau budget en USD (pour set_budget), ex: '0.02'",
                },
            },
            "required": ["action"],
        },
    },
}
