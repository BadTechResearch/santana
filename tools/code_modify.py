"""code_modify.py — Modification et exécution du code source de Santana.

Permet à Santana de lire, modifier et exécuter son propre code source
(tools/, agent/, core/, santana.py, etc.) avec backup automatique,
validation de sécurité et redémarrage du service.

Outils exposés via @tool (registry automatique) :
  - code_modify        : Écrit/modifie un fichier source
  - code_list_sources  : Liste les fichiers sources par dossier
  - restart_self       : Redémarre Santana après une modification
"""

import os
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime

from tools.registry import tool
from core.utils import get_base_dir

logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────────

BASE = get_base_dir()

# Dossiers source autorisés pour l'écriture
_WRITE_ALLOWED = {
    "tools",
    "agent",
    "core",
    "scripts",
    "atlas_engine",
    "metrics",
    "memory",
    "soul",
    "skills",
    "workspace",
    ".github",
    "tests",
}

# Fichiers à la racine autorisés
_ROOT_ALLOWED = {
    "santana.py",
    "deepseek_client.py",
    "pyproject.toml",
    "README.md",
    "ARCHITECTURE.md",
    "CHANGELOG.md",
    "requirements.txt",
    "requirements-lock.txt",
}

# Blocages de sécurité
_BLOCKED_PREFIXES = (".", "__pycache__", "venv", "backup", "data", "github_cache")
_BLOCKED_FRAGMENTS = (".env", "token", "secret", "password", "credential", "auth")
_BLOCKED_EXACT = {".env", ".env.example"}

# Extensions autorisées
_ALLOWED_EXTENSIONS = {".py", ".md", ".toml", ".txt", ".json", ".yaml", ".yml", ".cfg", ".ini", ".sh"}

# Backup dir
_BACKUP_DIR = os.path.join(BASE, "backup", "code_modify")


# ─── Validation ────────────────────────────────────────────────────────────

def _validate_path(path: str) -> tuple[bool, str, str]:
    """Valide un chemin d'écriture.

    Returns:
        (valide, message_erreur, chemin_absolu)
    """
    clean = path
    while clean.startswith("/") or clean.startswith("."):
        clean = clean[1:]
    parts = clean.split("/")
    abs_path = os.path.realpath(os.path.join(BASE, clean))

    # Doit être dans BASE
    if not abs_path.startswith(BASE + "/") and abs_path != BASE:
        return False, "❌ Chemin hors de ~/santana/.", ""

    # Extension autorisée
    ext = os.path.splitext(abs_path)[1].lower()
    if ext and ext not in _ALLOWED_EXTENSIONS:
        return False, f"❌ Extension '{ext}' non autorisée. ({', '.join(sorted(_ALLOWED_EXTENSIONS))})", ""

    # Blocages exacts
    base_name = os.path.basename(abs_path)
    if base_name in _BLOCKED_EXACT:
        return False, "❌ Fichier sensible bloqué.", ""

    # Fragments bloqués dans le chemin
    lower_path = abs_path.lower()
    for frag in _BLOCKED_FRAGMENTS:
        if frag in lower_path:
            return False, f"❌ Motif sensible '{frag}' dans le chemin.", ""

    # Fichier racine autorisé
    if len(parts) == 1 and parts[0] in _ROOT_ALLOWED:
        return True, "", abs_path

    # Préfixes bloqués (dossiers)
    for part in parts:
        if part.startswith(tuple(_BLOCKED_PREFIXES)):
            return False, f"❌ Dossier '{part}' bloqué.", ""

    # Dossier autorisé
    if parts[0] in _WRITE_ALLOWED:
        return True, "", abs_path

    return False, f"❌ Dossier '{parts[0]}' non autorisé. Autorisés: {', '.join(sorted(_WRITE_ALLOWED))}", ""


