"""
dev_exec.py — Exécution libre de commandes shell pour Santana.

L'outil qui manquait à Santana pour coder librement.
Pas d'allowlist, pas de denylist, pas de sandbox mount.

Garde-fous systémiques uniquement :
1. Timeout + kill forcé
2. Filtre post-output (patterns de tokens/secrets masqués)
3. Backup des fichiers critiques avant exécution
4. Snapshot git avant commandes destructives (push, commit)
5. Max concurrents (1 seule commande à la fois)

Utilisation :
  dev_exec("pytest tests/test_atlas.py")
  dev_exec("git add -A && git commit -m 'fix: ...'")
  dev_exec("cd ~/santana && source venv_new/bin/activate && python3 santana.py")
"""

import os
import re
import json
import logging
import subprocess
import shutil
import time
import threading

logger = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────

_DEFAULT_TIMEOUT = 60       # secondes
_MAX_TIMEOUT = 300          # max absolu (5 min)
_MAX_OUTPUT = 20000         # caractères max dans la réponse

# Répertoires de travail autorisés
_WORK_DIRS = [
    os.path.expanduser("~/santana"),
    os.path.expanduser("~/.openclaw"),
    os.path.expanduser("~/.hermes"),
    os.path.expanduser("~"),
]

# Fichiers critiques : backup automatique avant chaque commande
_CRITICAL_FILES = [
    "~/.openclaw/.env",
    "~/.openclaw/config.yaml",
    "~/.openclaw/openclaw.yaml",
    "~/santana/.env",
    "~/santana/santana.py",
    "~/santana/memory.db",
    "~/santana/metrics.db",
]

# Patterns à masquer dans les réponses (tokens, secrets, clés)
_SECRET_PATTERNS = [
    (r'gh[ps]_[a-zA-Z0-9]{36}', 'gh_[xxx]'),
    (r'sk-[a-zA-Z0-9]{32,}', 'sk-[xxx]'),
    (r'Bearer\s+\S+', 'Bearer [MASQUÉ]'),
    (r'Authorization:\s*\S+', 'Authorization: [MASQUÉ]'),
    (r'x-access-token:[^@]+@', 'x-access-token:[MASQUÉ]@'),
    (r'TELEGRAM_TOKEN=\S+', 'TELEGRAM_TOKEN=[MASQUÉ]'),
    (r'DEEPSEEK_API_KEY=\S+', 'DEEPSEEK_API_KEY=[MASQUÉ]'),
    (r'GROQ_API_KEY=\S+', 'GROQ_API_KEY=[MASQUÉ]'),
    (r'password[=:]\s*["\\\']?\S+["\\\']?', 'password=[MASQUÉ]'),
]

# Verrou global — 1 commande à la fois
_exec_lock = threading.Lock()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _expand(path: str) -> str:
    return os.path.expanduser(path)


