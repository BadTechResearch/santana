"""Orchestrateur d'outils Santana.
Importe les outils depuis les modules spécialisés.
Maintient le registre dynamique (_register / _dispatch) et la liste TOOLS pour le LLM.
Les outils trop spécifiques ou dépendants (workspace_state, tmux, vm, etc.) restent ici.
"""

import os
import json
import logging
import re
import requests
import time
import subprocess
import asyncio
from datetime import datetime

from core.db import get_db
from metrics import track

# ─── Registry (découverte automatique d'outils) ──────────────────────────────
from tools.registry import register as _reg_register, dispatch as _reg_dispatch, get_tools as _reg_get_tools
from core.utils import get_base_dir

# ─── Auth serveurs auxiliaires ──────────────────────────────────────────────
_MCP_API_KEY = os.getenv("MCP_API_KEY", "")
_MCP_HEADERS = {"X-API-Key": _MCP_API_KEY} if _MCP_API_KEY else {}

BASE_DIR = get_base_dir()

# Outils de base (définition JSON pour le LLM)
TOOLS = json.load(open(os.path.join(BASE_DIR, "tools", "tools.json"), "r"))

# ─── Outils spécialisés importés ────────────────────────────────────────
from tools.web_search import tool_web_search

# ─── Tool Creator (création dynamique d'outils par le LLM) ─────────────────
from tools.tool_creator import create_tool as _tool_creator_create, install_dependencies as _tool_creator_install
from tools.tool_creator import list_user_tools as _tool_creator_list, delete_user_tool as _tool_creator_delete
from tools.memory_ops import tool_memory_query, tool_atlas
from tools.social_search import social_search as tool_social_search_raw
from tools.social_search import tool_social_news, tool_social_browser, tool_twitter_search, tool_reddit_search
from tools.social_search import tool_instagram_search, tool_tiktok_search
from tools.social_search import tool_twitter_lookup, tool_reddit_lookup, tool_instagram_lookup, tool_tiktok_lookup
from tools.code_exec import run_code as tool_run_code_raw
from tools.vm_security import validate_command, validate_script, safe_env
from tools.youtube import tool_youtube_info
from tools.skills_manager import skill_view as _skill_view, skill_manage as _skill_manage, skill_list as _skill_list
from core.delegate import delegate_task as _delegate_task_async

# ─── Nouveaux outils (Playwright + PDF) ───────────────────────────────────
from tools.browser import browser_navigate, browser_screenshot
from tools.pdf_reader import read_pdf as _read_pdf_raw

# ─── Modules @tool : enregistrement automatique via décorateur ───────────
# Chaque import déclenche les décorateurs @tool() qui s'enregistrent
# dans tools/registry.py.
from tools import code_modify  # expose code_modify, code_list_sources, restart_self

# ─── Outils MCP (chargement paresseux, Correctif 3) ─────────────────────────
_MCP_TOOLS_CACHED = None

def is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp_") if name else False

def mcp_call(name: str, args: dict, timeout: int = 120) -> str:
    return "Erreur: outils MCP non disponibles (MCP non chargé)"

_MCP_IMPORTED = False

def _ensure_mcp_loaded():
    global _MCP_TOOLS_CACHED, TOOLS, is_mcp_tool, mcp_call, _MCP_IMPORTED
    if _MCP_IMPORTED:
        return
    try:
        from tools import mcp as _mcp_module
        _MCP_TOOLS_CACHED = _mcp_module.discover_all_servers()
        if _MCP_TOOLS_CACHED:
            TOOLS.extend(_MCP_TOOLS_CACHED)
            logging.info(f"[MCP] {len(_MCP_TOOLS_CACHED)} outils MCP charges (lazy)")
            is_mcp_tool = _mcp_module.is_mcp_tool
            mcp_call = _mcp_module.call_tool
    except Exception as _mcp_e:
        logging.error(f"[MCP] MCP lazy load failure: {_mcp_e}")
    finally:
        _MCP_IMPORTED = True

_TZ = None
try:
    import pytz
    _TZ = pytz.timezone("Africa/Kinshasa")
