"""Boucle de raisonnement de Santana : orchestre les appels LLM + outils."""

import os
import json
import logging
import asyncio
import time
import re
from datetime import datetime

from deepseek_client import complete, complete_stream
from tools.tools import execute_tool, TOOLS
from tools.cost_governor import check_cost_governor, estimate_cost_from_messages, record_usage
from memory.memory import get_recent_memory
from core.utils import strip_dsml, get_base_dir
from agent.orchestrator import build_system_prompt, classify_message
from agent.context import push_exchange, maybe_auto_summarize, init_session as init_context_session
from core.disambiguate import disambiguate
from core.json_logger import json_log
from core.cache import cache_get, cache_set, cache_purge_all
from core.provider_manager import get_active_provider, get_provider_config
import threading
from agent.evaluator import evaluate_response, log_evaluation
from core.loop_evolution import pulse, pulse_error, get_pulse_summary

# ─── Garde-fou : validation des appels outils avant exécution ──────────
_ALLOWED_TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)
# Outils dont les paramètres contiennent naturellement du code/commandes
# (ne pas vérifier les métacharactères shell pour ces outils)
_SKIP_METACHAR_CHECK = {"vm_exec", "vm_exec_script", "run_code", "code_exec"}
_SHELL_METACHARS = frozenset("$`;&|><")
def _validate_tool_call(tname: str, targs: dict) -> str | None:
    """Valide un appel outil avant exécution.
    Retourne None si OK, un message d'erreur si refusé."""
    if tname not in _ALLOWED_TOOL_NAMES:
        return f"Outil inconnu: {tname}"
    if tname not in _SKIP_METACHAR_CHECK:
        for k, v in targs.items():
            sv = str(v)
            if any(c in sv for c in _SHELL_METACHARS):
                return f"Paramètre '{k}' contient des métacaractères shell interdits"
    return None
_ITERATION_TIMEOUT = 60   # Temps max par itération (outil bloquant = kill propre)
_SESSION_TIMEOUT = 300    # Temps max total pour une session complète (5 min)
# Quarantaine d'outils : après 3 échecs consécutifs, l'outil est gelé 1h
_QUARANTINE_SECONDS = 3600  # 1 heure
_quarantined_until: dict[str, float] = {}  # tool_name -> expiry timestamp


def reset_state():
    """Réinitialise l'état global de react_loop (quarantaine + cache prompt)."""
    _quarantined_until.clear()
    # Cache prompt supprimé (v1.1) — plus de _CACHED_PROMPT global
    cache_purge_all()


# Outils pouvant prendre du temps (heartbeat assistant)
_EXPENSIVE_TOOLS = {
    "web_search", "web_navigate", "web_screenshot", "social_search",
    "run_code", "vm_exec", "vm_exec_script",
}
_TOOL_PROGRESS = {
    # 🔍  Recherche web / social / navigation
    "web_search": "🔍 Recherche web en cours...",
    "web_navigate": "🔍 Navigation sur le web...",
    "web_screenshot": "🔍 Capture d'écran...",
    "social_search": "🔍 Recherche sociale...",
    "youtube_info": "🎬 Récupération infos vidéo...",
    # 🧠  Mémoire, skills, auto-analyse
    "memory_query": "🧠 Consultation mémoire...",
    "atlas": "🧠 Sauvegarde en mémoire...",
    "self_inspect": "🧠 Auto-analyse...",
    "search_skills": "🧠 Recherche de skills...",
    "delegate_task": "🧠 Délégation à un sous-agent...",
    # ⚡  Code / commandes / scripts
    "run_code": "⚡ Exécution de code...",
    "vm_exec": "⚡ Commande shell...",
    "vm_exec_script": "⚡ Script en cours...",
    # 💾  Sauvegarde / données
    "save_skill": "💾 Sauvegarde skill...",
    "fs_write": "💾 Écriture fichier...",
    "workspace_state": "💾 État workspace...",
    # 🌐  GitHub / outils externes (MCP)
    "github_": "🌐 GitHub...",
    "mcp_": "🌐 Outil externe...",
    # 🖥️  Terminal / preview
    "tmux_session": "🖥️ Session terminal...",
    "render_preview": "🖥️ Aperçu...",
    "get_datetime": "🖥️ Vérification date...",
}

# ─── Validation des résultats d'outils ───────────────────────────────────
_MAX_TOOL_RESULT_CHARS = 10000
_HTML_ERROR_RE = re.compile(
    r'<(html|!DOCTYPE|title>Error|title>404|title>403|title>50[0-9])',
    re.IGNORECASE
)


