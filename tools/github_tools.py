"""
github_tools.py — Lecture et écriture sur GitHub via SSH.

Santana utilise la clé SSH ~/.ssh/github_obsidian pour opérer
sur les repos privés de BadTechResearch (compte personnel GitHub).

Repos connus :
  - santana            → Code de l'agent lui-même
  - notes-btr          → Vault de notes BTR (production)
  - obsidian-vault-btr → Ancien vault Obsidian (legacy)

Usage :
  github_list_repos()                     → liste les repos disponibles
  github_list_files("notes-btr", "BTR")   → liste fichiers d'un dossier
  github_read("notes-btr", "BTR/BTR.md")  → lit un fichier
  github_write("notes-btr", "BTR/note.md", "# Titre\ntexte", "Message du commit")
"""

import os
import logging
import subprocess
from datetime import datetime

from metrics import track

# ── Configuration ──────────────────────────────────────────────────────────
BASE_DIR = os.path.expanduser("~/santana")
GIT_CACHE = os.path.join(BASE_DIR, "github_cache")
SSH_KEY = os.path.expanduser("~/.ssh/github_obsidian")
GIT_SSH_CMD = f"ssh -i {SSH_KEY} -o StrictHostKeyChecking=no"

# Email GitHub (noreply avec user ID — requis par GH007)
_GIT_EMAIL = "287147811+BadTechResearch@users.noreply.github.com"
_GIT_NAME = "Santana"

# Compte GitHub cible
GITHUB_ACCOUNT = "BadTechResearch"
GITHUB_HOST = "github.com"

# Liste des repos connus — restreint à CODEX-BRAINSTORM uniquement (refactoring CODE)
_KNOWN_REPOS = {
    "CODEX-BRAINSTORM": "Le deuxième cerveau — brainstorming et mémoire longue de Serge",
}

# ── Utilitaires bas niveau ────────────────────────────────────────────────

def _git(cmd: list[str], cwd: str = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Exécute une commande git avec la clé SSH configurée."""
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = GIT_SSH_CMD
    env["GIT_AUTHOR_NAME"] = _GIT_NAME
    env["GIT_AUTHOR_EMAIL"] = _GIT_EMAIL
    env["GIT_COMMITTER_NAME"] = _GIT_NAME
    env["GIT_COMMITTER_EMAIL"] = _GIT_EMAIL
    try:
        result = subprocess.run(
            ["git"] + cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        if result.returncode != 0:
            error = (result.stderr or result.stdout or "").strip()[:500]
            raise RuntimeError(f"Git error: {error}")
        return result
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Git timeout après {timeout}s")
    except FileNotFoundError:
        raise RuntimeError("Git non installé")


def _repo_url(repo: str) -> str:
    """Construit l'URL SSH du repo."""
    return f"git@{GITHUB_HOST}:{GITHUB_ACCOUNT}/{repo}.git"


def _ensure_repo(repo: str) -> str:
    """Vérifie que le repo existe en cache, le clone si nécessaire, pull sinon.

    Returns:
        Chemin absolu du repo en cache
    """
    repo_path = os.path.join(GIT_CACHE, repo)
    git_dir = os.path.join(repo_path, ".git")

    if os.path.exists(git_dir):
        # Pull pour mettre à jour
        try:
            _git(["pull", "--ff-only"], cwd=repo_path, timeout=20)
        except RuntimeError as e:
            logging.warning(f"[GITHUB] Pull {repo} échoué (peut-être pas grave): {e}")
    else:
        # Clone frais
        os.makedirs(GIT_CACHE, exist_ok=True)
        logging.info(f"[GITHUB] Clone {repo}...")
        _git(["clone", "--depth", "1", _repo_url(repo), repo_path], timeout=60)

    return repo_path


def _is_valid_repo(repo: str) -> bool:
    """Vérifie qu'un repo existe sur GitHub (test via git ls-remote)."""
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = GIT_SSH_CMD
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", _repo_url(repo)],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        return result.returncode == 0
    except Exception:
        logging.error("[GITHUB] _is_valid_repo git ls-remote failed for %s", repo)
        return False


# ── Outils exposés ─────────────────────────────────────────────────────────


@track()
def tool_github_list_repos() -> str:
    """Liste les dépôts GitHub accessibles par Santana."""
    lines = ["📦 Dépôts BadTechResearch accessibles :\n"]
    for name, desc in _KNOWN_REPOS.items():
        status = "✅" if _is_valid_repo(name) else "❌"
        lines.append(f"  {status} {name} — {desc}")
    lines.append("\n💡 Santana peut lire et écrire dans tous ces dépôts.")
    return "\n".join(lines)


@track()
def tool_github_list_files(repo: str, path: str = "") -> str:
    """Liste les fichiers et dossiers d'un dépôt GitHub.

    Args:
        repo: Nom du dépôt (ex: notes-btr, santana)
        path: Chemin dans le dépôt (laisser vide pour la racine)

    Returns:
        Liste des fichiers et dossiers avec leur type
    """
    try:
        repo_path = _ensure_repo(repo)
    except RuntimeError as e:
        return f"❌ Impossible d'accéder au dépôt '{repo}': {e}"

    target_path = os.path.join(repo_path, path) if path else repo_path

    if not os.path.exists(target_path):
        return f"❌ Chemin introuvable : '{path}' dans {repo}"

    # Lister le contenu
    try:
        items = sorted(os.listdir(target_path))
    except PermissionError:
        return f"❌ Permission refusée : {target_path}"

    if not items:
        return f"📂 Dossier vide : {repo}/{path}"

    lines = [f"📂 {repo}/{path or ''} :\n"]
    for item in items:
        # Ignorer les fichiers cachés et dossiers git
        if item.startswith("."):
            continue
        full = os.path.join(target_path, item)
        if os.path.isdir(full):
            lines.append(f"  📁 {item}/")
        else:
            # Taille du fichier
            size = os.path.getsize(full)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size/1024:.0f} KB"
            else:
                size_str = f"{size/1024/1024:.1f} MB"
            lines.append(f"  📄 {item}  ({size_str})")

    return "\n".join(lines)


