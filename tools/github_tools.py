"""
github_tools.py — Accès GitHub complet via HTTPS + token.

Santana utilise le GITHUB_TOKEN de l'environnement Hermes (~/.hermes/env.sh)
pour opérer sur TOUS les repos BadTechResearch en lecture ET écriture.

Usage :
  github_list_repos()                      → liste tous les repos disponibles
  github_list_branches("santana")          → liste les branches d'un repo
  github_list_files("santana", "tools/")   → liste fichiers d'un dossier
  github_read("santana", "santana.py")     → lit un fichier
  github_write("santana", "foo.py", "...") → écrit/commit/push
  github_delete_file("santana", "old.py")  → supprime un fichier
  github_create_repo("nouveau-projet")     → crée un repo
  github_create_branch("santana", "feature/x") → crée une branche
  github_create_pr("santana", "feature/x", "Titre", "Description")
  github_merge_pr("santana", 42)           → merge une PR
"""

import os
import re
import json
import time
import logging
import subprocess
import urllib.request
import urllib.error
import shlex
from datetime import datetime

from metrics import track
from core.utils import get_base_dir

# ── Configuration ──────────────────────────────────────────────────────────

BASE_DIR = get_base_dir()
GIT_CACHE = os.path.join(BASE_DIR, "github_cache")

_GIT_NAME = "Santana"
_GIT_EMAIL = "287147811+BadTechResearch@users.noreply.github.com"
GITHUB_ACCOUNT = "BadTechResearch"
GITHUB_API = "https://api.github.com"

# Lecteur du token
_ENV_FILE = os.path.expanduser("~/.hermes/env.sh")


def _get_token() -> str:
    """Lit le GITHUB_TOKEN depuis env.sh."""
    try:
        with open(_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                # Formats: GITHUB_TOKEN="xxx" ou export GITHUB_TOKEN='xxx'
                if line.replace("export ", "").startswith("GITHUB_TOKEN="):
                    raw = line.split("=", 1)[1]
                    raw = raw.strip("\"'")
                    return raw
    except Exception as e:
        logging.error("[GITHUB] Impossible de lire GITHUB_TOKEN: %s", e)
    return ""


def _api_headers() -> dict:
    token = _get_token()
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Santana",
    }


