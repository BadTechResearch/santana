"""Provider LLM pour Santana — DeepSeek principal, Groq fallback unique.

Chaîne de fallback : DeepSeek (retry ×2) → Groq.
Le passage d'un provider à l'autre est notifié au provider_manager
qui maintient l'état global (tag réponse, config dynamique).
"""

import copy
import json, logging, os, requests, time
from typing import Generator

logger = logging.getLogger(__name__)

from core import provider_manager as pm

DEEPSEEK_URL = "https://api.deepseek.com/v1"
GROQ_URL = "https://api.groq.com/openai/v1"

# Session HTTP persistante (connection pool, évite TCP handshake à chaque appel)
_HTTP_SESSION = requests.Session()
_HTTP_SESSION.headers.update({
    "Content-Type": "application/json",
})

PROVIDER_CHAIN = []


def _init_providers():
    global PROVIDER_CHAIN
    PROVIDER_CHAIN = []
    env = _get_env()

    # 1. DeepSeek — provider principal
    if env.get("deepseek_key"):
        PROVIDER_CHAIN.append({
            "name": "deepseek",
            "key": env["deepseek_key"],
            "url": DEEPSEEK_URL,
            "model": env.get("deepseek_model", "deepseek-v4-flash"),
        })

    # 2. Groq — fallback unique
    if env.get("groq_key"):
        PROVIDER_CHAIN.append({
            "name": "groq",
            "key": env["groq_key"],
            "url": GROQ_URL,
            "model": env.get("groq_model", "llama-3.3-70b-versatile"),
        })


def _truncate_messages(messages: list, provider_name: str) -> list:
    """Compresse les messages selon le provider actif.

    DeepSeek gère 1M tokens → pas de troncature.
    Groq a ~128K tokens de contexte → troncature agressive.

    Stratégie :
    - Garder le(s) message(s) system (prompt)
    - Garder le dernier message user ET le dernier assistant
    - Résumer les tool results trop longs
    """
    config = pm.get_provider_config(provider_name)
    max_chars = config["max_payload_chars"]

    if provider_name == "deepseek":
        return messages  # DeepSeek gère 1M tokens, pas de limite payload

    # Compter la taille actuelle
    current_size = len(json.dumps(messages, ensure_ascii=False))
    if current_size <= max_chars:
        return messages

    logger.warning("[TRUNCATE] Payload %d chars > %d pour %s — compression",
                   current_size, max_chars, provider_name)

    # Séparer system et conversation
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    if not other_msgs:
        return messages

    # Garder : système + dernier user + dernier assistant + dernier tool (si présent)
    last_user = None
    last_assistant = None
    last_tool = None

    for m in reversed(other_msgs):
        role = m.get("role")
        if role == "user" and last_user is None:
            last_user = m
        elif role == "assistant" and last_assistant is None:
            last_assistant = m
        elif role == "tool" and last_tool is None:
            last_tool = m
        if last_user and last_assistant:
            break

    truncated = list(system_msgs)
    if last_user:
        truncated.append(copy.deepcopy(last_user))
    if last_assistant:
        truncated.append(copy.deepcopy(last_assistant))
    if last_tool:
        truncated.append(copy.deepcopy(last_tool))

    # Tronquer les contenus tool trop longs
    for m in truncated:
        if m.get("role") == "tool" and m.get("content"):
            content = str(m["content"])
            if len(content) > 2000:
                m["content"] = content[:1000] + "\n[... tronqué par fallback ...]\n" + content[-500:]

    # Si encore trop gros : tronquer le system prompt aussi (Groq)
    new_size = len(json.dumps(truncated, ensure_ascii=False))
    if new_size > max_chars:
        for m in truncated:
            if m.get("role") == "system" and m.get("content"):
                content = str(m["content"])
                if len(content) > 10000:
                    m["content"] = content[:5000] + "\n[... prompt système tronqué pour Groq ...]\n" + content[-3000:]
                    break
        new_size = len(json.dumps(truncated, ensure_ascii=False))
    # Dernier recours : tronquer TOUS les contenus des messages non-système
    if new_size > max_chars:
        for m in truncated:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                content = str(m["content"])
                if len(content) > 5000:
                    m["content"] = content[:2500] + "\n[... contenu tronqué pour Groq ...]\n" + content[-1500:]
        new_size = len(json.dumps(truncated, ensure_ascii=False))
    logger.info("[TRUNCATE] Messages comprimés: %d → %d messages, %d → %d chars",
                len(messages), len(truncated), current_size, new_size)
    return truncated


