"""
tool_creator.py — Stub de sécurité.

Le fichier source original a été perdu, seul le .pyc survivait.
Ce stub évite le crash à l'import (NameError) lors d'une purge des __pycache__.
Les outils tool_create, install_dependencies, list_user_tools, delete_user_tool
retournent une erreur explicite au lieu de planter.
"""

import json
import logging

logger = logging.getLogger(__name__)
_UNAVAILABLE_MSG = "Outil non disponible : le module tool_creator.py est un stub (source originale perdue)."


def create_tool(name: str = "", description: str = "", code: str = "", **kwargs) -> str:
    """Stub — retourne une erreur explicite."""
    logger.warning("[TOOL_CREATOR] create_tool appelé mais module absent")
    return f"❌ {_UNAVAILABLE_MSG}"


def install_dependencies(packages: list = None, **kwargs) -> str:
    """Stub — retourne une erreur explicite."""
    logger.warning("[TOOL_CREATOR] install_dependencies appelé mais module absent")
    return f"❌ {_UNAVAILABLE_MSG}"


def list_user_tools(**kwargs) -> str:
    """Stub — retourne une liste vide."""
    return json.dumps({"tools": [], "note": _UNAVAILABLE_MSG})


def delete_user_tool(name: str = "", **kwargs) -> str:
    """Stub — retourne une erreur explicite."""
    logger.warning("[TOOL_CREATOR] delete_user_tool appelé mais module absent")
    return f"❌ {_UNAVAILABLE_MSG}"