@track()
def tool_github_read(repo: str, path: str, max_chars: int = 15000) -> str:
    """Lit le contenu d'un fichier dans un dépôt GitHub.

    Args:
        repo: Nom du dépôt (ex: notes-btr, santana)
        path: Chemin du fichier dans le dépôt (ex: BTR/BTR.md)
        max_chars: Nombre maximum de caractères à retourner (défaut: 15000)

    Returns:
        Contenu du fichier
    """
    try:
        repo_path = _ensure_repo(repo)
    except RuntimeError as e:
        return f"❌ Impossible d'accéder au dépôt '{repo}': {e}"

    full_path = os.path.join(repo_path, path)

    # Vérifier que le chemin est bien dans le repo
    full_path = os.path.abspath(full_path)
    repo_path_abs = os.path.abspath(repo_path)
    if not full_path.startswith(repo_path_abs):
        return "❌ Chein hors du dépôt."

    if not os.path.exists(full_path):
        return f"❌ Fichier introuvable : {path} dans {repo}"

    if os.path.isdir(full_path):
        return f"❌ '{path}' est un dossier, pas un fichier. Utilise github_list_files pour lister son contenu."

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        total_size = os.path.getsize(full_path)
        lines_count = content.count("\n")
        truncated = total_size > max_chars

        header = f"📄 {repo}/{path} ({lines_count} lignes, {min(total_size, max_chars)}/{total_size} caractères)"
        if truncated:
            header += " — TRONQUÉ (limité à 15000 caractères)"

        return f"{header}\n\n{content}"
    except Exception as e:
        return f"❌ Erreur lecture {path}: {e}"


@track()
def tool_github_write(repo: str, path: str, content: str, message: str = "") -> str:
    """Écrit ou met à jour un fichier dans un dépôt GitHub (commit + push).

    Args:
        repo: Nom du dépôt (ex: notes-btr, santana)
        path: Chemin du fichier dans le dépôt (ex: BTR/note-importante.md)
        content: Contenu à écrire (format Markdown recommandé)
        message: Message de commit (optionnel — auto-généré si vide)

    Returns:
        Confirmation du commit avec le hash
    """
    # Restreindre à CODEX-BRAINSTORM uniquement (refactoring CODE)
    ALLOWED_REPO = "CODEX-BRAINSTORM"
    if repo.upper() != ALLOWED_REPO.upper():
        return f"❌ Santana ne peut écrire que dans {ALLOWED_REPO}. Écriture dans '{repo}' refusée."
    try:
        repo_path = _ensure_repo(repo)
    except RuntimeError as e:
        return f"❌ Impossible d'accéder au dépôt '{repo}': {e}"

    full_path = os.path.join(repo_path, path)
    full_path = os.path.abspath(full_path)

    # Vérifier que le chemin est dans le repo
    repo_path_abs = os.path.abspath(repo_path)
    if not full_path.startswith(repo_path_abs):
        return "❌ Chemin hors du dépôt."

    # Créer les dossiers parents si nécessaire
    parent = os.path.dirname(full_path)
    os.makedirs(parent, exist_ok=True)

    # Vérifier si c'est une création ou une modification
    is_new = not os.path.exists(full_path)

    # Écrire le fichier
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return f"❌ Erreur écriture {path}: {e}"

    # Commit + Push
    action = "Création" if is_new else "Mise à jour"
    commit_msg = message.strip() or f"{action} de {path} par Santana — {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    try:
        # add
        _git(["add", path], cwd=repo_path, timeout=10)
        # commit
        result = _git(["commit", "-m", commit_msg], cwd=repo_path, timeout=10)
        # push
        _git(["push"], cwd=repo_path, timeout=30)

        # Extraire le hash du commit
        hash_result = _git(["rev-parse", "HEAD"], cwd=repo_path, timeout=5)
        commit_hash = hash_result.stdout.strip()[:12]

        return (
            f"✅ {action} réussie dans `{repo}/{path}`\n"
            f"🔖 Commit: {commit_hash}\n"
            f"💬 Message: {commit_msg}"
        )

    except RuntimeError as e:
        error_msg = str(e)
        if "nothing to commit" in error_msg.lower() or "nothing added" in error_msg.lower():
            return f"ℹ️ Aucun changement détecté — le fichier `{path}` est identique."
        return f"❌ Erreur Git: {error_msg}"


# ── Registre Santana ───────────────────────────────────────────────────────

def register_all():
    """Enregistre tous les outils GitHub dans le registre Santana."""
    from tools.tools import _register

    _register("github_list_repos", tool_github_list_repos, {})
    _register("github_list_files", tool_github_list_files, {"repo": "repo", "path": "path"})
    _register("github_read", tool_github_read, {"repo": "repo", "path": "path", "max_chars": "max_chars"})
    _register("github_write", tool_github_write, {
        "repo": "repo", "path": "path",
        "content": "content", "message": "message"
    })
    logging.info("[GITHUB] 4 outils enregistrés : github_list_repos, github_list_files, github_read, github_write")