def _check_env_on_start() -> dict:
    """Vérifie les clés API au démarrage et logue les problèmes."""
    env = _get_env()
    status = {}
    for name, key_field, model_field in [
        ("deepseek", "deepseek_key", "deepseek_model"),
        ("groq", "groq_key", "groq_model"),
    ]:
        key = env.get(key_field, "")
        model = env.get(model_field, "inconnu")
        if key:
            status[name] = {"ok": True, "model": model, "key_prefix": key[:7] + "..."}
        else:
            status[name] = {"ok": False, "model": model}
    return status


def _get_env():
    return {
        "deepseek_key": os.getenv('DEEPSEEK_API_KEY', '').strip(),
        "deepseek_model": os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash').strip(),
        "groq_key": os.getenv('GROQ_API_KEY', '').strip(),
        "groq_model": os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile').strip(),
    }


def _provider_headers(provider: dict) -> dict:
    return {
        "Authorization": f"Bearer {provider['key']}",
        "Content-Type": "application/json",
    }


def _call_with_retry(provider: dict, fn, *args, **kwargs):
    """Appelle 'fn' pour ce provider avec retry exponentiel.

    DeepSeek : jusqu'à 2 retries avant d'abandonner (transient 401/429).
    Groq : 1 retry rapide.
    """
    config = pm.get_provider_config(provider["name"])
    max_attempts = 1 + config["retry_count"]  # 1 vrai appel + N retry
    delay = config["retry_delay"]

    last_error = None
    for attempt in range(max_attempts):
        try:
            result = fn(*args, **kwargs)
            # Succès → notifier le manager
            if provider["name"] == "deepseek":
                pm.set_active_provider("deepseek")
                pm.record_deepseek_success()
            else:
                pm.set_active_provider("groq")
            return result
        except requests.exceptions.HTTPError as e:
            last_error = e
            status = e.response.status_code if e.response else 0
            # 401 (auth) ou 403 (forbidden) → inutile de retenter
            if status in (401, 403):
                logger.warning("[RETRY] %s HTTP %d — non récupérable, fallback immédiat",
                               provider['name'], status)
                pm.set_active_provider("groq" if provider["name"] == "deepseek" else "deepseek")
                break
            # 429 (rate limit) ou 5xx (server error) → retry pertinent
            if attempt < max_attempts - 1:
                logger.warning("[RETRY] %s HTTP %d — tentative %d/%d dans %.1fs",
                               provider['name'], status, attempt + 1, max_attempts, delay)
                time.sleep(delay)
                delay *= 2  # exponentiel
            else:
                logger.warning("[RETRY] %s: toutes les %d tentatives épuisées, fallback",
                               provider['name'], max_attempts)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            if attempt < max_attempts - 1:
                logger.warning("[RETRY] %s timeout/connection — tentative %d/%d dans %.1fs",
                               provider['name'], attempt + 1, max_attempts, delay)
                time.sleep(delay)
                delay *= 2
            else:
                logger.warning("[RETRY] %s: timeout épuisé après %d tentatives, fallback",
                               provider['name'], max_attempts)
        except Exception as e:
            last_error = e
            logger.warning("[RETRY] %s: erreur inattendue: %s", provider['name'], e)
            break  # erreur inconnue → fallback immédiat

    raise last_error or RuntimeError(f"{provider['name']} indisponible")