except Exception as e:
    logging.error("[TOOLS] pytz import fallback: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# OUTILS SPÉCIALISÉS (trop spécifiques pour justifier un fichier dédié)
# ═══════════════════════════════════════════════════════════════════════════════

def tool_get_datetime() -> str:
    try:
        now = datetime.now(_TZ) if _TZ else datetime.now()
        return now.strftime("%A %d %B %Y, %H:%M")
    except Exception:
        logging.debug("[TOOL] get_datetime echec, fallback now()")
        return str(datetime.now())


def tool_save_skill(title, trigger, steps, pitfalls, verification):
    try:
        return _tool_save_skill(title, trigger, steps, pitfalls, verification)
    except Exception as e:
        logging.error(f"[TOOL] save_skill error: {e}")
        return "Outil temporairement indisponible"

def _tool_save_skill(title, trigger, steps, pitfalls, verification):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO skills (title, trigger_condition, steps, pitfalls, verification) VALUES (?, ?, ?, ?, ?)",
            (title, trigger, steps, pitfalls, verification),
        )
        conn.commit()
        return f"Skill {title} sauvegardee."
    except Exception as e:
        return f"Erreur skill: {str(e)}"


def tool_search_skills(query):
    try:
        return _tool_search_skills(query)
    except Exception as e:
        logging.error(f"[TOOL] search_skills error: {e}")
        return "Outil temporairement indisponible"

def _tool_search_skills(query):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT title, steps, pitfalls, usage_count FROM skills WHERE title LIKE ? OR trigger_condition LIKE ? ORDER BY usage_count DESC LIMIT 6",
            (f"%{query}%", f"%{query}%"),
        )
        rows = c.fetchall()
        if not rows:
            return f"Aucune skill trouvee pour: {query}"
        c.execute("UPDATE skills SET usage_count = usage_count + 1 WHERE title = ?", (rows[0][0],))
        conn.commit()
        return "\n---\n".join(
            f"📌 {t} (utilisee {u}x)\n  Etapes: {s}\n  Pieges: {p}"
            for t, s, p, u in rows
        )
    except Exception as e:
        return f"Erreur search_skills: {str(e)}"


def tool_web_navigate(url: str) -> str:
    """Ouvre une URL et extrait le contenu textuel via Playwright (Chromium headless intégré)."""
    try:
        return browser_navigate(url)
    except Exception as e:
        logging.error(f"[TOOL] web_navigate error: {e}")
        return f"Erreur web_navigate: {str(e)}"


def tool_web_screenshot(url: str) -> str:
    """Prend une capture d'écran d'une page web via Playwright (Chromium headless intégré)."""
    try:
        return browser_screenshot(url)
    except Exception as e:
        logging.error(f"[TOOL] web_screenshot error: {e}")
        return f"Erreur web_screenshot: {str(e)}"


# ─── SELF INSPECT — Auto-description dynamique ────────────────────────────

def tool_self_inspect() -> str:
    """Outil OBLIGATOIRE pour répondre à Serge quand il demande de décrire ton code,
    ton architecture, tes outils, qui tu es, ce que tu sais faire.
    Retourne un rapport markdown complet et lisible (pas de code brut).
    """
    try:
        from agent.self import build_report
        return build_report()
    except Exception as e:
        logging.error(f"[TOOL] self_inspect error: {e}")
        return json.dumps({"error": f"Auto-inspection indisponible: {str(e)}"})


def tool_run_code(code: str, language: str = "python", timeout: int = 30) -> str:
    """Exécute du code Python ou bash dans un environnement sandboxé.
    
    Args:
        code: Le code à exécuter
        language: 'python' ou 'bash' (défaut: python)
        timeout: Temps max en secondes (défaut: 30, max: 120)
    """
    try:
        t = int(timeout) if timeout is not None else 30
    except (ValueError, TypeError):
        t = 30
    return tool_run_code_raw(code, language=language, timeout=t)


# ─── SOCIAL SEARCH (wrapper vers social_search.py) ──────────────────────────

@track()
def tool_social_search(query="", platform="all", count=5) -> str:
    try:
        return tool_social_search_raw(query, platform, int(count))
    except Exception as e:
        logging.error(f"[TOOL] Social search failure: {e}")
        return json.dumps({"note": "social_search non disponible. Utilise web_search."})


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRE DYNAMIQUE D'OUTILS
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Plus de _register / _dispatch — utiliser tools.registry ─────────────
# Les outils sont enregistrés via registry.register() ci-dessous.
# Voir tools/registry.py pour l'API : @tool(), register(), dispatch(), get_tools()
# ─── FS_READ — Lecture locale de fichiers (auto-introspection) ───────────────

