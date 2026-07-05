"""Client MCP léger pour Santana (sans SDK, protocole JSON-RPC stdio pur).

Connexion aux serveurs MCP configurés dans ~/santana/mcp_config.json.
Découverte automatique des outils et conversion au format OpenAI function-calling.
"""

import os
import json
import logging
import subprocess
import threading
import time
from typing import Optional
from queue import Queue, Empty
from core.utils import get_base_dir

BASE_DIR = get_base_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "mcp_config.json")

# Cache des connexions : {name: {"proc": subprocess, "tools": [...], "lock": Lock}}
_connections: dict = {}

# ─── Circuit Breaker ─────────────────────────────────────────────────────────────────
# Évite les appels répétés à un serveur MCP en panne
_CB_STATE: dict = {}  # {server_name: {"failures": int, "last_failure": float, "open_until": float}}
_CB_THRESHOLD = 3       # Échecs consécutifs avant ouverture
_CB_COOLDOWN = 60       # Secondes avant tentative de rétablissement (half-open)


def _cb_check(server: str) -> bool:
    """Vérifie si le circuit est ouvert pour un serveur. Retourne True si autorisé."""
    state = _CB_STATE.get(server)
    if not state or state.get("failures", 0) < _CB_THRESHOLD:
        return True  # Circuit fermé → OK
    if time.time() > state.get("open_until", 0):
        # Half-open → on laisse passer un appel
        logging.info(f"[MCP-CB] Circuit half-open pour {server}, tentative...")
        return True
    elapsed = time.time() - state.get("last_failure", 0)
    logging.warning(f"[MCP-CB] Circuit ouvert pour {server} "
                    f"({state['failures']} echecs, {elapsed:.0f}s depuis le dernier)")
    return False


def _cb_success(server: str):
    """Appel réussi → réinitialise le circuit."""
    if server in _CB_STATE:
        old = _CB_STATE[server].get("failures", 0)
        if old >= _CB_THRESHOLD:
            logging.info(f"[MCP-CB] Circuit refermé pour {server} (apres {old} echecs)")
        _CB_STATE.pop(server, None)


def _cb_failure(server: str):
    """Appel échoué → incrémente le compteur, ouvre si seuil atteint."""
    now = time.time()
    state = _CB_STATE.setdefault(server, {"failures": 0, "last_failure": 0, "open_until": 0})
    state["failures"] += 1
    state["last_failure"] = now
    if state["failures"] >= _CB_THRESHOLD:
        state["open_until"] = now + _CB_COOLDOWN
        logging.warning(f"[MCP-CB] Circuit OUVERT pour {server} "
                        f"({state['failures']} echecs, cooldown {_CB_COOLDOWN}s)")


# ─── Protocole JSON-RPC MCP ──────────────────────────────────────────────────────

def _read_line(proc: subprocess.Popen, timeout: int = 10) -> Optional[str]:
    """Lit une ligne JSON-RPC sur stdout via readline() avec timeout."""
    q = Queue()
    def _reader():
        try:
            line = proc.stdout.readline()
            if line:
                q.put(line.decode("utf-8", errors="replace").strip())
            else:
                q.put(None)
        except Exception:
            logging.debug("[MCP] reader thread echec")
            q.put(None)
    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout=timeout)
    try:
        return q.get_nowait()
    except Empty:
        return None


def _send_json(proc: subprocess.Popen, msg: dict):
    """Envoie un message JSON-RPC sur stdin du subprocess."""
    data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
    proc.stdin.write(data)
    proc.stdin.flush()


def _rpc_call(proc: subprocess.Popen, method: str, params: dict = None,
              timeout: int = 10) -> Optional[dict]:
    """Appel JSON-RPC → retourne le contenu de 'result' ou None."""
    req_id = int(time.time() * 1_000_000)
    msg = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params or {},
    }
    _send_json(proc, msg)
    resp_line = _read_line(proc, timeout)
    if not resp_line:
        return None
    try:
        resp = json.loads(resp_line)
    except json.JSONDecodeError:
        logging.error(f"[MCP] JSON decode error in response from server: {resp_line[:200]}")
        return None
    if "error" in resp:
        logging.error(f"[MCP] RPC error: {resp['error']}")
        return None
    return resp.get("result")


