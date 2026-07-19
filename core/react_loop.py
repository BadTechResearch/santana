#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
react_loop.py — Boucle ReAct principale de Santana.

Déclenché par handle_message (santana.py). Chaque message passe par :
  1. Désambiguïsation → 2. Classification → 3. Prompt système
  → 4. Appel LLM (streaming) → 5. Exécution outils → 6. Livraison
  → 7. Évaluation différée.
"""

import re
import os, json, logging, time, asyncio, sys, threading
from typing import Dict, Optional
from datetime import datetime

from tools.cost_governor import check_cost_governor, estimate_cost_from_messages, record_usage
from tools.tools import execute_tool, TOOLS
from deepseek_client import complete, complete_stream
from agent.context import (
    init_session as init_context_session,
    push_exchange, get_session_buffer, get_session_summary,
    maybe_auto_summarize, reset_session
)
from core.provider_manager import get_active_provider
from agent.orchestrator import build_system_prompt, classify_message
from core.disambiguate import disambiguate
from agent.evaluator import evaluate_response, log_evaluation
from memory.memory import get_recent_memory, save_message

from core.utils import get_base_dir, strip_dsml

# ─── Task State (reprise après interruption) ────────────────────────
from core.task_state import set_task, get_task, clear_task, resume_prompt


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
    except Exception as _ee:
        logging.error(f"[EVAL-BG] Run error: {_ee}")

BASE_DIR = get_base_dir()

# ── Constantes de sécurité ──────────────────────────────────────────
_SESSION_TIMEOUT = 300     # 5 min max par session utilisateur
_ITERATION_TIMEOUT = 120   # 2 min max par itération LLM
_MAX_ITER = 20             # Max d'itérations outillage (garde-fou)
_EXPENSIVE_TOOLS = {      # Outils bloqués à 95%+ du budget
    "tool_social_search", "tool_deep_search"
}
_LEAK_PATTERNS = (
    '<invoke', '<tool_calls>', '<tool_call>', '[Calling tool:'
)

logger = logging.getLogger(__name__)


# Cache des noms d'outils autorisés (construit une fois depuis TOOLS)
_TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOLS)
# Outils dont les paramètres contiennent naturellement du code/commandes
_SKIP_METACHAR_CHECK = frozenset()
_SHELL_METACHARS = frozenset("$`;&|><")


def _validate_tool_call(tname: str, targs: dict) -> str | None:
    """Valide un appel d'outil — existence + types des paramètres + métacaractères."""
    if tname not in _TOOL_NAMES:
        return f"Outil '{tname}' inconnu."
    # Vérifier les métacaractères shell dans les arguments
    if tname not in _SKIP_METACHAR_CHECK:
        for k, v in targs.items():
            sv = str(v)
            if any(c in sv for c in _SHELL_METACHARS):
                return f"Paramètre '{k}' contient des métacaractères interdits"
    # Trouver la spec de l'outil
    spec = None
    for t in TOOLS:
        if t["function"]["name"] == tname:
            spec = t["function"]
            break
    if not spec:
        return None  # déjà vérifié mais sécurité
    for pname, pinfo in spec.get("parameters", {}).items():
        if pname in targs:
            expected = pinfo.get("type", "string")
            val = targs[pname]
            if expected == "string" and not isinstance(val, str):
                targs[pname] = str(val)
            elif expected in ("number", "integer") and isinstance(val, str):
                try:
                    targs[pname] = int(val) if expected == "integer" else float(val)
                except (ValueError, TypeError):
                    return f"Paramètre '{pname}' devrait être {expected}, reçu '{type(val).__name__}'"
    return None


def _detect_leak(content: str) -> bool:
    """Détecte les tool calls exportés en texte par DeepSeek au lieu d'appels natifs."""
    return any(p in content for p in _LEAK_PATTERNS)


async def _stream_to_message(messages, model, max_tokens, tools, tool_choice,
                             stream_callback=None, provider='deepseek'):
    """Appel LLM streaming dans un thread. Retourne {message, finish_reason, usage}.

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
                if stream_callback and stream_active:
                    if _detect_leak(c):
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


async def _stream_and_collect(messages, model, max_tokens, tools, tool_choice,
                              stream_callback=None, provider='deepseek'):
    """Wrapper synchrone pour compatibilité (délègue à _stream_to_message)."""
    return await _stream_to_message(
        messages, model=model, max_tokens=max_tokens,
        tools=tools, tool_choice=tool_choice,
        stream_callback=stream_callback, provider=provider
    )


def reset_state():
    """Réinitialise l'état global de react_loop (task_state + cache)."""
    try:
        clear_task()
    except Exception:
        pass


