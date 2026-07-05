"""Provider LLM pour Santana — DeepSeek natif, OpenRouter fallback, Groq gratuit."""
import json, logging, os, requests, time
from typing import Generator

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1"
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

    # 1. DeepSeek DIRECT — provider principal
    if env.get("deepseek_key"):
        PROVIDER_CHAIN.append({
            "name": "deepseek",
            "key": env["deepseek_key"],
            "url": DEEPSEEK_URL,
            "model": env.get("deepseek_model", "deepseek-v4-flash"),
        })

    # 2. OpenRouter — fallback (DeepSeek V4 Flash)
    if env.get("openrouter_key"):
        PROVIDER_CHAIN.append({
            "name": "openrouter",
            "key": env["openrouter_key"],
            "url": OPENROUTER_URL,
            "model": env.get("openrouter_model", "deepseek/deepseek-v4-flash"),
        })

    # 3. Groq — fallback gratuit (Llama 3.3 70B)
    if env.get("groq_key"):
        PROVIDER_CHAIN.append({
            "name": "groq",
            "key": env["groq_key"],
            "url": GROQ_URL,
            "model": env.get("groq_model", "llama-3.3-70b-versatile"),
        })


def _get_env():
    return {
        "openrouter_key": os.getenv('OPENROUTER_API_KEY', '').strip(),
        "openrouter_model": os.getenv('OPENROUTER_MODEL', 'deepseek/deepseek-v4-flash').strip(),
        "groq_key": os.getenv('GROQ_API_KEY', '').strip(),
        "groq_model": os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile').strip(),
        "deepseek_key": os.getenv('DEEPSEEK_API_KEY', '').strip(),
        "deepseek_model": os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash').strip(),
    }


def _provider_headers(provider: dict) -> dict:
    return {
        "Authorization": f"Bearer {provider['key']}",
        "Content-Type": "application/json",
    }


def complete(messages, model=None, max_tokens=32000, tools=None, tool_choice='auto', timeout=120):
    """Appel LLM bloquant — fallback sur chaque provider jusqu'au premier succès."""
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
    }


def complete_stream(messages, model=None, max_tokens=32000, tools=None, tool_choice='auto', timeout=120, **kwargs):
    if kwargs:
        logger.debug(f"[STREAM] Ignored kwargs: {kwargs}")
    """Vrai streaming LLM — yield chaque token en temps réel via SSE."""
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
                tool_calls_parts = {}
                finish_reason = "stop"

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
                       'reasoning_content': reasoning or None}
            return

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
