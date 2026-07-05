"""Gestionnaire de skills en fichiers .md pour Santana.
Remplace le stockage SQLite tronqué par des fichiers markdown complets,
versionnables, chargeables dynamiquement.

Fonctions exposées via le registry Santana :
    skill_view(name) — Charge une skill depuis ~/santana/skills/<name>.md
    skill_manage(action, name, content) — Crée/modifie/supprime une skill
    skill_list() — Liste toutes les skills disponibles
"""

import glob
import logging
import os
import re
from core.utils import get_base_dir

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(get_base_dir(), "skills")
_FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n(.*)', re.DOTALL)
_VALID_NAME = re.compile(r'^[a-zA-Z0-9_-]+$')


def _skill_path(name: str) -> str:
    """Chemin absolu vers un fichier skill."""
    if not _VALID_NAME.match(name):
        raise ValueError(f"Nom de skill invalide: {name}")
    return os.path.join(SKILLS_DIR, f"{name}.md")


def skill_view(name: str) -> str:
    """Charge une skill depuis un fichier .md et retourne son contenu complet.

    La skill peut avoir un frontmatter YAML (--- ... ---) qui est inclus
    dans le retour. Utilisé pour injecter une méthodologie dans le contexte.

    Args:
        name: Nom de la skill (sans .md)

    Returns:
        Contenu complet de la skill ou message d'erreur
    """
    path = _skill_path(name)
    if not os.path.exists(path):
        return f"Skill '{name}' introuvable. Skills disponibles: {', '.join(skill_list())}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        logger.error(f"[SKILL] Erreur lecture {name}: {e}")
        return f"Erreur: {str(e)}"


def skill_manage(action: str, name: str, content: str = "") -> str:
    """Crée, modifie ou supprime une skill.

    Args:
        action: 'create', 'patch', 'delete'
        name: Nom de la skill (sans .md)
        content: Contenu complet (requis pour create/patch)

    Returns:
        Confirmation ou message d'erreur
    """
    path = _skill_path(name)
    actions = {
        "create": lambda: _skill_create(path, content),
        "patch": lambda: _skill_patch(path, content),
        "delete": lambda: _skill_delete(path),
    }
    fn = actions.get(action)
    if not fn:
        return f"Action invalide: {action}. Utilise create, patch ou delete."
    return fn()


def _skill_create(path: str, content: str) -> str:
    if os.path.exists(path):
        return f"Erreur: skill déjà existante ({os.path.basename(path)}). Utilise 'patch' pour modifier."
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n") + 1
    logger.info(f"[SKILL] Créée: {path} ({lines} lignes)")
    return f"✅ Skill créée: {os.path.basename(path)} ({lines} lignes)"


def _skill_patch(path: str, content: str) -> str:
    if not os.path.exists(path):
        return f"Erreur: skill '{os.path.basename(path)}' n'existe pas. Utilise 'create' d'abord."
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n") + 1
    logger.info(f"[SKILL] Patchée: {path} ({lines} lignes)")
    return f"✅ Skill patchée: {os.path.basename(path)} ({lines} lignes)"


def _skill_delete(path: str) -> str:
    if not os.path.exists(path):
        return f"Erreur: skill '{os.path.basename(path)}' n'existe pas."
    os.unlink(path)
    logger.info(f"[SKILL] Supprimée: {path}")
    return f"✅ Skill supprimée: {os.path.basename(path)}"


def skill_list() -> list:
    """Liste toutes les skills disponibles."""
    pattern = os.path.join(SKILLS_DIR, "*.md")
    files = sorted(glob.glob(pattern))
    return [os.path.splitext(os.path.basename(f))[0] for f in files]
