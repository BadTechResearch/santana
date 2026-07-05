"""Provider LLM pour Santana — DeepSeek direct en premier, OpenRouter fallback."""
import json, logging, os, requests, time
from typing import Generator

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEEPSEEK_URL = "https://api.deepseek.com/v1"
NOUS_URL = "https://inference-api.nousresearch.com/v1"

# Session HTTP persistante (P2.1 — connection pool, évite TCP handshake à chaque appel)
_HTTP_SESSION = requests.Session()
_HTTP_SESSION.headers.update({
    "Content-Type": "application/json",
})

PROVIDER_CHAIN = []


def _init_providers():
    global PROVIDER_CHAIN
    PROVIDER_CHAIN = []
    env = _get_env()

    # DeepSeek DIRECT en premier (provider principal — unique provider réel)
    # DeepSeek V4 Flash natif, le plus rapide (~200ms), coût réel le plus bas
    # grâce au cache hit (94-96% sur les sessions Serge = $0.0028/1M au lieu de $0.14)
    if env.get("deepseek_key"):
        PROVIDER_CHAIN.append({
            "name": "deepseek",
            "key": env["deepseek_key"],
            "url": DEEPSEEK_URL,
            "model": env.get("deepseek_model", "deepseek-v4-flash"),
        })

    # Nous Portal (StepFun free) en deuxième — fallback léger, gratuit
    # Utilisé uniquement par Hermès Agent, pas par Santana en production.
    # Modèle : stepfun/step-3.7-flash:free
    if env.get("nous_key"):
        PROVIDER_CHAIN.append({
            "name": "nous",
            "key": env["nous_key"],
            "url": NOUS_URL,
            "model": env.get("nous_model", "stepfun/step-3.7-flash:free"),
        })

    # OpenRouter en troisième fallback (DeepSeek V4 Flash via API)
    if env.get("openrouter_key"):
        PROVIDER_CHAIN.append({
            "name": "openrouter",
            "key": env["openrouter_key"],
            "url": OPENROUTER_URL,
            "model": env.get("openrouter_model", "deepseek/deepseek-v4-flash"),
        })


def _get_env():
    return {
        "nous_key": os.getenv('NOUS_API_KEY', '').strip(),
        "nous_model": os.getenv('NOUS_MODEL', 'stepfun/step-3.7-flash:free').strip(),
        "openrouter_key": os.getenv('OPENROUTER_API_KEY', '').strip(),
        "openrouter_model": os.getenv('OPENROUTER_MODEL', 'deepseek/deepseek-v4-flash').strip(),
        "deepseek_key": os.getenv('DEEPSEEK_API_KEY', '').strip(),
        "deepseek_model": os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash').strip(),
    }


def _provider_headers(provider: dict) -> dict:
    return {
        "Authorization": f"Bearer {provider['key']}",
        "Content-Type": "application/json",
    }


def complete(messages, model=None, max_tokens=32000, tools=None, tool_choice='auto', timeout=120):
    """Appel LLM bloquant — fallback sur chaque provider jusqu'au premier succès.

    Args:
        messages: liste de dicts [{"role": "user", "content": "..."}]
        model: override du modèle (None = utiliser celui du provider)
        max_tokens: max tokens de sortie (défaut 32000)
        tools: liste d'outils OpenAI function-calling
        tool_choice: 'auto' ou 'none'
        timeout: timeout HTTP en secondes (défaut 120)

    Returns:
        dict avec "message" (role + content + optionnel tool_calls) et "finish_reason"
    """
    if not PROVIDER_CHAIN:
        _init_providers()
    if not PROVIDER_CHAIN:
        raise RuntimeError("Aucune clé API configurée")

    last_error = None
    for provider in PROVIDER_CHAIN:
        try:
            return _provider_complete(
                provider, messages,
                model or provider["model"],
                max_tokens, tools, tool_choice, timeout,
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

    # Gère le format StepFun : met le contenu reasoning dans content si content est vide
    content = msg.get("content")
    if not content and msg.get("reasoning"):
        content = msg["reasoning"]

    # ── Usage réel DeepSeek : tokens consommés (coût réel) ──
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
    }