_SAFE_BASE = get_base_dir()
_SENSITIVE_FRAGMENTS = [
    "token", "secret", "key", "password", ".env",
    "credential", "private", "auth"
]


def tool_fs_read(path: str, offset: int = 1, limit: int = 200) -> str:
    """Lit un fichier dans ~/santana/. Permet à Santana de s'auto-inspecter."""
    # Forcer les types (le LLM envoie parfois des strings)
    offset = int(offset) if offset is not None else 1
    limit = int(limit) if limit is not None else 200
    abs_path = os.path.realpath(os.path.join(_SAFE_BASE, path))
    if not abs_path.startswith(_SAFE_BASE):
        return "Erreur: chemin hors de ~/santana/."

    # Bloquer les fichiers sensibles
    lower_path = abs_path.lower()
    if any(frag in lower_path for frag in _SENSITIVE_FRAGMENTS):
        return "Erreur: fichier sensible."

    try:
        with open(abs_path, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return "Erreur: fichier introuvable."
    except Exception as e:
        return f"Erreur: {e}"

    total = len(lines)
    start = max(0, offset - 1)
    end = min(total, start + limit)
    content = "".join(lines[start:end])
    return f"{abs_path} ({total} lignes, affiche {start+1}-{end})\n{content}"


def tool_fs_write(path: str, content: str) -> str:
    """Écrit un fichier dans ~/santana/skills/ ou ~/santana/workspace/.
    Permet à Santana de créer et modifier ses propres fichiers.

    Args:
        path: Chemin relatif (ex: skills/mon-skill.md, workspace/rapport.md)
        content: Contenu complet du fichier

    Returns:
        Confirmation ou message d'erreur
    """
    _WRITE_SAFE_DIRS = ["tools", "agent", "core", "skills", "workspace", "tests", "soul", "scripts", "metrics", "atlas_engine", "memory"]
    # Normaliser le chemin
    clean_path = path.lstrip("/").lstrip(".")
    parts = clean_path.split("/")
    if not parts or parts[0] not in _WRITE_SAFE_DIRS:
        return f"Erreur: écriture autorisée uniquement dans {_WRITE_SAFE_DIRS}."
    # Extension autorisée
    _ALLOWED_EXTS = {".py", ".md", ".toml", ".txt", ".json", ".yaml", ".yml", ".cfg", ".ini", ".sh"}
    ext = os.path.splitext(clean_path)[1].lower()
    if ext and ext not in _ALLOWED_EXTS:
        return f"Erreur: extension '{ext}' non autorisée."
    abs_path = os.path.realpath(os.path.join(_SAFE_BASE, clean_path))
    if not abs_path.startswith(_SAFE_BASE):
        return "Erreur: chemin hors de ~/santana/."
    # Bloquer les fichiers sensibles
    lower_path = abs_path.lower()
    if any(frag in lower_path for frag in _SENSITIVE_FRAGMENTS):
        return "Erreur: fichier sensible."
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        total = len(content)
        lines = content.count("\n") + 1
        return f"✅ Écrit: {abs_path} ({lines} lignes, {total} chars)"
    except Exception as e:
        logging.error(f"[TOOL] fs_write error: {e}")
        return f"Erreur: {str(e)}"


def tool_delegate_task(goal: str, context: str = "") -> str:
    """Délègue une tâche à un sous-agent isolé (exécution parallèle).

    execute_tool()/dispatch() appellent cet outil de façon SYNCHRONE depuis
    l'intérieur de la boucle asyncio déjà active de react_loop() — un simple
    asyncio.run() ici lève RuntimeError("asyncio.run() cannot be called from
    a running event loop") à 100% des appels réels. On lance donc la
    coroutine dans un thread dédié avec sa propre boucle d'événements, et on
    bloque jusqu'à son résultat — le thread appelant (celui de react_loop)
    attend déjà la fin de l'outil de toute façon, delegate_task n'étant ni
    dans _PARALLEL_TOOLS ni _EXPENSIVE_TOOLS.

    Args:
        goal: Objectif précis de la tâche
        context: Contexte additionnel (fichiers, contraintes, etc.)

    Returns:
        Résultat textuel de la sous-tâche
    """
    import threading
    result: dict = {}

    def _run_in_new_loop():
        try:
            result["value"] = asyncio.run(_delegate_task_async(goal=goal, context=context))
        except Exception as e:
            logging.error(f"[TOOL] delegate_task error: {e}")
            result["value"] = json.dumps({"error": f"Erreur délégation: {str(e)}"})

    t = threading.Thread(target=_run_in_new_loop, daemon=True)
    t.start()
    t.join()
    return result.get("value", json.dumps({"error": "delegate_task: aucun résultat"}))


def tool_read_pdf(path: str, max_chars: int = 10000) -> str:
    """Extrait le texte d'un fichier PDF via pypdf.
    
    Args:
        path: Chemin du PDF (absolu ou relatif depuis ~/santana/)
        max_chars: Nombre max de caractères (défaut: 10000, max: 50000)
    
    Returns:
        Texte extrait page par page
    """
    try:
        return _read_pdf_raw(path, max_chars=max_chars)
    except Exception as e:
        logging.error(f"[TOOL] read_pdf error: {e}")
        return f"Erreur lecture PDF: {str(e)}"


# ─── REGISTRE ─────────────────────────────────────────────────────────────────

# Enregistrement des outils via le nouveau registry (compatible legacy)
_reg_register("web_search", tool_web_search, arg_map={"query": "query"})
_reg_register("memory_query", tool_memory_query, arg_map={"query": "query"})
_reg_register("get_datetime", tool_get_datetime, arg_map={})
_reg_register("save_skill", tool_save_skill, arg_map={
    "title": "title", "trigger": "trigger",
    "steps": "steps", "pitfalls": "pitfalls",
    "verification": "verification"
})
_reg_register("search_skills", tool_search_skills, arg_map={"query": "query"})
_reg_register("web_navigate", tool_web_navigate, arg_map={"url": "url"})
_reg_register("web_screenshot", tool_web_screenshot, arg_map={"url": "url"})
_reg_register("atlas", tool_atlas, arg_map={"context": "context"})
_reg_register("social_search", tool_social_search, arg_map={"query": "query", "platform": "platform", "count": "count"}, defaults={"count": "5"})
_reg_register("social_news", tool_social_news, arg_map={"query": "query", "platform": "platform", "max_results": "max_results"}, defaults={"platform": "all", "max_results": "8"})
_reg_register("social_browser", tool_social_browser, arg_map={"url": "url", "timeout": "timeout"}, defaults={"timeout": "20"})
_reg_register("twitter_search", tool_twitter_search, arg_map={"query_search": "query_search", "max_tweets": "max_tweets"}, defaults={"max_tweets": "10"})
_reg_register("reddit_search", tool_reddit_search, arg_map={"query": "query", "subreddit": "subreddit", "max_posts": "max_posts"}, defaults={"max_posts": "10"})
_reg_register("instagram_search", tool_instagram_search, arg_map={"query": "query", "max_posts": "max_posts"}, defaults={"max_posts": "10"})
_reg_register("tiktok_search", tool_tiktok_search, arg_map={"query": "query", "max_posts": "max_posts"}, defaults={"max_posts": "10"})
_reg_register("twitter_lookup", tool_twitter_lookup, arg_map={"handle": "handle", "query": "query", "max_tweets": "max_tweets"}, defaults={"query": "", "max_tweets": "5"})
_reg_register("reddit_lookup", tool_reddit_lookup, arg_map={"subreddit": "subreddit", "max_posts": "max_posts"}, defaults={"max_posts": "5"})
_reg_register("instagram_lookup", tool_instagram_lookup, arg_map={"username": "username", "max_posts": "max_posts"}, defaults={"max_posts": "5"})
_reg_register("tiktok_lookup", tool_tiktok_lookup, arg_map={"username": "username", "max_posts": "max_posts"}, defaults={"max_posts": "5"})
_reg_register("self_inspect", tool_self_inspect, arg_map={})
_reg_register("fs_read", tool_fs_read,
              arg_map={"path": "path", "offset": "offset", "limit": "limit"},
              defaults={"offset": "1", "limit": "200"})
_reg_register("run_code", tool_run_code, arg_map={"code": "code", "language": "language", "timeout": "timeout"}, defaults={"language": "python", "timeout": "30"})
_reg_register("youtube_info", tool_youtube_info, arg_map={"url": "url", "include_transcript": "include_transcript"}, defaults={"include_transcript": "false"})
_reg_register("fs_write", tool_fs_write, arg_map={"path": "path", "content": "content"})
_reg_register("skill_view", _skill_view, arg_map={"name": "name"})
_reg_register("skill_manage", _skill_manage, arg_map={"action": "action", "name": "name", "content": "content"}, defaults={"content": ""})
_reg_register("skill_list", _skill_list, arg_map={})
_reg_register("delegate_task", tool_delegate_task, arg_map={"goal": "goal", "context": "context"}, defaults={"context": ""})
_reg_register("read_pdf", tool_read_pdf, arg_map={"path": "path", "max_chars": "max_chars"}, defaults={"max_chars": "10000"})

# F9 — Gouverneur de coût (défini dans tools.json, dispatch dans cost_governor.py)
from tools.cost_governor import cost_governor_dispatch as _cost_governor_dispatch
_reg_register("cost_governor", _cost_governor_dispatch,
              arg_map={"action": "action", "budget": "budget"},
              defaults={"action": "status", "budget": ""})

# Compatibilité : exposer les alias legacy pour les importeurs anciens
_register = _reg_register
_dispatch = _reg_dispatch

# Fusionner tools.json (base) + registry (les outils enregistrés via @tool/register)
# On garde tools.json comme base car il contient tous les outils (dont vm_exec, github_*, etc.)
# On y ajoute les outils du registry qui ne seraient pas déjà dans tools.json
_BASE_TOOL_NAMES = {t["function"]["name"] for t in TOOLS}
for reg_tool in _reg_get_tools():
    if reg_tool["function"]["name"] not in _BASE_TOOL_NAMES:
        TOOLS.append(reg_tool)
logging.info(f"[TOOLS] {len(TOOLS)} outils (base: {len(_BASE_TOOL_NAMES)}, registry: {len(_reg_get_tools())})")

# Chargement EAGER des outils MCP (pas lazy) — pour que le LLM les voie dans TOOLS
_ensure_mcp_loaded()


# ═══════════════════════════════════════════════════════════════════════════════
# WORKSPACE STATE (état persistant via SQLite)
# ═══════════════════════════════════════════════════════════════════════════════

def tool_workspace_state(action: str, key: str = "", value: str = "") -> str:
    """Stocke/récupère/gère des variables d'état persistantes.
    Actions : set, get, list, clear
    """
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS ws (
            key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
        )""")
        conn.commit()

        if action == "set":
            c.execute(
                "INSERT OR REPLACE INTO ws (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                (key, value)
            )
            conn.commit()
            return f"ws:{key} = {value[:80]}"
        elif action == "get":
            c.execute("SELECT value FROM ws WHERE key=?", (key,))
            row = c.fetchone()
            return row[0] if row else "aucune valeur"
        elif action == "list":
            c.execute("SELECT key, value FROM ws ORDER BY updated_at DESC LIMIT 20")
            rows = c.fetchall()
            return "\n".join(f"{k}: {v[:80]}" for k, v in rows) if rows else "(vide)"
        elif action == "clear":
            c.execute("DELETE FROM ws")
            conn.commit()
            return "ws efface."
        return "Actions: set, get, list, clear"
    except Exception as e:
        return f"Erreur ws: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════════════
# TMUX SESSION
# ═══════════════════════════════════════════════════════════════════════════════

def _tmux_validate_command(cmd: str) -> tuple[bool, str]:
    """Valide une commande tmux via l'allowlist vm_security (pas denylist).

    Avant juin 2026 : denylist faible (substring matching "rm" → faux positif
    rmdir, "cat /etc/shadow" passait sans être bloqué). Remplacée par la
    validation standard vm_security pour une couche de défense uniforme."""
    from tools.vm_security import validate_command
    return validate_command(cmd)


def tool_tmux_session(action: str, session_name: str = "", command: str = "") -> str:
    """Controle une session tmux.
    Actions: list, create, send, read, kill
    """
    try:
        if action == "list":
            r = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=5)
            return r.stdout or "aucune session"

        elif action == "create":
            r = subprocess.run(
                ["tmux", "new-session", "-d", "-s", session_name],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, "export TERM=xterm-256color", "Enter"],
                    capture_output=True, timeout=3
                )
                return f"Session {session_name} creee"
            return f"Erreur creation: {r.stderr}"

        elif action == "send":
            valid, msg = _tmux_validate_command(command)
            if not valid:
                return msg
            r = subprocess.run(
                ["tmux", "send-keys", "-t", session_name, command, "Enter"],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode != 0:
                return f"Erreur envoi: {r.stderr}"
            # Attendre un peu et capturer
            time.sleep(1)
            r2 = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-30"],
                capture_output=True, text=True, timeout=5
            )
            return r2.stdout[-3000:] if r2.stdout else "Commande envoyee"

        elif action == "read":
            r = subprocess.run(
                ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-40"],
                capture_output=True, text=True, timeout=5
            )
            return r.stdout[-4000:] if r.stdout else "Panne vide"

        elif action == "kill":
            subprocess.run(["tmux", "kill-session", "-t", session_name],
                         capture_output=True, timeout=5)
            return f"Session {session_name} tuee"

        return "Actions: list, create, send, read, kill"
    except FileNotFoundError:
        return "tmux non installe"
    except subprocess.TimeoutExpired:
        return "Timeout tmux"
    except Exception as e:
        return f"Erreur tmux: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════════════
# RENDER PREVIEW
# ═══════════════════════════════════════════════════════════════════════════════

import tempfile, webbrowser

_LIVRE_PATTERN = re.compile(r'^[A-Z][a-zA-Z0-9_/-]+\.(md|txt)$')
_GIT_RE = re.compile(r'^https?://github\.com/|^git@')

def tool_render_preview(source: str) -> str:
    """Génère un aperçu HTML/navigateur d'un fichier markdown local ou distant."""
    try:
        html = _render_preview_direct(source, "")
        if not html:
            return "Impossible de generer l apercu"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(html)
            preview_path = f.name
        webbrowser.open("file://" + preview_path)
        return f"Apercu genere: {preview_path}"
    except Exception as e:
        return f"Erreur preview: {str(e)}"


def _render_preview_direct(url: str, output_path: str) -> str:
    """Convertit un fichier markdown en HTML autonome via GitHub ou local.

    Args:
        url: URL GitHub, fichier local ou nom de fichier dans skills/
        output_path: ignoré (retourne le HTML)
    """
    try:
        import re, urllib.parse

        markdown = None
        source_name = url

        # GitHub URL
        if _GIT_RE.match(url):
            # Transformer raw.githubusercontent.com
            parsed = urllib.parse.urlparse(url)
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 5 and "blob" in path_parts:
                idx = path_parts.index("blob")
                path_parts[idx] = "refs/heads/main" if "main" in url else "refs/heads/master"
                raw_url = f"https://raw.githubusercontent.com/{'/'.join(path_parts[1:])}"
            else:
                raw_url = url.replace("github.com", "raw.githubusercontent.com")
                raw_url = raw_url.replace("/blob/", "/")
            source_name = url
            r = requests.get(raw_url, timeout=15)
            if r.status_code == 200:
                markdown = r.text

        # Fichier local
        elif url.startswith("/") or url.startswith("~"):
            path = os.path.expanduser(url)
            if os.path.isfile(path):
                with open(path) as f:
                    markdown = f.read()
                    source_name = path

        # Nom de fichier dans skills/
        elif _LIVRE_PATTERN.match(url):
            for d in ["skills", "livres", "."]:
                p = os.path.join(BASE_DIR, d, url)
                if os.path.isfile(p):
                    with open(p) as f:
                        markdown = f.read()
                        source_name = p
                    break

        if not markdown:
            return f"Fichier non trouve: {url}"

        # Conversion MD → HTML simple
        html_parts = []
        in_code = False
        for line in markdown.split("\n"):
            if line.startswith("```"):
                in_code = not in_code
                html_parts.append("<pre><code>" if in_code else "</code></pre>")
            elif in_code:
                html_parts.append(line + "\n")
            elif line.startswith("# "):
                html_parts.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                html_parts.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                html_parts.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("- "):
                html_parts.append(f"<li>{line[2:]}</li>")
            elif line.startswith("> "):
                html_parts.append(f"<blockquote>{line[2:]}</blockquote>")
            elif line.strip() == "":
                html_parts.append("<br>")
            else:
                html_parts.append(f"<p>{line}</p>")

        body = "\n".join(html_parts)
        return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{os.path.basename(source_name)}</title>
<style>body{{max-width:800px;margin:auto;padding:20px;font-family:sans-serif;line-height:1.6}}
h1,h2,h3{{color:#333}}pre{{background:#f4f4f4;padding:10px;overflow-x:auto}}
blockquote{{border-left:4px solid #ccc;margin-left:0;padding-left:16px;color:#666}}
li{{margin:4px 0}}</style></head><body>
<h2>📄 {source_name}</h2>
{body}</body></html>"""

    except Exception as e:
        logging.error(f"[RENDER_PREVIEW] Erreur: {e}")
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
# VM EXEC — validation par allowlist (tools/vm_security.py), pas denylist.
# Historique : l'ancienne denylist (rm -rf, find -delete, interpréteurs inline)
# était contournable via `bash -c "..."`, `os.system()`, `curl|bash` — voir
# CLAUDE-AUDIT-4-FINAL.md section BUGS RÉELS. Remplacée entièrement.
# ═══════════════════════════════════════════════════════════════════════════════


def tool_vm_exec(command: str, workdir: str = "") -> str:
    """Execute une commande shell simple sur la VM (allowlist, environnement minimal)."""
    valid, msg = validate_command(command)
    if not valid:
        return msg
    try:
        env = safe_env()
        if workdir:
            env["CWD"] = workdir
        # Sandbox mount : la commande validee est executee dans son propre
        # namespace mount → pas d'acces au filesystem hote en dehors de ~
        _quoted = command.replace("'", "'\\''")
        _safe_cmd = f"unshare --user --map-root-user --mount --propagation private bash -c '{_quoted}'"
        r = subprocess.run(
            _safe_cmd, shell=True, capture_output=True, text=True, timeout=120,
            env=env, cwd=workdir or os.path.expanduser("~")
        )
        output = r.stdout[-5000:] if r.stdout else ""
        if r.stderr:
            output += "\n[stderr]\n" + r.stderr[-1000:]
        return output or "(rien)"
    except subprocess.TimeoutExpired:
        return "Timeout 120s"
    except Exception as e:
        return f"Erreur exec: {str(e)}"


def tool_vm_exec_script(script: str, workdir: str = "") -> str:
    """Execute un script shell (multiligne) sur la VM. Chaque ligne du script
    doit individuellement passer l'allowlist (vm_security.validate_script) —
    bash n'est utilisé que comme interpréteur du script déjà entièrement vérifié,
    jamais comme relais pour une commande non vérifiée."""
    valid, msg = validate_script(script)
    if not valid:
        return f"Script refuse: {msg}"
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write("#!/bin/bash\nset -e\n")
            f.write(script)
            script_path = f.name
        os.chmod(script_path, 0o700)
        r = subprocess.run(
            ["bash", script_path], capture_output=True, text=True, timeout=180,
            cwd=workdir or os.path.expanduser("~"), env=safe_env()
        )
        os.unlink(script_path)
        output = r.stdout[-5000:] if r.stdout else ""
        if r.stderr:
            output += "\n[stderr]\n" + r.stderr[-1000:]
        return output or "(rien)"
    except subprocess.TimeoutExpired:
        return "Timeout 180s"
    except Exception as e:
        return f"Erreur script: {str(e)}"


# ── Enregistrement des outils de tool_creator ──────────────────────────
_reg_register("tool_create", _tool_creator_create,
    arg_map={"name": "name", "description": "description", "parameters_json": "parameters_json",
             "code": "code", "dependencies": "dependencies", "requires_network": "requires_network"},
    defaults={"parameters_json": "{}", "dependencies": "", "requires_network": False})
_reg_register("install_dependencies", _tool_creator_install,
    arg_map={"name": "name", "requirements": "requirements"})
_reg_register("list_user_tools", _tool_creator_list)
_reg_register("delete_user_tool", _tool_creator_delete,
    arg_map={"name": "name"})

# ── Enregistrement des outils définis ci-dessus ─────────────────────────
# (placé ici car les fonctions sont définies plus haut dans ce fichier)
# vm_exec et vm_exec_script retirés le 20 juin 2026 — trop dangereux, Santana
# bouclait sur des commandes refusées par le security sandbox.
# Utiliser run_code (sandboxé) à la place.
# _reg_register("vm_exec", tool_vm_exec, ...)
# _reg_register("vm_exec_script", tool_vm_exec_script, ...)
_reg_register("workspace_state", tool_workspace_state, arg_map={"action": "action", "key": "key", "value": "value"}, defaults={"key": "", "value": ""})
_reg_register("tmux_session", tool_tmux_session, arg_map={"action": "action", "session_name": "session_name", "command": "command"}, defaults={"session_name": "", "command": ""})
_reg_register("render_preview", tool_render_preview, arg_map={"source": "source"})

# ── Outils GitHub (importés depuis github_tools.py) ─────────────────────
from tools.github_tools import register_all as _github_register_all
_github_register_all()

# ── Synchronisation TOOLS ← Registry ──────────────────────────────────────
# Les outils enregistrés via registry.register() ne sont pas automatiquement
# dans TOOLS (chargé depuis tools.json). On synchronise ici pour que le
# guardrail dans react_loop (basé sur TOOLS) voie tous les outils.
from tools.registry import get_tools as _reg_get_tools
_registry_all = _reg_get_tools()
_existing_names = {t["function"]["name"] for t in TOOLS}
for _rt in _registry_all:
    if _rt["function"]["name"] not in _existing_names:
        TOOLS.append(_rt)
        _existing_names.add(_rt["function"]["name"])
if len(_registry_all) != len(TOOLS):
    logging.info("[TOOLS] Synchronisé: %d outils registry → %d outils TOOLS (+%d GitHub/MCP)",
                  len(_registry_all), len(TOOLS), len(TOOLS) - len(_existing_names))
else:
    logging.info("[TOOLS] %d outils chargés (registry + JSON synchronisés)", len(TOOLS))


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTE TOOL (point d'entrée unique depuis react_loop)
# ═══════════════════════════════════════════════════════════════════════════════

def execute_tool(name: str, args: dict) -> str:
    _ensure_mcp_loaded()

    # ── F7 — Rate-limiting granulaire par outil ─────────────────────────────
    # Seuls les outils coûteux déclarés dans TOOL_RATE_LIMITS sont bridés.
    try:
        from agent.securite import check_tool_rate_limit
        _tok = len(json.dumps(args, ensure_ascii=False)) // 4 if args else 0
        _ok, _raison = check_tool_rate_limit(name, tokens=_tok)
        if not _ok:
            logging.warning("[SECURITE] Outil '%s' refusé: %s", name, _raison)
            return json.dumps({"error": _raison}, ensure_ascii=False)
    except Exception as _se:
        logging.debug("[SECURITE] check_tool_rate_limit indisponible: %s", _se)

    # 1. Essayer le dispatch (outils enregistrés dans ce fichier)
    result = _dispatch(name, args)

    # 2. Essayer MCP
    if result is None:
        if is_mcp_tool(name):
            result = mcp_call(name, args)
        else:
            # 3. Essayer les outils MCP
            try:
                from tools.mcp import call_tool as mcp_call_tool
                result = mcp_call_tool(name, args)
            except Exception as e:
                result = json.dumps({"error": f"Outil '{name}' non trouve: {str(e)}"})

    # ── F12 — Détecteur d'échec / auto-réparation ───────────────────────────
    try:
        from agent.orchestration import record_tool_result
        _succes = not _resultat_est_echec(result)
        record_tool_result(name, _succes, erreur="" if _succes else str(result)[:200])
    except Exception as _re:
        logging.debug("[ORCHESTRATION] record_tool_result indisponible: %s", _re)

    return result


def _resultat_est_echec(result) -> bool:
    """Heuristique : un résultat d'outil signale-t-il un échec ?"""
    if result is None:
        return True
    s = str(result).strip()
    if not s:
        return True
    bas = s.lower()
    return (
        '"error"' in bas
        or bas.startswith("erreur")
        or "temporairement indisponible" in bas
        or "non trouve" in bas
    )