def _validate_tool_result(name: str, result: str) -> str:
    """Valide et nettoie un résultat d'outil avant injection dans le contexte LLM.

    Vérifie : contenu non vide, pas de page d'erreur HTML, taille limite.
    Si invalide, retourne un message d'erreur explicite au lieu du résultat brut.
    """
    if not result or result.strip() in ("null", "{}", "[]"):
        logging.warning(f"[VALIDATE] {name}: résultat vide")
        return json.dumps({"error": f"L'outil {name} n'a retourné aucun résultat."})

    if _HTML_ERROR_RE.search(result[:500]):
        logging.warning(f"[VALIDATE] {name}: page d'erreur HTML détectée")
        return json.dumps({"error": f"L'outil {name} a retourné une page d'erreur."})

    if len(result) > _MAX_TOOL_RESULT_CHARS:
        logging.info(f"[VALIDATE] {name}: tronqué de {len(result)} à {_MAX_TOOL_RESULT_CHARS} chars")
        return result[:_MAX_TOOL_RESULT_CHARS] + "\n\n[... résultat tronqué — trop long]"

    return result


def _schedule_background_eval(response_text: str, user_msg: str):
    """Lance l'auto-évaluation en tâche de fond (fire-and-forget)."""
    if not response_text or not user_msg:
        return
    try:
        t = threading.Thread(
            target=lambda: _run_eval(response_text, user_msg),
            daemon=True
        )
        t.start()
    except Exception as _ee:
        logging.error(f"[EVAL-BG] Schedule error: {_ee}")


def _run_eval(resp: str, msg: str):
    """Exécute l'évaluation et logue le score."""
    try:
        er = evaluate_response(resp, msg)
        log_evaluation(er)
        logging.info(f"[EVAL-BG] Score: {er.score:.2f}")
        if er.score < 0.5:
            logging.warning(f"[EVAL-BG] Score critique ({er.score:.2f}) — correction nécessaire")
    except Exception as _ee:
        logging.error(f"[EVAL-BG] Error: {_ee}")


# ─── Filtrage des outils par type de message (optimisation performance) ──
# Chaque outil inutile que le LLM voit = temps perdu en décision + appels
# inutiles (ex: github_list_files sur une question d'actualité).
# On ne présente au LLM que les outils pertinents pour le type de message.
_TOOL_CATEGORIES = {
    # Recherche & informations publiques
    "search": {"web_search", "web_navigate", "web_screenshot",
               "get_datetime", "youtube_info", "read_pdf"},
    # Réseaux sociaux (recherche par mots-clés)
    "social_search": {"social_search", "social_news", "social_browser",
                      "twitter_search", "reddit_search",
                      "instagram_search", "tiktok_search"},
    # Réseaux sociaux (lookup par compte spécifique)
    "social_lookup": {"twitter_lookup", "reddit_lookup",
                      "instagram_lookup", "tiktok_lookup"},
    # Mémoire personnelle & skills
    "memory": {"memory_query", "atlas", "self_inspect",
               "search_skills", "skill_view", "skill_list", "skill_manage"},
    # Code / exécution
    "code": {"run_code", "code_modify", "code_list_sources", "restart_self",
             "workspace_state", "tmux_session"},
    # GitHub
    "github": {"github_list_repos", "github_list_files",
               "github_read", "github_write"},
    # Meta — édition, skills, délégation, preview
    "meta": {"save_skill", "render_preview", "fs_write", "fs_read",
             "delegate_task", "cost_governor"},
    # Admin — outils dynamiques créés par le LLM (rares)
    "admin": {"tool_create", "install_dependencies",
              "list_user_tools", "delete_user_tool"},
}
# Catégories autorisées par type de message
_TOOLS_BY_TYPE = {
    # Questions factuelles → recherche + mémoire seulement
    "FACTUEL":   ["search", "memory"],
    # Synthèse → recherche + mémoire
    "SYNTHESE":  ["search", "memory"],
    # Analyse approfondie → recherche + social + code + meta
    "DEEP":      ["search", "social_search", "social_lookup",
                  "memory", "code", "meta"],
    # Personnel → tout (y compris GitHub, MCP)
    "PERSONNEL": ["search", "social_search", "social_lookup",
                  "memory", "code", "github", "meta"],
    # Salutations → pas d'outils du tout
    "SOCIAL":    [],
}

# Cache prompt supprimé (v1.1) : build_system_prompt reconstruit
# le prompt complet à chaque message. Le cache partiel du socle
# statique est dans orchestrator.py::get_prompt_base().