def complete(messages, model=None, max_tokens=128000, tools=None, tool_choice='auto', timeout=120):
    """Appel LLM bloquant — fallback sur chaque provider jusqu'au premier succès."""
    if not PROVIDER_CHAIN:
        _init_providers()
    if not PROVIDER_CHAIN:
        raise RuntimeError("Aucune clé API configurée")

    last_error = None
    for provider in PROVIDER_CHAIN:
        try:
            truncated = _truncate_messages(messages, provider["name"])
            # Utiliser le max_tokens adapté au provider si pas d'override
            p_config = pm.get_provider_config(provider["name"])
            p_max_tokens = min(max_tokens, p_config["max_tokens"]) if max_tokens == 128000 else max_tokens
            return _call_with_retry(
                provider, _provider_complete,
                provider, truncated,
                model or provider["model"],
                p_max_tokens, tools, tool_choice, timeout,
            )
        except Exception as e:
            last_error = e
            logger.warning("[PROVIDER] %s a échoué, fallback: %s", provider['name'], e)
            continue
    raise RuntimeError(f"Tous les providers indisponibles: {last_error}")


def _provider_complete(provider, messages, model, max_tokens, tools, tool_choice, timeout):
    headers = _provider_headers(provider)
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    url = f"{provider['url']}/chat/completions"
    resp = _HTTP_SESSION.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    msg = data["choices"][0]["message"]
    finish_reason = data["choices"][0].get("finish_reason", "stop")

    content = msg.get("content")
    if not content and msg.get("reasoning"):
        content = msg["reasoning"]

    # Enregistrer les tokens consommés
    usage = data.get("usage", {})
    if usage:
        try:
            from tools.cost_governor import record_usage
            record_usage(
                prompt_tokens=usage.get("prompt_tokens", 0) or 0,
                completion_tokens=usage.get("completion_tokens", 0) or 0,
                cached_tokens=usage.get("prompt_cache_hit_tokens", 0) or 0,
                provider_name=provider["name"],
            )
        except Exception:
            logger.exception("[PROVIDER] Erreur enregistrement usage réel")

    return {
        "message": {
            "role": msg.get("role", "assistant"),
            "content": content or "",
            "tool_calls": msg.get("tool_calls"),
        },
        "finish_reason": finish_reason,
        "usage": usage,
    }


