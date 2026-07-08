"""
Registry d'outils Santana — découverte automatique et dispatch centralisé.

Mécanisme :
  1. Les outils s'enregistrent automatiquement via le décorateur @tool()
  2. Le registre fournit TOOLS (liste OpenAI) pour le LLM et dispatch() pour l'exécution
  3. Plus besoin de éditer tools.json ni la liste TOOLS manuellement

Usage dans un nouvel outil (ex: tools/weather.py) :
    from tools.registry import tool

    @tool(
        name="get_weather",
        description="Météo pour une ville",
        parameters={
            "city": {"type": "string", "description": "Nom de la ville"},
        }
    )
    def get_weather(city: str) -> str:
        return f"Il fait 22°C à {city}"
"""

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ─── Registre interne ──────────────────────────────────────────────────────────

# Structure : {name: {"fn": Callable, "schema": dict, "arg_map": dict, "defaults": dict}}
_TOOL_REGISTRY: dict[str, dict] = {}

# TOOLS list au format OpenAI (build à la demande depuis le registre)
_CACHED_TOOLS: list[dict] | None = None


def tool(
    name: str | None = None,
    description: str = "",
    parameters: dict[str, dict] | None = None,
    arg_map: dict[str, str] | None = None,
    defaults: dict[str, Any] | None = None,
):
    """Décorateur : enregistre une fonction comme outil Santana.

    Args:
        name: Nom de l'outil (par défaut = nom de la fonction)
        description: Description pour le LLM
        parameters: {nom_param: {"type": str, "description": str}}
        arg_map: Mapping {nom_param_fonction: nom_param_json}
        defaults: Valeurs par défaut {nom_param: valeur}
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__

        # Auto-générer arg_map depuis parameters si non fourni
        final_arg_map = arg_map or {}
        if not final_arg_map and parameters:
            final_arg_map = {p: p for p in parameters}

        # Construire le schéma OpenAI
        schema_properties = {}
        required = []
        if parameters:
            for param_name, param_info in parameters.items():
                schema_properties[param_name] = {
                    "type": param_info.get("type", "string"),
                    "description": param_info.get("description", ""),
                }
                if param_name not in (defaults or {}):
                    required.append(param_name)

        schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": schema_properties,
                    "required": required,
                },
            },
        }

        _TOOL_REGISTRY[tool_name] = {
            "fn": fn,
            "schema": schema,
            "arg_map": final_arg_map,
            "defaults": defaults or {},
        }

        # Invalider le cache pour reconstruire TOOLS au prochain appel
        global _CACHED_TOOLS
        _CACHED_TOOLS = None

        logger.debug("[REGISTRY] Tool enregistré: %s", tool_name)
        return fn

    return decorator


def register(
    name: str,
    fn: Callable,
    schema: dict | None = None,
    arg_map: dict[str, str] | None = None,
    defaults: dict[str, Any] | None = None,
):
    """Enregistrement direct (sans décorateur) — compatible _register().

    Utile pour les outils qui ont déjà leur définition JSON dans tools.json.
    """
    _TOOL_REGISTRY[name] = {
        "fn": fn,
        "schema": schema or {"type": "function", "function": {"name": name}},
        "arg_map": arg_map or {},
        "defaults": defaults or {},
    }
    global _CACHED_TOOLS
    _CACHED_TOOLS = None


def _coerce_type(value: Any, param_name: str) -> Any:
    """Convertit une valeur au type attendu selon le nom du paramètre.
    
    Protection contre le bug des defaults string -> int.
    """
    if isinstance(value, str) and value.isdigit():
        # Noms de paramètres qui doivent être des entiers
        int_params = {"max_chars", "pull_number", "count", "max_results", "timeout", 
                      "max_tweets", "max_posts", "offset", "limit", "max_pages"}
        if param_name in int_params:
            return int(value)
    return value


def dispatch(name: str, args: dict) -> str | None:
    """Exécute un outil par son nom.

    Args:
        name: Nom de l'outil
        args: Arguments JSON de l'outil

    Returns:
        Résultat textuel, ou None si l'outil n'est pas dans le registre
    """
    entry = _TOOL_REGISTRY.get(name)
    if not entry:
        return None

    fn = entry["fn"]
    arg_map = entry["arg_map"]
    defaults = entry["defaults"]

    kwargs = {}
    missing = []
    for param, arg_key in arg_map.items():
        if arg_key in args:
            kwargs[param] = _coerce_type(args[arg_key], param)
        elif param in defaults:
            kwargs[param] = _coerce_type(defaults[param], param)
        else:
            missing.append(param)

    if missing:
        return json.dumps({"error": f"Paramètres manquants: {', '.join(missing)}"})

    try:
        return fn(**kwargs)
    except Exception as e:
        logger.error("[REGISTRY] Erreur outil %s: %s", name, e)
        return json.dumps({"error": f"Erreur outil {name}: {str(e)}"})


def get_tools() -> list[dict]:
    """Retourne la liste TOOLS au format OpenAI (avec cache, build au 1er appel)."""
    global _CACHED_TOOLS
    if _CACHED_TOOLS is None:
        _CACHED_TOOLS = [entry["schema"] for entry in _TOOL_REGISTRY.values()]
        logger.debug("[REGISTRY] TOOLS reconstruit: %d outils", len(_CACHED_TOOLS))
    return _CACHED_TOOLS


def get_tool_names() -> list[str]:
    """Retourne les noms de tous les outils enregistrés."""
    if not _TOOL_REGISTRY:
        try:
            import tools.tools  # noqa: F401
        except Exception:
            pass
    return list(_TOOL_REGISTRY.keys())


def clear():
    """Vide le registre (utile pour les tests)."""
    _TOOL_REGISTRY.clear()
    global _CACHED_TOOLS
    _CACHED_TOOLS = None