def connect_server(name: str, config: dict) -> list:
    """Connecte un serveur MCP (stdio) et découvre ses outils.

    Args:
        name: Nom du serveur (ex: "notion")
        config: {"command": ..., "args": [...], "env": {...}}

    Returns:
        Liste d'outils au format OpenAI function-calling
    """
    if name in _connections:
        return _connections[name]["tools"]

    cmd = config["command"]
    args = config.get("args", [])
    extra_env = config.get("env", {})

    env = os.environ.copy()
    env.update(extra_env)

    logging.info(f"[MCP] Connexion à {name}: {cmd} {' '.join(args)}")
    try:
        proc = subprocess.Popen(
            [cmd] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=BASE_DIR,
        )
    except FileNotFoundError as e:
        logging.error(f"[MCP] {name}: commande introuvable: {e}")
        return []
    except Exception as e:
        logging.error(f"[MCP] {name}: echec lancement: {e}")
        return []

    # Initialize
    init_result = _rpc_call(proc, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "santana", "version": "1.0"},
    }, timeout=config.get("connect_timeout", 30))
    if not init_result:
        logging.error(f"[MCP] {name}: echec initialize")
        try:
            proc.terminate()
        except Exception:
            logging.debug("[MCP] connect_server proc terminate echec")
        return []

    # Notify initialized
    _send_json(proc, {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
        "params": {},
    })

    # List tools
    tools_result = _rpc_call(proc, "tools/list", timeout=config.get("connect_timeout", 30))
    if not tools_result:
        logging.error(f"[MCP] {name}: echec tools/list")
        try:
            proc.terminate()
        except Exception:
            logging.debug("[MCP] connect_server tools/list echec")
        return []

    mcp_tools = tools_result.get("tools", [])
    openai_tools = []
    for mcp_tool in mcp_tools:
        openai_tool = {
            "type": "function",
            "function": {
                "name": f"mcp_{name}_{mcp_tool['name']}",
                "description": mcp_tool.get("description", f"Outil MCP: {name}/{mcp_tool['name']}"),
                "parameters": mcp_tool.get("inputSchema", {"type": "object", "properties": {}}),
            }
        }
        openai_tools.append(openai_tool)

    _connections[name] = {
        "proc": proc,
        "tools": openai_tools,
        "config": config,
        "lock": threading.Lock(),
        "connected_at": time.time(),
    }

    logging.info(f"[MCP] {name}: {len(openai_tools)} outils decouverts")
    return openai_tools


# ── Health-check périodique MCP (Correctif 5) ──
_HC_REDISCOVER_INTERVAL = 300  # Re-découverte des serveurs MCP toutes les 5min (Correctif 17)

def _health_check_servers():
    """Vérifie l'état des connexions MCP toutes les 60s (lance dans un thread)."""
    _last_rediscover = 0
    while True:
        time.sleep(60)
        # Vérifier l'état des connexions existantes
        for name, conn in list(_connections.items()):
            proc = conn.get("proc")
            if proc and proc.poll() is not None:
                logging.warning(f"[MCP-HC] Serveur {name} mort, reconnexion...")
                try:
                    connect_server(name, conn["config"])
                except Exception as e:
                    logging.error(f"[MCP-HC] Reconnexion {name} échouée: {e}")
        # Re-découverte périodique des nouveaux serveurs (Correctif 17)
        now = time.time()
        if now - _last_rediscover > _HC_REDISCOVER_INTERVAL:
            _last_rediscover = now
            try:
                if os.path.exists(CONFIG_PATH):
                    with open(CONFIG_PATH, "r") as f:
                        config = json.load(f)
                    for srv_name, srv_config in config.items():
                        if srv_name.startswith("_"):
                            continue
                        if srv_name not in _connections and isinstance(srv_config, dict) and "command" in srv_config:
                            logging.info(f"[MCP-HC] Nouveau serveur détecté: {srv_name}, connexion...")
                            connect_server(srv_name, srv_config)
            except Exception as e:
                logging.error(f"[MCP-HC] Re-découverte échouée: {e}")