def _api_get(path: str) -> dict:
    """Requête GET vers l'API GitHub."""
    url = f"{GITHUB_API}{path}"
    req = urllib.request.Request(url, headers=_api_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"GitHub API GET {path} → {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"GitHub API GET {path} → {e}")


def _api_post(path: str, data: dict) -> dict:
    """Requête POST vers l'API GitHub."""
    url = f"{GITHUB_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=_api_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        raise RuntimeError(f"GitHub API POST {path} → {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"GitHub API POST {path} → {e}")


def _api_delete(path: str) -> dict:
    """Requête DELETE vers l'API GitHub."""
    url = f"{GITHUB_API}{path}"
    req = urllib.request.Request(url, headers=_api_headers(), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 204:
                return {"status": "deleted"}
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        raise RuntimeError(f"GitHub API DELETE {path} → {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"GitHub API DELETE {path} → {e}")


def _api_patch(path: str, data: dict) -> dict:
    """Requête PATCH vers l'API GitHub."""
    url = f"{GITHUB_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=_api_headers(), method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        raise RuntimeError(f"GitHub API PATCH {path} → {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"GitHub API PATCH {path} → {e}")


# ── Utilitaires Git bas niveau ────────────────────────────────────────────

def _git_env() -> dict:
    """Construit l'environnement pour les commandes git avec auth HTTPS."""
    token = _get_token()
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = _GIT_NAME
    env["GIT_AUTHOR_EMAIL"] = _GIT_EMAIL
    env["GIT_COMMITTER_NAME"] = _GIT_NAME
    env["GIT_COMMITTER_EMAIL"] = _GIT_EMAIL
    # Forcer l'URL avec token embarqué
    env["GIT_ASKPASS"] = ""  # désactive tout helper externe
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _repo_url_https(repo: str) -> str:
    """URL HTTPS avec token embarqué pour auth silencieuse."""
    token = _get_token()
    return f"https://x-access-token:{token}@github.com/{GITHUB_ACCOUNT}/{repo}.git"


def _git(cmd: list[str], cwd: str = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Exécute une commande git avec token HTTPS."""
    env = _git_env()
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


def _ensure_repo(repo: str) -> str:
    """Vérifie que le repo existe en cache, le clone si nécessaire, pull sinon."""
    repo_path = os.path.join(GIT_CACHE, repo)
    git_dir = os.path.join(repo_path, ".git")

    if os.path.exists(git_dir):
        try:
            _git(["pull", "--ff-only"], cwd=repo_path, timeout=20)
        except RuntimeError as e:
            logging.warning(f"[GITHUB] Pull {repo} échoué: {e}")
    else:
        os.makedirs(GIT_CACHE, exist_ok=True)
        logging.info(f"[GITHUB] Clone {repo}...")
        _git(["clone", "--depth", "1", _repo_url_https(repo), repo_path], timeout=60)

    return repo_path


# ── Outils exposés ────────────────────────────────────────────────────────


@track()
def tool_github_list_repos() -> str:
    """Liste tous les dépôts GitHub du compte BadTechResearch."""
    try:
        repos = _api_get(f"/users/{GITHUB_ACCOUNT}/repos?per_page=100&sort=updated")
        if not repos:
            return "❌ Aucun dépôt trouvé."

        lines = ["📦 **Dépôts BadTechResearch :**\n"]
        for r in repos:
            name = r["name"]
            desc = (r.get("description") or "(pas de description)").strip()
            private = "🔒" if r.get("private") else "🌍"
            updated = r.get("pushed_at", "")[:10]
            lines.append(f"  {private} **{name}** — {desc}  _(mis à jour: {updated})_")
        lines.append(f"\n📊 {len(repos)} dépôt(s) au total.")
        return "\n".join(lines)
    except RuntimeError as e:
        return f"❌ Erreur listage repos: {e}"


@track()
def tool_github_list_branches(repo: str) -> str:
    """Liste les branches d'un dépôt GitHub.

    Args:
        repo: Nom du dépôt (ex: santana)
    """
    try:
        branches = _api_get(f"/repos/{GITHUB_ACCOUNT}/{repo}/branches?per_page=100")
        if not branches:
            return f"📂 Aucune branche trouvée dans `{repo}`."

        lines = [f"🌿 **Branches de {repo} :**\n"]
        for b in branches:
            name = b["name"]
            default = " ⬅️ défaut" if b.get("name") == "main" or b.get("name") == "master" else ""
            lines.append(f"  🌱 {name}{default}")
        return "\n".join(lines)
    except RuntimeError as e:
        return f"❌ Erreur listage branches: {e}"


@track()
def tool_github_list_files(repo: str, path: str = "") -> str:
    """Liste les fichiers et dossiers d'un dépôt GitHub.

    Args:
        repo: Nom du dépôt (ex: santana)
        path: Chemin dans le dépôt (laisser vide pour la racine)
    """
    try:
        repo_path = _ensure_repo(repo)
    except RuntimeError as e:
        return f"❌ Impossible d'accéder au dépôt '{repo}': {e}"

    target = os.path.join(repo_path, path) if path else repo_path
    if not os.path.exists(target):
        return f"❌ Chemin introuvable : '{path}' dans {repo}"

    try:
        items = sorted(os.listdir(target))
    except PermissionError:
        return f"❌ Permission refusée : {target}"

    if not items:
        return f"📂 Dossier vide : {repo}/{path}"

    lines = [f"📂 **{repo}/{path or ''}** :\n"]
    for item in items:
        if item.startswith("."):
            continue
        full = os.path.join(target, item)
        if os.path.isdir(full):
            lines.append(f"  📁 {item}/")
        else:
            size = os.path.getsize(full)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.0f} KB"
            else:
                size_str = f"{size / 1024 / 1024:.1f} MB"
            lines.append(f"  📄 {item}  ({size_str})")

    return "\n".join(lines)


@track()
def tool_github_read(repo: str, path: str, max_chars: int = 15000) -> str:
    """Lit le contenu d'un fichier dans un dépôt GitHub.

    Args:
        repo: Nom du dépôt (ex: santana)
        path: Chemin du fichier (ex: santana.py)
        max_chars: Nombre max de caractères (défaut: 15000)
    """
    try:
        repo_path = _ensure_repo(repo)
    except RuntimeError as e:
        return f"❌ Impossible d'accéder au dépôt '{repo}': {e}"

    full_path = os.path.abspath(os.path.join(repo_path, path))
    repo_abs = os.path.abspath(repo_path)
    if not full_path.startswith(repo_abs):
        return "❌ Chemin hors du dépôt."
    if not os.path.exists(full_path):
        return f"❌ Fichier introuvable : {path} dans {repo}"
    if os.path.isdir(full_path):
        return f"❌ '{path}' est un dossier. Utilise github_list_files."

    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        total = os.path.getsize(full_path)
        lines_count = content.count("\n")
        truncated = total > max_chars

        header = f"📄 **{repo}/{path}** ({lines_count} lignes, {min(total, max_chars)}/{total} caractères)"
        if truncated:
            header += " — ⚠️ TRONQUÉ"

        return f"{header}\n\n{content}"
    except Exception as e:
        return f"❌ Erreur lecture {path}: {e}"


@track()
def tool_github_write(repo: str, path: str, content: str, message: str = "") -> str:
    """Écrit ou met à jour un fichier dans un dépôt GitHub (commit + push).

    Santana peut écrire dans TOUS les dépôts BadTechResearch, y compris
    son propre code source (santana). Après écriture dans santana, il
    DOIT redémarrer via systemctl --user restart santana si le code a changé.

    Args:
        repo: Nom du dépôt (ex: santana)
        path: Chemin du fichier (ex: tools/github_tools.py)
        content: Contenu à écrire
        message: Message de commit (optionnel — auto-généré si vide)
    """
    try:
        repo_path = _ensure_repo(repo)
    except RuntimeError as e:
        return f"❌ Impossible d'accéder au dépôt '{repo}': {e}"

    full_path = os.path.abspath(os.path.join(repo_path, path))
    repo_abs = os.path.abspath(repo_path)
    if not full_path.startswith(repo_abs):
        return "❌ Chemin hors du dépôt."

    parent = os.path.dirname(full_path)
    os.makedirs(parent, exist_ok=True)

    is_new = not os.path.exists(full_path)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        return f"❌ Erreur écriture {path}: {e}"

    action = "Création" if is_new else "Mise à jour"
    commit_msg = message.strip() or f"{action} de {path} par Santana — {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    try:
        _git(["add", path], cwd=repo_path, timeout=10)
        result = _git(["commit", "-m", commit_msg], cwd=repo_path, timeout=10)
        _git(["push"], cwd=repo_path, timeout=30)

        hash_result = _git(["rev-parse", "HEAD"], cwd=repo_path, timeout=5)
        commit_hash = hash_result.stdout.strip()[:12]

        return (
            f"✅ {action} réussie dans `{repo}/{path}`\n"
            f"🔖 Commit: `{commit_hash}`\n"
            f"💬 Message: {commit_msg}"
        )
    except RuntimeError as e:
        err = str(e)
        if "nothing to commit" in err.lower():
            return f"ℹ️ Aucun changement — `{path}` est identique."
        return f"❌ Erreur Git: {err}"


@track()
def tool_github_delete_file(repo: str, path: str, message: str = "") -> str:
    """Supprime un fichier d'un dépôt GitHub (commit + push).

    Args:
        repo: Nom du dépôt (ex: santana)
        path: Chemin du fichier à supprimer
        message: Message de commit (optionnel)
    """
    try:
        repo_path = _ensure_repo(repo)
    except RuntimeError as e:
        return f"❌ Impossible d'accéder au dépôt '{repo}': {e}"

    full_path = os.path.abspath(os.path.join(repo_path, path))
    repo_abs = os.path.abspath(repo_path)
    if not full_path.startswith(repo_abs):
        return "❌ Chemin hors du dépôt."
    if not os.path.exists(full_path):
        return f"❌ Fichier introuvable : {path} dans {repo}"
    if os.path.isdir(full_path):
        return f"❌ '{path}' est un dossier. Suppression de dossiers non supportée."

    try:
        os.remove(full_path)
    except Exception as e:
        return f"❌ Erreur suppression {path}: {e}"

    commit_msg = message.strip() or f"Suppression de {path} par Santana — {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    try:
        _git(["rm", path], cwd=repo_path, timeout=10)
        _git(["commit", "-m", commit_msg], cwd=repo_path, timeout=10)
        _git(["push"], cwd=repo_path, timeout=30)

        hash_result = _git(["rev-parse", "HEAD"], cwd=repo_path, timeout=5)
        commit_hash = hash_result.stdout.strip()[:12]

        return (
            f"🗑️ Fichier `{repo}/{path}` supprimé.\n"
            f"🔖 Commit: `{commit_hash}`\n"
            f"💬 Message: {commit_msg}"
        )
    except RuntimeError as e:
        return f"❌ Erreur Git: {e}"


@track()
def tool_github_create_repo(name: str, description: str = "", private: bool = True) -> str:
    """Crée un nouveau dépôt GitHub.

    Args:
        name: Nom du dépôt (ex: mon-nouveau-projet)
        description: Description courte (optionnel)
        private: Dépôt privé ? (défaut: True)
    """
    try:
        data = {"name": name, "description": description, "private": private}
        result = _api_post(f"/user/repos", data)
        return (
            f"✅ Dépôt **{name}** créé avec succès !\n"
            f"🔗 {result['html_url']}\n"
            f"{'🔒 Privé' if private else '🌍 Public'}"
        )
    except RuntimeError as e:
        return f"❌ Erreur création dépôt: {e}"


@track()
def tool_github_create_branch(repo: str, branch: str, from_branch: str = "main") -> str:
    """Crée une nouvelle branche sur un dépôt.

    Args:
        repo: Nom du dépôt
        branch: Nom de la nouvelle branche (ex: feature/ma-fonctionnalite)
        from_branch: Branche source (défaut: main)
    """
    try:
        # Récupérer le SHA du dernier commit de la branche source
        ref_data = _api_get(f"/repos/{GITHUB_ACCOUNT}/{repo}/git/ref/heads/{from_branch}")
        sha = ref_data["object"]["sha"]

        # Créer la nouvelle référence
        _api_post(f"/repos/{GITHUB_ACCOUNT}/{repo}/git/refs", {
            "ref": f"refs/heads/{branch}",
            "sha": sha,
        })
        return f"✅ Branche **{branch}** créée sur `{repo}` (depuis `{from_branch}`)."
    except RuntimeError as e:
        return f"❌ Erreur création branche: {e}"


@track()
def tool_github_create_pr(repo: str, head: str, title: str, body: str = "", base: str = "main") -> str:
    """Crée une Pull Request.

    Args:
        repo: Nom du dépôt
        head: Branche source (celle qui contient les modifs)
        title: Titre de la PR
        body: Description de la PR (optionnel)
        base: Branche cible (défaut: main)
    """
    try:
        result = _api_post(f"/repos/{GITHUB_ACCOUNT}/{repo}/pulls", {
            "title": title,
            "body": body or "",
            "head": head,
            "base": base,
        })
        return (
            f"✅ Pull Request créée sur **{repo}**\n"
            f"🔗 {result['html_url']}\n"
            f"🏷️ #{result['number']} — {title}"
        )
    except RuntimeError as e:
        return f"❌ Erreur création PR: {e}"


def _api_put(path: str, data: dict) -> dict:
    """Requête PUT vers l'API GitHub."""
    url = f"{GITHUB_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers=_api_headers(), method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        raise RuntimeError(f"GitHub API PUT {path} → {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"GitHub API PUT {path} → {e}")


@track()
def tool_github_merge_pr(repo: str, pull_number: int, commit_title: str = "") -> str:
    """Merge une Pull Request.

    Args:
        repo: Nom du dépôt
        pull_number: Numéro de la PR
        commit_title: Titre du commit de merge (optionnel)
    """
    try:
        result = _api_put(f"/repos/{GITHUB_ACCOUNT}/{repo}/pulls/{pull_number}/merge", {
            "commit_title": commit_title or f"Merge PR #{pull_number} par Santana",
            "merge_method": "merge",
        })
        if result.get("merged"):
            return f"✅ PR #{pull_number} mergée sur `{repo}`.\n🔗 {result.get('sha', '')[:12]}"
        else:
            return f"⚠️ PR #{pull_number} non mergée: {result.get('message', 'raison inconnue')}"
    except RuntimeError as e:
        if "Merge conflict" in str(e):
            return f"❌ Conflit de merge sur PR #{pull_number} — intervention manuelle nécessaire."
        return f"❌ Erreur merge PR: {e}"


# ── Registre Santana ───────────────────────────────────────────────────────

def register_all():
    """Enregistre tous les outils GitHub dans le registre Santana."""
    from tools.tools import _register

    _register("github_list_repos",    tool_github_list_repos,    arg_map={})
    _register("github_list_branches", tool_github_list_branches, arg_map={"repo": "repo"})
    _register("github_list_files",    tool_github_list_files,    arg_map={"repo": "repo", "path": "path"},
              defaults={"path": ""})
    _register("github_read",          tool_github_read,          arg_map={"repo": "repo", "path": "path", "max_chars": "max_chars"},
              defaults={"max_chars": "15000"})
    _register("github_write",         tool_github_write,         arg_map={"repo": "repo", "path": "path", "content": "content", "message": "message"},
              defaults={"message": ""})
    _register("github_delete_file",   tool_github_delete_file,   arg_map={"repo": "repo", "path": "path", "message": "message"},
              defaults={"message": ""})
    _register("github_create_repo",   tool_github_create_repo,   arg_map={"name": "name", "description": "description", "private": "private"},
              defaults={"description": "", "private": "True"})
    _register("github_create_branch", tool_github_create_branch, arg_map={"repo": "repo", "branch": "branch", "from_branch": "from_branch"},
              defaults={"from_branch": "main"})
    _register("github_create_pr",     tool_github_create_pr,     arg_map={"repo": "repo", "head": "head", "title": "title", "body": "body", "base": "base"},
              defaults={"body": "", "base": "main"})
    _register("github_merge_pr",      tool_github_merge_pr,      arg_map={"repo": "repo", "pull_number": "pull_number", "commit_title": "commit_title"},
              defaults={"commit_title": ""})

    logging.info("[GITHUB] 10 outils enregistrés : github_list_repos, github_list_branches, github_list_files, github_read, github_write, github_delete_file, github_create_repo, github_create_branch, github_create_pr, github_merge_pr")