def _backup_critical():
    """Sauvegarde les fichiers critiques avant une commande destructive."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.expanduser("~/backups/dev_exec")
    os.makedirs(backup_dir, exist_ok=True)
    for path in _CRITICAL_FILES:
        src = _expand(path)
        if os.path.exists(src):
            dst = os.path.join(backup_dir, f"{os.path.basename(src)}.{ts}")
            try:
                shutil.copy2(src, dst)
            except Exception as e:
                logger.warning(f"[DEVEXEC] Backup échoué {src}: {e}")


def _mask_secrets(output: str) -> str:
    """Masque les tokens et secrets dans la sortie."""
    for pattern, replacement in _SECRET_PATTERNS:
        output = re.sub(pattern, replacement, output)
    return output


def _snapshot_before_destructive(command: str) -> str | None:
    """Fait un snapshot git avant les commandes destructives."""
    cmd_lower = command.lower()
    is_destructive = (
        "git push" in cmd_lower
        or "git commit" in cmd_lower
        or "git merge" in cmd_lower
    )
    if not is_destructive:
        return None

    repos = {
        "~/santana": "Santana",
        "~/.openclaw": "OpenClaw",
        "~/.hermes": "Hermes",
    }
    results = []
    for path, name in repos.items():
        repo_dir = _expand(path)
        git_dir = os.path.join(repo_dir, ".git")
        if os.path.exists(git_dir):
            try:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=repo_dir, capture_output=True, timeout=10
                )
                r = subprocess.run(
                    ["git", "stash", "push", "-m", f"[auto-snapshot avant destructive] {ts}"],
                    cwd=repo_dir, capture_output=True, text=True, timeout=10
                )
                results.append(f"{name}: {r.stdout.strip() or 'stash créé'}")
            except Exception as e:
                results.append(f"{name}: snapshot échoué ({e})")

    return " | ".join(results) if results else None


# ─── Outil principal ────────────────────────────────────────────────────────

def _dev_exec(command: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Exécute une commande shell et retourne stdout/stderr."""
    global _exec_active

    # Rate limiter : 1 commande à la fois
    if not _exec_lock.acquire(blocking=False):
        return json.dumps({"error": "Une commande est déjà en cours d'exécution."})

    try:
        actual_timeout = min(timeout or _DEFAULT_TIMEOUT, _MAX_TIMEOUT)

        # 1. Backup fichiers critiques
        _backup_critical()

        # 2. Snapshot git avant actions destructives
        snap_msg = _snapshot_before_destructive(command)
        if snap_msg:
            logger.info(f"[DEVEXEC] Snapshot: {snap_msg}")

        # 3. Déterminer le répertoire de travail
        workdir = os.path.expanduser("~")
        cd_match = re.search(r'cd\s+(\S+)', command)
        if cd_match:
            candidate = os.path.expanduser(cd_match.group(1))
            if os.path.isdir(candidate):
                workdir = candidate

        logger.info(f"[DEVEXEC] Lancement dans {workdir}: {command[:120]}")

        # 4. Exécution
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=actual_timeout,
            cwd=workdir,
            executable="/bin/bash",
        )

        # 5. Collecter et filtrer
        stdout = _mask_secrets(result.stdout or "")
        stderr = _mask_secrets(result.stderr or "")

        output_parts = []
        if stdout:
            output_parts.append(stdout[-_MAX_OUTPUT:])
        if stderr:
            output_parts.append(f"--- stderr ---\n{stderr[-5000:]}")
        if result.returncode != 0:
            output_parts.append(f"--- code de sortie: {result.returncode} ---")

        final = "\n".join(output_parts) or "(aucune sortie)"
        if len(final) > _MAX_OUTPUT:
            final = final[:_MAX_OUTPUT] + "\n[... tronqué]"

        logger.info(f"[DEVEXEC] Terminé: returncode={result.returncode}, {len(final)} chars")
        return final

    except subprocess.TimeoutExpired:
        logger.warning(f"[DEVEXEC] Timeout après {actual_timeout}s")
        return json.dumps({"error": f"Timeout {actual_timeout}s — commande tuée."})
    except Exception as e:
        logger.error(f"[DEVEXEC] Erreur: {e}")
        return json.dumps({"error": f"Erreur: {str(e)}"})
    finally:
        _exec_lock.release()


# ─── Interface outil ────────────────────────────────────────────────────────

def tool_dev_exec(command: str, timeout: int | None = None) -> str:
    """Exécute une commande shell libre sur la VM.

    Permet à Santana de modifier, tester et déployer son code ainsi que
    celui des autres agents (OpenClaw, Hermes) sur la machine.

    Args:
        command: Commande shell à exécuter (bash, cd, git, python3, pytest, etc.)
        timeout: Timeout en secondes (défaut: 60, max: 300)

    Returns:
        stdout + stderr de la commande (secrets masqués)
    """
    if not command or not command.strip():
        return json.dumps({"error": "Commande vide."})
    return _dev_exec(command, timeout=timeout or _DEFAULT_TIMEOUT)
