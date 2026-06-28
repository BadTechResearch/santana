"""Gouverneur de coût pour Santana (F9 de la roadmap).

Contrôleur de budget : suit le coût cumulé de la session LLM en cours et
applique trois seuils pour protéger le budget mensuel (≤ €10/mois, verrou Serge).

Seuils (en pourcentage du budget) :
- ALERT     (80 %)  → log d'avertissement, on continue normalement
- THROTTLE  (95 %)  → on ralentit, on limite les outils coûteux
- STOP      (100 %) → on refuse les appels LLM coûteux, mode dégradé

Le budget par défaut vient de DEEPSEEK_COST_LIMIT dans .env (défaut 0.01 = 0,01 $).
DeepSeek V4 Flash coûte ¥1 / 1M tokens ; le prix par 1M tokens en USD est
configurable via DEEPSEEK_PRICE_PER_1M_USD (défaut 0.14).

Le coût est volontairement estimé (pas de relevé exact par l'API) : l'objectif
est un garde-fou conservateur, pas une comptabilité au centime.
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────

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
    "cout_cumule": 0.0,     # coût cumulé estimé de la session ($)
    "budget": _read_budget(),
    "appels": 0,            # nombre d'appels LLM comptabilisés
    "dernier_niveau": "OK",
}


def estimate_cost_from_tokens(input_tokens: int, output_tokens: int = 0) -> float:
    """Estime le coût en USD d'un appel à partir des tokens entrée/sortie."""
    price = _read_price_per_1m()
    total_tokens = max(0, input_tokens) + max(0, output_tokens)
    return (total_tokens / 1_000_000.0) * price


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
            "cout_cumule": round(cumule, 6),
            "budget": round(budget, 6),
            "pourcentage": round(ratio * 100, 1),
            "appels": _state["appels"],
            "restant": round(max(0.0, budget - cumule), 6),
        }


def reset() -> dict:
    """Réinitialise le coût cumulé de la session (garde le budget)."""
    with _lock:
        _state["cout_cumule"] = 0.0
        _state["appels"] = 0
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