async def _finalize(response: str, user_message: str, msg_type: str = "", tools_used: set = None):
    """Point de sortie unique : écrit en mémoire + Nettoie task_state."""
    if tools_used:
        for t in tools_used:
            logger.info(f"[TOOL] tool_call_finalized {t}")
    try:
        clear_task()
    except Exception:
        pass
    push_exchange("assistant", response)
    save_message("assistant", response, msg_type=msg_type)
    maybe_auto_summarize()
    # Enregistrement des patterns de dialogue
    if user_message and msg_type:
        try:
            from agent.patterns import record_interaction
            record_interaction(
                timestamp=datetime.now().isoformat(),
                sujet=user_message[:80],
                type_message=msg_type or "inconnu",
            )
        except Exception:
            pass
    return response


async def react_loop(user_message: str,
                     stream_callback=None, _stats: dict = None) -> str:
    """Boucle principale. stream_callback(content: str) appelé pour chaque token."""
    # ── Initialiser la tâche pour reprise si interrompu ──
    try:
        _action_label = user_message[:100].replace('\n', ' ').strip()
        set_task("Réponse Santana", "analyse", _action_label)
    except Exception:
        pass

    init_context_session()
    push_exchange("user", user_message)
    _start_time = time.time()
    _ttft_start = time.time()
    _tools_called: set = set()

    try:
        user_message = disambiguate(user_message)
    except Exception as _de:
        logger.error(f"[DISAMBIGUATE] error: {_de}")

    msg_type = classify_message(user_message)

    # Reclassifier set_task avec le type de message
    try:
        set_task("Réponse Santana", msg_type, _action_label)
    except Exception:
        pass

    SYSTEM = build_system_prompt(user_message=user_message, msg_type=msg_type)
    messages = [{"role": "system", "content": SYSTEM}]

    # Vérifier si une tâche précédente a été interrompue
    try:
        _resume_ctx = resume_prompt()
        if _resume_ctx:
            messages.append({"role": "system", "content": _resume_ctx})
            logger.info(f"[TASK] Contexte de reprise injecté ({len(_resume_ctx)} chars)")
    except Exception:
        pass

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

    text_len = len(user_message.strip())
    if stream_callback:
        stream_callback("__MSGTYPE__" + msg_type)

    provider = get_active_provider()
    actual_provider = provider
    actual_tools = []
    for tname, tspec in TOOLS.items():
        tool_def = {
            "type": "function",
            "function": {
                "name": tname,
                "description": tspec.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
        for pname, pinfo in tspec.get("parameters", {}).items():
            ptype = pinfo.get("type", "string")
            tool_def["function"]["parameters"]["properties"][pname] = {
                "type": ptype,
                "description": pinfo.get("description", ""),
            }
        actual_tools.append(tool_def)

    use_stream = stream_callback is not None
    last_content = ""
    _last_tokens = 0
    max_iter = _MAX_ITER
    iteration = 0
    is_self_query = any(kw in user_message.lower()
                        for kw in ["qui es-tu", "décris-toi", "décrivez-vous",
                                   "parle de toi", "ton code", "ton architecture",
                                   "tes outils", "auto-description"])

    while iteration < max_iter:
        _elapsed = time.time() - _start_time
        if _elapsed > _SESSION_TIMEOUT:
            logger.warning(f"[TIMEOUT] Session dépassée ({_elapsed:.0f}s > {_SESSION_TIMEOUT}s)")
            break

        if iteration > 0 and _elapsed > 15 * (iteration // 15):
            logger.info("[HEARTBEAT] Itération %d, écoulé %.0fs", iteration, _elapsed)

        mt = 32000 if iteration == 0 else 8000

        _gov = check_cost_governor()
        if _gov == "STOP":
            logger.error("[COST] STOP — budget épuisé")
            last_content = (
                "Budget de session épuisé pour l'instant. Utilise /reset pour "
                "réinitialiser le compteur, ou attends le prochain cycle."
            )
            break
        elif _gov == "THROTTLE":
            logger.warning("[COST] THROTTLE — 95%% du budget atteint, outils coûteux coupés")
            if actual_tools:
                actual_tools = [t for t in actual_tools
                                if t["function"]["name"] not in _EXPENSIVE_TOOLS]
            max_iter = min(max_iter, iteration + 2)

        if actual_tools:
            tc = "auto"
        else:
            tc = "none"

        if iteration == 0:
            _pre_llm_ms = (time.time() - _ttft_start) * 1000
            logger.info(f"[TIMING] pre_llm_ms={_pre_llm_ms:.0f} msg_type={msg_type} provider={actual_provider}")

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
            logger.warning(f"[TIMEOUT] Itération {iteration} bloquée > {_ITERATION_TIMEOUT}s")
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

        _usage = choice.get('usage', {})
        if _usage:
            try:
                _pt = _usage.get('prompt_tokens', 0) or 0
                _ct = _usage.get('completion_tokens', 0) or 0
                if _pt or _ct:
                    record_usage(
                        prompt_tokens=_pt,
                        completion_tokens=_ct,
                        cached_tokens=_usage.get('prompt_cache_hit_tokens', 0) or 0,
                        provider_name=actual_provider
                    )
                    _last_tokens = _pt + _ct
            except Exception as _ue:
                logger.error(f"[COST] record_usage error: {_ue}")

        if content:
            last_content = content

        # Réponse finale sans outils
        if finish_reason in ("stop", "length") and not tool_calls:
            if content and _detect_leak(content):
                logger.warning("[DSML] Tool call leak détecté en XML, parsing et exécution directe")
                xml_tools = re.findall(r'<invoke name="([^"]+)"(.*?)</invoke>', content, re.DOTALL)
                executed_any = False
                for tname, tbody in xml_tools:
                    tname = tname.strip()
                    params = re.findall(r'<parameter name="([^"]+)"[^>]*>(.*?)</parameter>', tbody, re.DOTALL)
                    targs = {p[0]: p[1].strip() for p in params}
                    try:
                        # Tracker l'outil
                        try:
                            set_task("Réponse Santana", f"outil:{tname}", _action_label)
                        except Exception:
                            pass
                        tresult = execute_tool(tname, targs)
                        _tools_called.add(tname)
                        logger.info(f"[DSML-XML] {tname}({targs}) -> {str(tresult)[:200]}")
                        messages.append({
                            "role": "tool", "type": "tool",
                            "tool_call_id": f"xml_{iteration}_{tname}",
                            "content": str(tresult)
                        })
                        executed_any = True
                    except Exception as _xe:
                        logger.error(f"[DSML-XML] Erreur exécution {tname}: {_xe}")
                if executed_any:
                    iteration += 1
                    continue
                logger.warning("[DSML] Aucun outil XML parsé, retry avec instruction")
                last_content = strip_dsml(content) or last_content
                iteration += 1
                if iteration < max_iter:
                    messages.append({"role": "user", "content": "Utilise les appels de fonction pour chercher sur le web."})
                    continue
                return await _finalize(last_content or "Je n'ai pas pu effectuer la recherche.", user_message, msg_type=msg_type, tools_used=_tools_called)

            cleaned = strip_dsml(content) if content else ""
            if finish_reason == "length" and cleaned:
                logger.warning(f"[LENGTH] Limite atteinte — {len(cleaned)} chars, livraison immédiate")
            if not is_self_query:
                _schedule_background_eval(cleaned, user_message)
            return await _finalize(cleaned or "Pas de réponse.", user_message, msg_type=msg_type, tools_used=_tools_called)

        if not tool_calls:
            cleaned = strip_dsml(content) if content else ""
            if not is_self_query:
                _schedule_background_eval(cleaned, user_message)
            return await _finalize(cleaned or "Je n'ai pas compris.", user_message, msg_type=msg_type, tools_used=_tools_called)

        # Nettoyer le XML leaké de l'historique
        clean_content = msg.get("content", "") or ""
        if _detect_leak(clean_content):
            clean_content = re.sub(r'<invoke name="[^"]+".*?</invoke>', '',
                                     clean_content, flags=re.DOTALL).strip()
            clean_content = re.sub(r'<tool_calls>.*?</tool_calls>', '',
                                     clean_content, flags=re.DOTALL).strip()
        msg["content"] = clean_content
        messages.append(msg)

        # Itération avec outils — tracker l'étape
        try:
            set_task("Réponse Santana", f"itération {iteration+1}", _action_label[:60])
        except Exception:
            pass

        # Exécuter chaque tool call
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            tname = tc.get("function", {}).get("name", "")
            try:
                targs = json.loads(tc.get("function", {}).get("arguments", "{}"))
            except json.JSONDecodeError:
                logger.warning(f"[TOOL] Échec parsing args pour {tname}")
                targs = {}

            error = _validate_tool_call(tname, targs)
            if error:
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": error})
                continue

            try:
                # Tracker l'outil avant exécution
                try:
                    set_task("Réponse Santana", f"outil:{tname}", _action_label[:60])
                except Exception:
                    pass
                tresult = execute_tool(tname, targs)
                _tools_called.add(tname)
                logger.info(f"[TOOL] {tname}(...) -> {str(tresult)[:200]}")
            except Exception as _te:
                tresult = f"Erreur: {_te}"
                logger.error(f"[TOOL] Erreur {tname}: {_te}")

            messages.append({"role": "tool", "tool_call_id": tc_id, "content": str(tresult)})

        iteration += 1

    # Point de sortie
    if _stats is not None:
        _stats['tool_count'] = len(_tools_called)
        _stats['provider'] = get_active_provider()
        _stats['token_count'] = _last_tokens

    if last_content:
        response = strip_dsml(last_content)
    else:
        logger.warning("[LOOP] max_iter épuisé sans contenu")
        response = "Je n'ai pas pu trouver l'information avec les outils disponibles. Peux-tu préciser ta question ?"
    return await _finalize(response, user_message, msg_type=msg_type, tools_used=_tools_called)