# Démarrer le health-check dans un thread daemon
_health_thread = threading.Thread(target=_health_check_servers, daemon=True)
_health_thread.start()


def call_tool(name: str, args: dict, timeout: int = 120) -> str:
    """Appelle un outil MCP par son nom complet (mcp_server_tool).

    Args:
        name: Nom complet de l'outil (ex: "mcp_notion_search_pages")
        args: Arguments de l'outil

    Returns:
        Résultat textuel
    """
    mcp_name = name[len("mcp_"):]  # enlever préfixe "mcp_"
    # Circuit breaker : éviter les appels à un serveur en panne
    for srv_name in _connections:
        if name.startswith(f"mcp_{srv_name}_"):
            if not _cb_check(srv_name):
                return f"Erreur: serveur MCP {srv_name} indisponible (circuit ouvert, attendez quelques instants)"
            break

    # Séparer server_name du tool_name
    # Format: mcp_{server}_{tool} → server_name peut contenir des underscores
    # On cherche le serveur connu
    found_server = None
    found_tool_name = None

    for srv_name, conn in _connections.items():
        prefix = f"mcp_{srv_name}_"
        if name.startswith(prefix):
            found_server = srv_name
            found_tool_name = name[len(prefix):]
            break

    if not found_server:
        return f"Erreur: serveur MCP inconnu pour {name}"

    conn = _connections.get(found_server)
    if not conn:
        _cb_failure(found_server)
        return f"Erreur: serveur MCP {found_server} non connecte"

    with conn["lock"]:
        proc = conn["proc"]
        if proc.poll() is not None:
            # Reconnexion
            logging.info(f"[MCP] Reconnexion à {found_server}...")
            new_tools = connect_server(found_server, conn["config"])
            if not new_tools:
                _cb_failure(found_server)
                return f"Erreur: serveur MCP {found_server} plus disponible"
            proc = _connections[found_server]["proc"]

        try:
            result = _rpc_call(proc, "tools/call", {
                "name": found_tool_name,
                "arguments": args,
            }, timeout=timeout)
        except Exception as e:
            _cb_failure(found_server)
            return f"Erreur appel MCP {found_server}/{found_tool_name}: {str(e)}"

    if result is None:
        _cb_failure(found_server)
        return f"Erreur: {found_server}/{found_tool_name} n'a pas repondu"

    # Succès → refermer le circuit
    _cb_success(found_server)

    # MCP peut retourner du contenu avec des types (text, resource, etc.)
    content = result.get("content", [])
    if isinstance(content, list):
        texts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                texts.append(c.get("text", ""))
        return "\n".join(texts) if texts else str(content)
    return str(content)


def discover_all_servers() -> list:
    """Lit la config MCP et connecte tous les serveurs.

    Returns:
        Liste combinée d'outils OpenAI function-calling
    """
    if not os.path.exists(CONFIG_PATH):
        return []

    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"[MCP] Erreur lecture config: {e}")
        return []

    all_tools = []
    for name, srv_config in config.items():
        if name.startswith("_"):
            continue
        if not isinstance(srv_config, dict) or "command" not in srv_config:
            continue
        tools = connect_server(name, srv_config)
        all_tools.extend(tools)

    return all_tools


def is_mcp_tool(name: str) -> bool:
    """Vérifie si un nom d'outil commence par mcp_."""
    return name.startswith("mcp_")


def get_connection_status() -> dict:
    """Retourne l'état des connexions MCP."""
    status = {}
    for name, conn in _connections.items():
        proc = conn["proc"]
        alive = proc.poll() is None
        status[name] = {
            "connected": alive,
            "tools": len(conn["tools"]),
            "uptime": int(time.time() - conn["connected_at"]),
        }
    return status