def _filter_tools(msg_type: str, full_tools: list) -> list:
    """Filtre les outils selon le type de message.

    FACTUEL/SYNTHESE : que recherche + mémoire (pas de code, GitHub, orchestre)
    DEEP : recherche + mémoire + code + meta (pas GitHub, pas orchestre)
    PERSONNEL : tous sauf orchestration
    """
    cats = _TOOLS_BY_TYPE.get(msg_type)
    if cats is None:
        return full_tools  # type inconnu → tous les outils (sécurité)
    # Construire l'ensemble des noms autorisés
    allowed = set()
    for cat in cats:
        allowed |= _TOOL_CATEGORIES.get(cat, set())
    return [t for t in full_tools if t["function"]["name"] in allowed]


def _get_tool_progress(tname: str, targs: dict) -> str:
    """Génère un message de progression lisible pour l'utilisateur."""
    msg = _TOOL_PROGRESS.get(tname) or _TOOL_PROGRESS.get("github_", "⏳ Travail en cours...")
    # Vérifier les préfixes
    if msg == "⏳ Travail en cours...":
        for prefix, pmsg in [("github_", "🐙 GitHub..."), ("mcp_", "🔌 Outil externe...")]:
            if tname.startswith(prefix.rstrip("_")):
                msg = pmsg
                break
    # Ajouter le contexte si présent
    query = targs.get("query", targs.get("command", targs.get("url", "")))
    if query:
        q = str(query)[:80]
        msg += f" `{q}`"
    return msg


def _run_tool_with_heartbeat(tname: str, targs: dict,
                              stream_callback=None) -> str:
    """Execute un outil avec heartbeat : envoie une progression __PROGRESS__
    initiale via _get_tool_progress(), puis rafraîchit toutes les ~6s si
    l'outil est lent. TelegramStream affiche ce suffixe sans le mélanger au
    buffer de contenu réel (voir tools/telegram_stream.py::callback)."""
    result = {"val": "", "done": False}

    def _run():
        try:
            result["val"] = execute_tool(tname, targs)
        except Exception as e:
            result["val"] = json.dumps({"error": str(e)})
        result["done"] = True

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    if stream_callback:
        progress = _get_tool_progress(tname, targs)
        stream_callback(f"__PROGRESS__{progress}")

    heartbeat_count = 0
    while not result["done"]:
        time.sleep(2.0)
        heartbeat_count += 1
        if stream_callback and heartbeat_count >= 3:  # Rafraîchir toutes les 6s
            progress = _get_tool_progress(tname, targs)
            dots = "." * (heartbeat_count % 4)
            stream_callback(f"__PROGRESS__{progress}{dots}")
            heartbeat_count = 0

    t.join(timeout=1)
    return result["val"]


BASE_DIR = get_base_dir()
SOUL_DIR = os.path.join(BASE_DIR, "soul")
DB_PATH = os.path.join(BASE_DIR, "memory.db")

# ─── COUCHE BLEUE — Buffer de session (délégué à agent/context.py) ─────
# Les fonctions suivantes sont maintenant dans agent/context.py :
#   init_session(), push_exchange(), get_session_buffer(),
#   get_session_summary(), maybe_auto_summarize(), get_context()
# ────────────────────────────────────────────────────────────────────────

# L'initialisation du contexte se fait au premier appel de react_loop(),
# pas à l'import, pour éviter les conflits de DB avec les tests.


async def _stream_and_collect(messages, model, max_tokens, tools, tool_choice,
                              stream_callback=None,
                              provider='deepseek'):
    """Appel LLM streaming dans un thread. Retourne {message, finish_reason}.

    Streame CHAQUE chunk en temps réel via stream_callback(chunk) dès qu'il arrive
    du LLM. Anti-leak par chunk (filtre les leaks XML au vol).

    Si leak XML détecté → le streaming s'arrête silencieusement, le contenu est
    nettoyé par strip_dsml() avant retour (le retry dans react_loop gère le reste).
    """
    def _run():
        content = ""
        reasoning = ""
        tool_calls = None
        finish_reason = "stop"
        stream_active = True
        chunk_usage = {}
        for chunk in complete_stream(messages, model=model,
                                      max_tokens=max_tokens,
                                      tools=tools, tool_choice=tool_choice,
                                      provider=provider):
            if chunk['type'] == 'content':
                c = chunk['content']
                content += c
                # Streaming en TEMPS RÉEL — chaque chunk passe immédiatement
                # à stream_callback(), pas de buffer puis replay.
                # Anti-leak chunk par chunk : dès qu'un leak XML est détecté,
                # on arrête de streamer (le contenu leaké est nettoyé par
                # strip_dsml() avant retour, et le retry dans react_loop gère).
                if stream_callback and stream_active:
                    if ('<invoke' in c or '<tool_calls>' in c
                            or '<tool_call>' in c
                            or '[Calling tool:' in c):
                        stream_active = False
                    else:
                        stream_callback(c)
            elif chunk['type'] == 'reasoning':
                reasoning += chunk['content']
            elif chunk['type'] == 'complete':
                if chunk.get('content'):
                    content = chunk['content']
                finish_reason = chunk.get('finish_reason', 'stop')
                tool_calls = chunk.get('tool_calls')
                reasoning = chunk.get('reasoning_content', reasoning)
                chunk_usage = chunk.get('usage', {})
            elif chunk['type'] == 'error':
                raise RuntimeError(f"Stream error: {chunk['content']}")
        content_clean = strip_dsml(content) if content else ""
        msg = {"role": "assistant", "content": content_clean or content, "tool_calls": tool_calls}
        if reasoning:
            msg["reasoning_content"] = reasoning
        return {
            "message": msg,
            "finish_reason": finish_reason,
            "usage": chunk_usage if isinstance(chunk_usage, dict) else {}
        }
    return await asyncio.to_thread(_run)