def complete_stream(messages, model=None, max_tokens=32000, tools=None, tool_choice='auto', timeout=120, **kwargs):
    if kwargs:
        logger.debug(f"[STREAM] Ignored kwargs: {kwargs}")
    """Vrai streaming LLM — yield chaque token en temps réel via SSE.

    Itère sur les providers dans PROVIDER_CHAIN jusqu'au premier succès.
    Yield `{'type': 'content', 'content': token}` pour chaque token.
    Yield `{'type': 'complete', ...}` à la fin.
    """
    if not PROVIDER_CHAIN:
        _init_providers()
    if not PROVIDER_CHAIN:
        raise RuntimeError("Aucune clé API configurée")

    last_error = None
    for provider in PROVIDER_CHAIN:
        try:
            headers = _provider_headers(provider)
            body = {
                "model": model or provider["model"],
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if tools:
                body["tools"] = tools
                body["tool_choice"] = tool_choice

            url = f"{provider['url']}/chat/completions"
            logger.info(f"[STREAM] Appel {provider['name']}/{body['model']} en streaming")

            with _HTTP_SESSION.post(url, headers=headers, json=body,
                               timeout=timeout, stream=True) as resp:
                resp.raise_for_status()

                content = ""
                reasoning = ""
                tool_calls_parts = {}  # index -> {id, name, args_buffer}
                finish_reason = "stop"

                # StepFun (Nous Portal) a un charset bugué en streaming
                # On utilise decode_unicode=True pour les autres providers
                use_raw = provider["name"] == "nous"

                for line in resp.iter_lines(decode_unicode=not use_raw):
                    if not line:
                        continue
                    if use_raw:
                        # StepFun : decoder manuellement en UTF-8
                        if not line.startswith(b"data: "):
                            continue
                        payload = line[6:]
                        if payload == b"[DONE]":
                            break
                        try:
                            payload_str = payload.decode("utf-8")
                        except UnicodeDecodeError:
                            continue
                    else:
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            break
                        payload_str = payload

                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    f_reason = choices[0].get("finish_reason")

                    # Contenu textuel
                    if "content" in delta and delta["content"]:
                        token = delta["content"]
                        content += token
                        yield {'type': 'content', 'content': token}

                    # Raisonnement (DeepSeek R1: reasoning_content, StepFun: reasoning)
                    if "reasoning_content" in delta and delta["reasoning_content"]:
                        reasoning += delta["reasoning_content"]
                    elif "reasoning" in delta and delta["reasoning"]:
                        reasoning += delta["reasoning"]

                    # Tool calls
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

                    # Finish reason
                    if f_reason:
                        finish_reason = f_reason

                # Assembler les tool_calls finaux
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
                # StepFun place parfois la réponse dans reasoning sans jamais la mettre dans content
                resolved_content = content or reasoning or ""
                yield {'type': 'complete', 'content': resolved_content,
                       'finish_reason': finish_reason,
                       'tool_calls': tool_calls,
                       'reasoning_content': reasoning or None}
            return  # Succès → sortir de la boucle

        except requests.exceptions.HTTPError as e:
            last_error = e
            try:
                logger.warning(f"[STREAM] {provider['name']} HTTP {e.response.status_code}: {e.response.text[:300]}")
            except Exception:
                logger.warning(f"[STREAM] {provider['name']} HTTP {e.response.status_code}, fallback...")
        except Exception as e:
            last_error = e
            logger.warning(f"[STREAM] {provider['name']} a echoue: {e}, fallback suivant...")

    if last_error:
        yield {'type': 'error', 'content': f'LLM: {last_error}'}
    else:
        yield {'type': 'error', 'content': 'Aucun provider configure'}