def _backup_file(abs_path: str) -> str | None:
    """Sauvegarde un fichier avant modification. Retourne le chemin backup ou None."""
    if not os.path.exists(abs_path):
        return None
    try:
        rel = os.path.relpath(abs_path, BASE)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(_BACKUP_DIR, f"{ts}__{rel.replace('/', '__')}")
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        shutil.copy2(abs_path, backup_path)
        logger.info("[CODE_MODIFY] Backup créé: %s", backup_path)
        return backup_path
    except Exception as e:
        logger.warning("[CODE_MODIFY] Backup échoué: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# OUTILS
# ═══════════════════════════════════════════════════════════════════════════════

@tool(
    name="code_modify",
    description="MODIFIE le code source de Santana (tools/, agent/, core/, santana.py, tests/, etc.) avec backup automatique. Utilise APRES avoir lu le fichier avec fs_read.",
    parameters={
        "path": {
            "type": "string",
            "description": "Chemin relatif depuis ~/santana/ (ex: tools/mao.py, santana.py)"
        },
        "content": {
            "type": "string",
            "description": "NOUVEAU contenu complet du fichier (pas un diff, pas un patch, tout le fichier)"
        }
    }
)
def code_modify(path: str, content: str) -> str:
    """Écrit/modifie un fichier source de Santana avec backup automatique."""

    # Validation du chemin
    valid, error, abs_path = _validate_path(path)
    if not valid:
        return error

    try:
        # Backup si le fichier existe déjà
        backup = _backup_file(abs_path)

        # Écriture
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        total = len(content)
        lines = content.count("\n") + 1
        backup_info = f" (backup: {os.path.basename(backup)})" if backup else ""
        logger.info("[CODE_MODIFY] ✅ %s modifié (%d lignes, %d chars)%s", path, lines, total, backup_info or "")
        return f"✅ {path} modifié ({lines} lignes, {total} chars){backup_info}"

    except Exception as e:
        logger.error("[CODE_MODIFY] Erreur écriture %s: %s", path, e)
        return f"❌ Erreur écriture {path}: {str(e)}"


@tool(
    name="code_list_sources",
    description="Liste les fichiers sources Python de Santana par dossier. Utile avant code_modify pour vérifier les noms exacts.",
    parameters={
        "directory": {
            "type": "string",
            "description": "Dossier relatif (ex: tools/, agent/, core/). Vide = tous."
        }
    }
)
def code_list_sources(directory: str = "") -> str:
    """Liste les fichiers sources Python par dossier."""

    if directory:
        target_dir = os.path.join(BASE, directory.strip("/"))
        if not os.path.isdir(target_dir):
            return f"❌ Dossier '{directory}' introuvable."
        parts = [(directory, target_dir)]
    else:
        parts = []
        for d in sorted(_WRITE_ALLOWED):
            dd = os.path.join(BASE, d)
            if os.path.isdir(dd):
                parts.append((d, dd))
        # Racine
        for f in _ROOT_ALLOWED:
            fp = os.path.join(BASE, f)
            if os.path.isfile(fp):
                parts.append(("", BASE))  # sera traité spécialement

    result_lines = []
    for label, target_dir in parts:
        files = []
        for f in sorted(os.listdir(target_dir)):
            if f.endswith(".py") and not f.startswith("__"):
                files.append(f)
        if files:
            result_lines.append(f"\n📁 {label}/ ({len(files)} fichiers)")
            for f in files:
                fp = os.path.join(target_dir, f)
                size = os.path.getsize(fp)
                result_lines.append(f"  • {f} ({size} bytes)")

    if not result_lines:
        return "📭 Aucun fichier source trouvé."

    return "\n".join(result_lines)


@tool(
    name="restart_self",
    description="REDÉMARRE Santana. Utilise APRES avoir modifié le code avec code_modify ou tool_create pour appliquer les changements.",
    parameters={}
)
def restart_self() -> str:
    """Redémarre le service Santana via systemd --user."""

    logger.warning("[CODE_MODIFY] Redémarrage demandé!")

    try:
        # Vérifier que systemd est disponible
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "santana"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return "⚠️ Santana n'est pas actif (service systemd introuvable?). Redémarrage annulé: " + result.stderr[:200]

        # Restart
        result = subprocess.run(
            ["systemctl", "--user", "restart", "santana"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            logger.warning("[CODE_MODIFY] ✅ Redémarrage envoyé — Santana va redémarrer.")
            return "✅ Redémarrage lancé. Santana va redémarrer dans quelques secondes."
        else:
            return f"❌ Échec redémarrage: {result.stderr[:500]}"

    except FileNotFoundError:
        return "❌ systemctl introuvable sur ce système."
    except subprocess.TimeoutExpired:
        return "❌ Timeout redémarrage (30s)."
    except Exception as e:
        return f"❌ Erreur redémarrage: {str(e)}"