async def react_loop(user_message: str,
                     stream_callback=None, _stats: dict = None) -> str:
    """Boucle principale. stream_callback(content: str) appelé pour chaque token.
    
    Args:
        user_message: Le message de l'utilisateur.
        stream_callback: Fonction appelée pour chaque token/chunk pendant le streaming.
        _stats: Dict mutable optionnel pour remonter des métriques (tool_count, provider, token_count).
    """
    # Initialiser le contexte au premier appel (pas à l'import pour les tests)

    # ─── Garde-fou : forcer user_message en str ──────────────────────
    # Corrige le bug 'list object has no attribute lower' quand un handler
    # passe accidentellement une liste au lieu d'une string.
    if not isinstance(user_message, str):
        logging.warning(f"[REACT_LOOP] user_message n'est pas une str mais {type(user_message).__name__} — conversion forcée")
        user_message = str(user_message)

    init_context_session()
    # Enregistrer dans le buffer de session (Couche Bleue)
    push_exchange("user", user_message)
    _start_time = time.time()  # Pour le timeout global de session
    _tools_called: set = set()  # Garde-fou anti-bluff : outils appelés dans ce tour

    # Désambiguïsation : résout les références implicites (pronoms, "ça", "c'est")
    # avant classification et construction du prompt. Le message brut reste dans
    # le buffer de session ; seule la version enrichie sert au traitement courant.
    try:
        user_message = disambiguate(user_message)
    except Exception as _de:
        logging.error(f"[DISAMBIGUATE] error: {_de}")

    # Type de message (nécessaire AVANT build_system_prompt pour le cache)
    msg_type = classify_message(user_message)

    # Prompt système : build_system_prompt gère elle-même son cache
    # (get_prompt_base() dans orchestrator.py — socle statique uniquement,
    # pas la mémoire dynamique). Un cache supplémentaire ici gèlerait
    # la mémoire 5 minutes (cf. audit Fable 5).
    SYSTEM = build_system_prompt(user_message=user_message, msg_type=msg_type)
    messages = [{"role": "system", "content": SYSTEM}]

    # Contexte récent : uniquement si build_system_prompt() n'a pas déjà
    # injecté le buffer de session (Couche Bleue). Avant, les deux
    # coexistaient systématiquement et dupliquaient ~1500-2500 tokens de
    # contexte quasi identique, répétés à CHAQUE aller-retour LLM du tour
    # (3-5x). orchestrator.py::build_system_prompt() injecte déjà
    # session_buffer/session_summary pour msg_type hors SOCIAL/FACTUEL et
    # hors mode dégradé — get_recent_memory ne sert alors plus que de
    # fallback pour les autres cas (ou si le buffer est encore vide).
    _degraded = os.path.exists(os.path.join(BASE_DIR, '.crash_flag'))
    _session_covered = msg_type not in ("SOCIAL", "FACTUEL") and not _degraded
    if _session_covered:
        try:
            from agent.context import get_session_buffer
            _session_covered = bool(get_session_buffer())
        except Exception:
            _session_covered = False
    if not _session_covered:
        recent = get_recent_memory(20)
        if recent:
            ctx = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in recent)
            messages.append({"role": "system", "content": "Contexte récent:\n" + ctx})

    # Déterminer la longueur pour le routage
    text_len = len(user_message.strip())

    # Signale le type de message au front-end Telegram (voir
    # tools/telegram_stream.py::TelegramStream.callback) avant le premier
    # appel LLM. Convention de préfixe identique à "__PROGRESS__".
    if stream_callback:
        stream_callback("__MSGTYPE__" + msg_type)

    # Provider dynamique via le manager (deepseek ou groq selon l'état)
    provider = get_active_provider()
    # Aucun bridage artificiel : Santana s'arrête sur finish_reason='stop'
    # ou _SESSION_TIMEOUT (garde-fou technique 300s).
    max_iter = 50  # garde-fou technique (jamais atteint en usage normal)
    use_tools = True
    p_label = get_provider_config(provider)["label"]
    logging.info(f'[ROUTER] Message {msg_type} → {p_label}, outils libres')

    messages.append({"role": "user", "content": user_message})

    iteration = 0
    last_content = ""
    _last_tokens = 0
    _last_tool_error = [0, ""]   # [count, last_tool_name] — détection boucle outil
    use_stream = stream_callback is not None
    is_self_query = any(kw in user_message.lower()
                        for kw in ["qui es-tu", "décris-toi", "décrivez-vous",
                                   "parle de toi", "ton code", "ton architecture",
                                   "tes outils", "auto-description"])

    while iteration < max_iter:
        # Heartbeat + timeout check
        _elapsed = time.time() - _start_time
        if _elapsed > _SESSION_TIMEOUT:
            logging.warning(f"[TIMEOUT] Session dépassée ({_elapsed:.0f}s > {_SESSION_TIMEOUT}s) — arrêt après {iteration} itérations")
            break
        if iteration > 0 and _elapsed > 15 * (iteration // 15):
            logging.info("[HEARTBEAT] Itération %d, écoulé %.0fs", iteration, _elapsed)
        try:
            actual_provider = provider
            actual_tools = _filter_tools(msg_type, TOOLS) if use_tools else None

            # max_tokens dynamique selon le provider actif
            # DeepSeek: 32K, Groq: 8K (limite API Groq)
            mt = get_provider_config(actual_provider)["max_tokens"]

            # ── Coût : tracking passif seulement (ne bloque jamais) ────────
            _cost_est = estimate_cost_from_messages(messages, mt)
            _gov = check_cost_governor(_cost_est)
            if _gov == "ALERT":
                logging.info("[COST] ALERT — 80%% du budget atteint, pas de bridage")
            elif _gov == "THROTTLE":
                logging.warning("[COST] THROTTLE — 95%% du budget atteint, outils coûteux coupés")
                if actual_tools:
                    actual_tools = [t for t in actual_tools
                                    if t["function"]["name"] not in _EXPENSIVE_TOOLS]
                max_iter = min(max_iter, iteration + 2)
            elif _gov == "STOP":
                logging.error("[COST] STOP — budget épuisé, appel LLM refusé")
                last_content = (
                    "Budget de session épuisé pour l'instant. Utilise /reset pour "
                    "réinitialiser le compteur, ou attends le prochain cycle."
                )
                break

            if actual_tools:
                tc = "auto"   # Outils toujours disponibles
            else:
                tc = "none"

            try:
                if use_stream:
                    choice = await asyncio.wait_for(
                        _stream_and_collect(
                            messages, model=None, max_tokens=mt,
                            tools=actual_tools, tool_choice=tc,
                            stream_callback=stream_callback,
                            provider=actual_provider
                        ),
                        timeout=_ITERATION_TIMEOUT
                    )
                else:
                    choice = await asyncio.wait_for(
                        asyncio.to_thread(
                            complete, messages, model=None, max_tokens=mt,
                            tools=actual_tools, tool_choice=tc,
                            provider=actual_provider
                        ),
                        timeout=_ITERATION_TIMEOUT
                    )
            except asyncio.TimeoutError:
                logging.warning(f"[TIMEOUT] Itération {iteration} bloquée > {_ITERATION_TIMEOUT}s — forçage sans outils")
                if use_stream:
                    choice = await asyncio.wait_for(
                        _stream_and_collect(
                            messages, model=None, max_tokens=mt,
                            tools=None, tool_choice="none",
                            stream_callback=stream_callback,
                            provider=actual_provider
                        ),
                        timeout=30
                    )
                else:
                    choice = await asyncio.wait_for(
                        asyncio.to_thread(
                            complete, messages, model=None, max_tokens=mt,
                            tools=None, tool_choice="none",
                            provider=actual_provider
                        ),
                        timeout=30
                    )

            msg = choice["message"]
            finish_reason = choice["finish_reason"]
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls")

            # Enregistrer les tokens RÉELS retournés par l'API
            _usage = choice.get('usage', {})
            if _usage.get('prompt_tokens'):
                try:
                    record_usage(
                        prompt_tokens=_usage.get('prompt_tokens', 0),
                        completion_tokens=_usage.get('completion_tokens', 0),
                        cached_tokens=_usage.get('prompt_cache_hit_tokens', 0),
                        provider_name=actual_provider
                    )
                    _last_tokens = _usage.get('prompt_tokens', 0) + _usage.get('completion_tokens', 0)
                except Exception as _ue:
                    logging.error(f"[COST] record_usage error: {_ue}")

            if content:
                last_content = content

            # Réponse finale sans outils
            if finish_reason in ("stop", "length") and not tool_calls:
                # ── Vérifier les leaks XML ──
                if content and ("<tool_calls>" in content or "<invoke name=" in content):
                    # DeepSeek a leaké des tool_calls en XML — on les PARSE et exécute
                    logging.warning("[DSML] Tool call leak détecté en XML, parsing et exécution directe")
                    xml_tools = re.findall(r'<invoke name="([^"]+)"(.*?)</invoke>', content, re.DOTALL)
                    executed_any = False
                    for tname, tbody in xml_tools:
                        tname = tname.strip()
                        params = re.findall(r'<parameter name="([^"]+)"[^>]*>(.*?)</parameter>', tbody, re.DOTALL)
                        targs = {p[0]: p[1].strip() for p in params}
                        try:
                            tresult = execute_tool(tname, targs)
                            _tools_called.add(tname)
                            logging.info(f"[DSML-XML] {tname}({targs}) -> {str(tresult)[:200]}")
                            messages.append({
                                "role": "tool", "type": "tool",
                                "tool_call_id": f"xml_{iteration}_{tname}",
                                "content": str(tresult)
                            })
                            executed_any = True
                        except Exception as _xe:
                            logging.error(f"[DSML-XML] Erreur exécution {tname}: {_xe}")
                    if executed_any:
                        iteration += 1
                        continue
                    # Fallback : si aucun outil XML n'a été parsé, retry avec instruction
                    logging.warning("[DSML] Aucun outil XML parsé, retry avec instruction")
                    last_content = strip_dsml(content) or last_content
                    iteration += 1
                    if iteration < max_iter:
                        messages.append({"role": "user", "content": "Utilise les appels de fonction pour chercher sur le web."})
                        continue
                    return _finalize(last_content if last_content else "Je n'ai pas pu effectuer la recherche.", user_message, msg_type=msg_type, tools_used=_tools_called)

                # ── Contenu propre (pas de leak) ──
                cleaned = strip_dsml(content) if content else ""

                # ── Cas finish_reason="length" : livrer ce qu'on a, sans continuation ──
                # Raison : la boucle de continuation relançait DeepSeek pour compléter
                # la réponse, mais le second appel API timeoutait → Santana gelé 8+ min.
                # Maintenant : on livre le contenu partiel immédiatement. L'utilisateur
                # peut toujours dire "continue" si la réponse est vraiment tronquée.
                if finish_reason == "length" and cleaned:
                    logging.warning(f"[LENGTH] Limite atteinte — {len(cleaned)} chars, livraison immédiate (pas de continuation)")

                # ── Livrer le contenu (stop ou length, les deux sont traités pareil) ──

                # ── AUTO-ÉVALUATION (diagnostic seulement, pas de correction, tâche de fond) ──
                if not is_self_query:
                    _schedule_background_eval(cleaned, user_message)
                return _finalize(cleaned if cleaned else "Pas de réponse.", user_message, msg_type=msg_type, tools_used=_tools_called)

            # Pas de tools même si finish_reason inattendu
            if not tool_calls:
                cleaned = strip_dsml(content) if content else ""
                if not is_self_query:
                    _schedule_background_eval(cleaned, user_message)
                return _finalize(cleaned if cleaned else "Je n'ai pas compris.", user_message, msg_type=msg_type, tools_used=_tools_called)

            # Ajouter la réponse avec tool_calls — nettoyer le XML leaké de l'historique
            clean_content = msg.get("content", "") or ""
            if "<invoke name=" in clean_content or "<tool_calls>" in clean_content:
                clean_content = re.sub(r'<invoke name="[^"]+".*?</invoke>', '',
                                         clean_content, flags=re.DOTALL).strip()
                clean_content = re.sub(r'<tool_calls>.*?</tool_calls>', '',
                                         clean_content, flags=re.DOTALL).strip()
            msg["content"] = clean_content
            messages.append(msg)

            # Exécuter les outils (parallélisation intelligente)
            _PARALLEL_TOOLS = {"web_search", "social_search", "memory_query", "atlas"}
            _tool_batch = []  # [(tname, targs, tc)]
            for tc in tool_calls:
                tname = tc["function"]["name"]
                try:
                    targs = json.loads(tc["function"]["arguments"])
                except Exception as e:
                    logging.error("[TOOL] Invalid JSON in tool arguments: %s", e)
                    targs = {}
                _validation_error = _validate_tool_call(tname, targs)
                if _validation_error:
                    logging.warning(f"[GUARDRAIL] {_validation_error}")
                    _tools_called.add(tname)
                    messages.append({
                        "role": "tool", "type": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps({"error": _validation_error})
                    })
                    continue
                # Vérification quarantaine : outil gelé après 3 échecs consécutifs
                _now_q = time.time()
                if tname in _quarantined_until and _now_q < _quarantined_until[tname]:
                    _remaining = int(_quarantined_until[tname] - _now_q)
                    logging.warning(f"[QUARANTINE] {tname} en quarantaine ({_remaining}s restant) — bloqué")
                    _tools_called.add(tname)
                    messages.append({
                        "role": "tool", "type": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps({
                            "error": f"Outil {tname} temporairement indisponible (quarantaine {_remaining}s)"
                        })
                    })
                    continue
                _tool_batch.append((tname, targs, tc))

            # Exécution groupée : parallèle (search/memory) puis séquentiel (reste)
            _tool_results = []  # [(tname, tc, result)]
            _batch_idx = 0
            while _batch_idx < len(_tool_batch):
                tname, targs, tc = _tool_batch[_batch_idx]
                # Tous les outils passent par le cache d'abord (P1.7)
                _cached = cache_get(tname, targs)
                if _cached is not None:
                    _tool_results.append((tname, tc, _cached))
                    _batch_idx += 1
                    continue
                if tname in _PARALLEL_TOOLS:
                    # Rassembler tout le groupe parallèle
                    _group = []
                    while _batch_idx < len(_tool_batch) and _tool_batch[_batch_idx][0] in _PARALLEL_TOOLS:
                        # Vérifier le cache pour chaque outil du groupe avant exécution
                        _gt, _ga, _gtc = _tool_batch[_batch_idx]
                        _gcached = cache_get(_gt, _ga)
                        if _gcached is not None:
                            _tool_results.append((_gt, _gtc, _gcached))
                            _batch_idx += 1
                            continue
                        _group.append(_tool_batch[_batch_idx])
                        _batch_idx += 1
                    _results = await asyncio.gather(*[
                        asyncio.to_thread(execute_tool, gt, ga)
                        for gt, ga, _ in _group
                    ])
                    for (gt, ga, gtc), gr in zip(_group, _results):
                        cache_set(gt, ga, gr)  # Cache aussi les outils parallèles (P1.7)
                        _tool_results.append((gt, gtc, gr))
                else:
                    # Cache lookup (Phase 2)
                    _cached = cache_get(tname, targs)
                    if _cached is not None:
                        _tool_results.append((tname, tc, _cached))
                        _batch_idx += 1
                        continue
                    # Outil séquentiel (code, vm, etc.)
                    if tname in _EXPENSIVE_TOOLS:
                        tresult = _run_tool_with_heartbeat(tname, targs, stream_callback)
                    else:
                        tresult = execute_tool(tname, targs)
                    cache_set(tname, targs, tresult)
                    _tool_results.append((tname, tc, tresult))
                    _batch_idx += 1

            # Post-traitement : détection boucle + validation + log + messages
            for tname, tc, tresult in _tool_results:
                # JSON log structuré (Phase 2)
                json_log("tool_call", tool=tname, result_len=len(tresult),
                         has_error="error" in tresult[:50].lower())
                # Validation du résultat (contenu vide, HTML error, taille limite)
                tresult = _validate_tool_result(tname, tresult)
                _tools_called.add(tname)
                # Détection boucle outil : si le même outil échoue 3× de suite → quarantaine 1h
                if "error" in tresult[:50].lower() or "exception" in tresult[:50].lower():
                    pulse_error(tname, tresult[:200])
                    if tname == _last_tool_error[1]:
                        _last_tool_error[0] += 1
                    else:
                        _last_tool_error = [1, tname]
                    if _last_tool_error[0] >= 3:
                        _quarantined_until[tname] = time.time() + _QUARANTINE_SECONDS
                        logging.warning(f"[QUARANTINE] {tname} en quarantaine pour {_QUARANTINE_SECONDS}s après {_last_tool_error[0]} échecs consécutifs")
                        messages.append({
                            "role": "system",
                            "content": f"L'outil {tname} est en quarantaine pour 1h après {_last_tool_error[0]} échecs. Utilise d'autres outils ou réponds directement."
                        })
                        _last_tool_error = [0, ""]  # Reset complet
                else:
                    _last_tool_error = [0, ""]  # Réussi → reset compteur
                logging.info(f"[TOOL] {tname}(...) -> {tresult[:200]}")
                messages.append({
                    "role": "tool",
                    "type": "tool",
                    "tool_call_id": tc["id"],
                    "content": tresult
                })

            iteration += 1

        except Exception as e:
            logging.error(f"react_loop error: {e}")
            return _finalize(f"Erreur technique: {str(e)}", user_message, msg_type=msg_type, tools_used=_tools_called)

    # ── POINT DE SORTIE UNIQUE ──────────────────────────────────────────
    # Quelle que soit la provenance (happy path, erreur, timeout),
    # la réponse passe par _finalize pour garantir que la mémoire
    # (push_exchange, maybe_auto_summarize, atlas) est toujours mise à jour.

    # ── REMONTER LES MÉTRIQUES (Phase 4) ────────────────────────────
    if _stats is not None:
        _stats['tool_count'] = len(_tools_called)
        _stats['provider'] = get_active_provider()
        _stats['token_count'] = _last_tokens  # tokens réels du dernier appel LLM

    # Livrer le dernier contenu généré (ou un message utile si vide)
    if last_content:
        response = strip_dsml(last_content)
    else:
        # max_iter épuisé sans contenu → message constructif, pas de frustration
        logging.warning("[LOOP] max_iter épuisé sans contenu — réponse partielle")
        response = "Je n'ai pas pu trouver l'information avec les outils disponibles. Peux-tu préciser ta question ou me donner une indication sur où chercher ?"
    return _finalize(response, user_message, msg_type=msg_type, tools_used=_tools_called)


def _finalize(response: str, user_message: str = "", msg_type: str = "", tools_used: set = None) -> str:
    """Finalise une réponse : enregistre dans le buffer, résumé automatique, Atlas.

    Garantit que TOUTE réponse de Santana (happy path, erreur, timeout, etc.)
    passe par les trois opérations de fin.

    Appelée par react_loop() — unique point de sortie normalisé.
    """
    # ─── Garde-fou anti-bluff : affirmation non vérifiée ─────────────────
    # Détecteur CONSERVATEUR : signale uniquement les messages factuels sans outil.
    # Objectif : sous-signaler plutôt que sur-bloquer.
    if msg_type == "FACTUEL" and (tools_used is None or len(tools_used) == 0):
        logging.warning(
            "[ANTI-BLUFF] Réponse FACTUELLE sans outil appelé — "
            "affirmation possiblement non vérifiée. "
            f"message={user_message[:80]!r}"
        )
        try:
            from agent.tracabilite import log_action as _log_action
            _log_action(
                "affirmation_non_verifiee",
                f"FACTUEL sans outil: {user_message[:120]!r}",
                {"response_preview": response[:120]},
            )
        except Exception as _te:
            logging.debug(f"[ANTI-BLUFF] tracabilite indisponible: {_te}")

    # Buffer de session (Couche Bleue)
    try:
        push_exchange("assistant", response)
    except Exception as _pe:
        logging.error(f"[FINALIZE] push_exchange error: {_pe}")

    # Pulse : metriques d'auto-evolution (Loop Engineering)
    try:
        pulse(response, user_message, tools_used)
    except Exception as _le:
        logging.error(f"[FINALIZE] pulse error: {_le}")

    # Détection de patterns (F5) : enregistrement automatique de l'interaction
    if user_message:
        try:
            from agent.patterns import record_interaction
            record_interaction(
                timestamp=datetime.now().isoformat(),
                sujet=user_message[:80],
                type_message=msg_type or "inconnu",
            )
        except Exception as _rie:
            logging.error(f"[FINALIZE] record_interaction error: {_rie}")

    # Résumé automatique (Couche Argent) — tâche de fond
    try:
        def _background_summarize():
            try:
                maybe_auto_summarize()
            except Exception as _se:
                logging.error(f"[FINALIZE] auto_summarize error: {_se}")
        _t = threading.Thread(target=_background_summarize, daemon=True)
        _t.start()
    except Exception as _se:
        logging.error(f"[FINALIZE] auto_summarize schedule error: {_se}")

    # Atlas : apprentissage sémantique (Couche Or) — tâche de fond
    if user_message:
        try:
            def _background_atlas_learn(msg, resp):
                try:
                    from atlas_engine.atlas import learn as _atlas_learn
                    _atlas_learn(msg, resp)
                except Exception as _ae:
                    logging.debug(f"[FINALIZE] Atlas background skip: {_ae}")
            _t = threading.Thread(target=_background_atlas_learn, args=(user_message, response), daemon=True)
            _t.start()
        except Exception as _ae:
            logging.debug(f"[FINALIZE] Atlas schedule error: {_ae}")
    else:
        logging.debug("[FINALIZE] skip Atlas (pas de user_message)")

    # Cache prompt : l'invalidation n'est pas nécessaire ici.
    # Le cache a déjà un TTL de 60s et les changements mémoire
    # (threads background) sont asynchrones.

    return response