def complete_stream(messages, model=None, max_tokens=128000, tools=None, tool_choice='auto', timeout=120, **kwargs):
    if kwargs:
        logger.debug(f"[STREAM] Ignored kwargs: {kwargs}")
    """Vrai streaming LLM — yield chaque token en temps réel via SSE."""
    if not PROVIDER_CHAIN:
        _init_providers()
    if not PROVIDER_CHAIN:
        raise RuntimeError("Aucune clé API configurée")

    last_error = None
    for provider in PROVIDER_CHAIN:
        # Retry loop interne pour ce provider (DeepSeek: ×3, Groq: ×2)
        p_config = pm.get_provider_config(provider["name"])
        max_attempts = 1 + p_config["retry_count"]
        retry_delay = p_config["retry_delay"]

        for attempt in range(max_attempts):
            try:
                truncated = _truncate_messages(messages, provider["name"])
                p_max_tokens = min(max_tokens, p_config["max_tokens"]) if max_tokens == 128000 else max_tokens
                headers = _provider_headers(provider)
                body = {
                    "model": model or provider["model"],
                    "messages": truncated,
                    "max_tokens": p_max_tokens,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if tools:
                    body["tools"] = tools
                    body["tool_choice"] = tool_choice

                url = f"{provider['url']}/chat/completions"
                logger.info(f"[STREAM] Appel {provider['name']}/{body['model']} "
                            f"en streaming (tentative {attempt + 1}/{max_attempts})")

                with _HTTP_SESSION.post(url, headers=headers, json=body,
                                   timeout=timeout, stream=True) as resp:
                    resp.raise_for_status()

                    # Succès → notifier le manager
                    if provider["name"] == "deepseek":
                        pm.set_active_provider("deepseek")
                        pm.record_deepseek_success()
                    else:
                        pm.set_active_provider("groq")

                    content = ""
                    reasoning = ""
                    tool_calls_parts = {}
                    finish_reason = "stop"
                    response_usage = {}

                    for line in resp.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            break

                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            # DeepSeek renvoie l'usage dans le dernier chunk SSE
                            # {"choices":[], "usage":{...}} avant [DONE]
                            usage_data = chunk.get("usage")
                            if usage_data:
                                response_usage = usage_data
                            continue

                        delta = choices[0].get("delta", {})
                        f_reason = choices[0].get("finish_reason")

                        if "content" in delta and delta["content"]:
                            token = delta["content"]
                            content += token
                            yield {'type': 'content', 'content': token}

                        if "reasoning_content" in delta and delta["reasoning_content"]:
                            reasoning += delta["reasoning_content"]
                        elif "reasoning" in delta and delta["reasoning"]:
                            reasoning += delta["reasoning"]

                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_parts:
                                    tool_calls_parts[idx] = {
                                        "id": tc.get("id", f"call_{idx}"),
                                        "name": "",
                                        "arguments": "",
                                    }
                                part = tool_calls_parts[idx]
                                if "id" in tc and tc["id"]:
                                    part["id"] = tc["id"]
                                if tc.get("function"):
                                    if tc["function"].get("name"):
                                        part["name"] += tc["function"]["name"]
                                    if tc["function"].get("arguments"):
                                        part["arguments"] += tc["function"]["arguments"]

                        if f_reason:
                            finish_reason = f_reason

                    tool_calls = None
                    if tool_calls_parts:
                        tool_calls = []
                        for idx in sorted(tool_calls_parts.keys()):
                            part = tool_calls_parts[idx]
                            tool_calls.append({
                                "id": part["id"],
                                "type": "function",
                                "function": {
                                    "name": part["name"],
                                    "arguments": part["arguments"],
                                },
                            })

                    logger.info(f"[STREAM] Termine: {len(content)} chars, outils={'oui' if tool_calls else 'non'}")
                    resolved_content = content or reasoning or ""
                    yield {'type': 'complete', 'content': resolved_content,
                           'finish_reason': finish_reason,
                           'tool_calls': tool_calls,
                           'usage': response_usage,
                           'reasoning_content': reasoning or None}
                return  # succès → sortir du provider loop

            except requests.exceptions.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response else 0
                try:
                    logger.warning(f"[STREAM] {provider['name']} HTTP {status}: {e.response.text[:200]}")
                except Exception:
                    logger.warning(f"[STREAM] {provider['name']} HTTP {status}")
                # 401/403 → inutile de retenter
                if status in (401, 403):
                    pm.set_active_provider("groq" if provider["name"] == "deepseek" else "deepseek")
                    break  # sortir du retry loop, passer au provider suivant
                # 429/5xx → retry pertinent
                if attempt < max_attempts - 1:
                    logger.warning("[STREAM-RETRY] %s tentative %d/%d dans %.1fs",
                                   provider['name'], attempt + 1, max_attempts, retry_delay)
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.warning("[STREAM-RETRY] %s: toutes les %d tentatives épuisées",
                                   provider['name'], max_attempts)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = e
                if attempt < max_attempts - 1:
                    logger.warning("[STREAM-RETRY] %s timeout — tentative %d/%d dans %.1fs",
                                   provider['name'], attempt + 1, max_attempts, retry_delay)
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    logger.warning("[STREAM-RETRY] %s: timeout épuisé après %d tentatives",
                                   provider['name'], max_attempts)
            except Exception as e:
                last_error = e
                logger.warning(f"[STREAM] {provider['name']} a echoue: {e}")
                break  # erreur inconnue → sortir, prochain provider

    if last_error:
        yield {'type': 'error', 'content': f'LLM: {last_error}'}
    else:
        yield {'type': 'error', 'content': 'Aucun provider configure'}
