"""Multi-provider LLM resolution for Santana.
Chaîne : Mistral Small → Groq (gratuit).
L'utilisateur configure ses clés API dans .env.
"""
import json, logging, os, requests, time

logger = logging.getLogger(__name__)

MISTRAL_URL = "https://api.mistral.ai/v1"
GROQ_URL = "https://api.groq.com/openai/v1"

PROVIDER_CHAIN = []

def _init_providers():
    global PROVIDER_CHAIN
    PROVIDER_CHAIN = []
    env = _get_env()
    if env["mistral_key"]:
        PROVIDER_CHAIN.append({
            "name": "mistral",
            "key": env["mistral_key"],
            "url": MISTRAL_URL,
            "model": env["mistral_model"],
        })
    if env["groq_key"]:
        PROVIDER_CHAIN.append({
            "name": "groq",
            "key": env["groq_key"],
            "url": GROQ_URL,
            "model": "llama-3.3-70b-versatile",
        })

def _get_env():
    return {
        "mistral_key": os.getenv('MISTRAL_API_KEY', '').strip(),
        "mistral_model": os.getenv('MISTRAL_MODEL', 'mistral-small-3.2-24b').strip(),
        "groq_key": os.getenv('GROQ_API_KEY', '').strip(),
    }

def complete(messages, model=None, max_tokens=32000, tools=None, tool_choice='auto', timeout=120):
    if not PROVIDER_CHAIN:
        _init_providers()
    last_error = None
    for provider in PROVIDER_CHAIN:
        try:
            return _provider_complete(provider, messages, model or provider["model"], max_tokens, tools, tool_choice, timeout)
        except Exception as e:
            last_error = e
            logger.warning(f"[FALLBACK] {provider['name']} failed: {e}")
            continue
    raise RuntimeError(f"Tous les providers indisponibles: {last_error}")

def _provider_complete(provider, messages, model, max_tokens, tools, tool_choice, timeout):
    headers = {
        "Authorization": f"Bearer {provider['key']}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    resp = requests.post(f"{provider['url']}/chat/completions", headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]
