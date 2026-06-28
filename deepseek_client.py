#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deepseek_client.py — Client LLM exclusif DeepSeek pour Santana.
Provider DeepSeek V4 Flash uniquement. Cloudflare supprimé.

Exports: complete(), complete_stream(), ask()
"""

import os, time, requests, json, logging

# ── Constantes ────────────────────────────────────────────────────────────
DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash').strip()
DEEPSEEK_PRO_MODEL = os.getenv('DEEPSEEK_PRO_MODEL', 'deepseek-v4-pro').strip()
DEEPSEEK_KEY = os.getenv('DEEPSEEK_API_KEY', '').strip()


def _surveiller_externe(url: str, contexte: str) -> None:
    """F8 — Audit souveraineté temps réel ; ne doit jamais bloquer l'appel LLM."""
    try:
        from agent.souverainete import surveiller_appel_externe
        surveiller_appel_externe(url, contexte)
    except Exception as _se:
        logging.debug("[SOUVERAINETE] surveillance indisponible: %s", _se)


# ── Normalisation des messages (API DeepSeek v4 exige `type` sur tous) ─────

def _normalize_messages(messages: list) -> list:
    """Ajoute le champ `type` manquant à chaque message."""
    normalized = []
    for m in messages:
        if "type" not in m:
            # Tool messages ont déjà type="tool"; les autres → "text"
            if m.get("role") == "tool":
                m["type"] = "tool"
            else:
                m["type"] = "text"
        normalized.append(m)
    return normalized


# ── Appels DeepSeek ───────────────────────────────────────────────────────

def _ds_complete(messages, model, max_tokens, tools, tool_choice, timeout):
    """Appel direct à l'API DeepSeek."""
    model = model or DEEPSEEK_MODEL
    if not DEEPSEEK_KEY:
        raise RuntimeError("DEEPSEEK_API_KEY non configurée")

    headers = {
        'Authorization': f'Bearer {DEEPSEEK_KEY}',
        'Content-Type': 'application/json'
    }
    body = {'model': model, 'max_tokens': max_tokens, 'messages': _normalize_messages(messages)}
    if tools:
        body['tools'] = tools
        if tool_choice and tool_choice != 'auto':
            body['tool_choice'] = tool_choice
        # DeepSeek V4 Flash thinking mode rejecte tool_choice ≠ none

    # F8 — Audit souveraineté temps réel : tracer l'appel au LLM externe
    _surveiller_externe(f"{DEEPSEEK_URL}/v1/chat/completions", "llm")

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                f"{DEEPSEEK_URL}/v1/chat/completions",
                headers=headers, json=body, timeout=timeout
            )
            if r.status_code == 402:
                logging.error("[DEEPSEEK] 402 Payment Required — crédits épuisés")
                raise RuntimeError("Crédits DeepSeek épuisés")
            if r.status_code == 401:
                logging.error("[DEEPSEEK] 401 Unauthorized — clé invalide")
                raise RuntimeError("Clé DeepSeek invalide")
            if r.status_code == 429:
                logging.warning("[DEEPSEEK] 429 Rate Limited — retry")
                raise requests.exceptions.HTTPError("429 Rate Limited")
            if r.status_code >= 400:
                _body = r.text[:500]
                logging.error("[DEEPSEEK] %d — body: %s", r.status_code, _body)
            r.raise_for_status()
            return r.json()['choices'][0]
        except RuntimeError:
            raise
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                logging.warning(f"[DEEPSEEK] Tentative {attempt+1}/{max_retries} après erreur: {e}")
                time.sleep(wait)
            else:
                raise


def _ds_complete_stream(messages, model, max_tokens, tools, tool_choice, timeout):
    """Appel streaming à l'API DeepSeek. Yield des chunks."""
    model = model or DEEPSEEK_MODEL
    if not DEEPSEEK_KEY:
        yield {'type': 'error', 'content': 'DEEPSEEK_API_KEY non configurée'}
        return

    headers = {
        'Authorization': f'Bearer {DEEPSEEK_KEY}',
        'Content-Type': 'application/json'
    }
    body = {
        'model': model, 'max_tokens': max_tokens,
        'messages': _normalize_messages(messages), 'stream': True
    }
    if tools:
        body['tools'] = tools
        if tool_choice and tool_choice != 'auto':
            body['tool_choice'] = tool_choice
        # DeepSeek V4 Flash thinking mode rejecte tool_choice ≠ none

    # F8 — Audit souveraineté temps réel : tracer l'appel au LLM externe
    _surveiller_externe(f"{DEEPSEEK_URL}/v1/chat/completions", "llm")

    print(f"[DS ROUTER] DeepSeek: model={model} tools={len(tools) if tools else 0}", flush=True)

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(
                f"{DEEPSEEK_URL}/v1/chat/completions",
                headers=headers, json=body,
                timeout=timeout, stream=True
            )
            if r.status_code == 402:
                yield {'type': 'error', 'content': 'Crédits DeepSeek épuisés'}
                return
            if r.status_code == 401:
                yield {'type': 'error', 'content': 'Clé DeepSeek invalide'}
                return
            if r.status_code == 429:
                logging.warning("[DEEPSEEK] 429 Rate Limited — retry stream")
                raise requests.exceptions.HTTPError("429 Rate Limited")
            if r.status_code >= 400:
                _body = r.text[:500]
                logging.error("[DEEPSEEK STREAM] %d — body: %s", r.status_code, _body)
            r.raise_for_status()

            content = ""
            tool_calls = {}
            reasoning = ""
            for line in r.iter_lines():
                if not line:
                    continue
                line = line.decode('utf-8').strip()
                if not line.startswith('data: '):
                    continue
                data = line[6:].strip()
                if data == '[DONE]':
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    logging.warning("[DEEPSEEK] JSON decode error in stream chunk, skipping: %s", data[:100])
                    continue
                choices = chunk.get('choices', [])
                if not choices:
                    continue
                delta = choices[0].get('delta', {})
                finish = choices[0].get('finish_reason')
                if delta.get('reasoning_content'):
                    reasoning += delta['reasoning_content']
                    yield {'type': 'reasoning', 'content': delta['reasoning_content']}
                if delta.get('content'):
                    content += delta['content']
                    yield {'type': 'content', 'content': delta['content']}
                if 'tool_calls' in delta:
                    for tc in delta['tool_calls']:
                        idx = tc.get('index', 0)
                        if idx not in tool_calls:
                            tool_calls[idx] = {
                                'id': '', 'function': {'name': '', 'arguments': ''}
                            }
                        if tc.get('id'):
                            tool_calls[idx]['id'] += tc['id']
                        if tc.get('function', {}).get('name'):
                            tool_calls[idx]['function']['name'] += tc['function']['name']
                        if tc.get('function', {}).get('arguments'):
                            tool_calls[idx]['function']['arguments'] += tc['function']['arguments']
                if finish:
                    result = {
                        'type': 'complete', 'content': content,
                        'finish_reason': finish
                    }
                    if reasoning:
                        result['reasoning_content'] = reasoning
                    if tool_calls:
                        result['tool_calls'] = [
                            {'id': v['id'], 'type': 'function',
                             'function': {'name': v['function']['name'],
                                          'arguments': v['function']['arguments']}}
                            for v in tool_calls.values()
                        ]
                    yield result
                    return
            yield {'type': 'complete', 'content': content, 'finish_reason': 'stop'}
            return
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                logging.warning(f"[DEEPSEEK] Tentative {attempt+1}/{max_retries} après erreur: {e}")
                time.sleep(wait)
            else:
                yield {'type': 'error', 'content': f'DeepSeek inaccessible: {e}'}
                return


# ── Interface publique ────────────────────────────────────────────────────

def complete(messages, model=None, max_tokens=32000,
             tools=None, tool_choice='auto',
             provider='deepseek', timeout=120):
    """Appel LLM synchrone. Fallback inter-provider si DeepSeek échoue."""
    try:
        return _ds_complete(messages, model, max_tokens, tools, tool_choice, timeout)
    except (RuntimeError, requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError) as e:
        logging.warning(f"[FALLBACK] DeepSeek Flash/Main échoué ({e}), fallback chaîne...")
        try:
            from core.provider import complete as provider_complete
            return provider_complete(messages, model=model, max_tokens=max_tokens,
                                      tools=tools, tool_choice=tool_choice, timeout=timeout)
        except Exception as pe:
            logging.error(f"[FALLBACK] Fallback complet échoué: {pe}")
            raise RuntimeError(f"DeepSeek + fallbacks indisponibles: {e}; {pe}") from e


def complete_stream(messages, model=None, max_tokens=32000,
                    tools=None, tool_choice='auto',
                    provider='deepseek', timeout=120):
    """Appel LLM streaming. Fallback inter-provider si DeepSeek échoue."""
    tried_pro = False
    current_model = model or DEEPSEEK_MODEL
    generator = _ds_complete_stream(messages, current_model, max_tokens, tools, tool_choice, timeout)

    last_yield = None
    for chunk in generator:
        last_yield = chunk
        if chunk.get('type') == 'error' and not tried_pro:
            # DeepSeek a échoué → fallback chaîne inter-provider
            tried_pro = True
            current_model = model or DEEPSEEK_MODEL
            logging.warning(f"[FALLBACK] Stream DeepSeek échoué ({chunk.get('content')}), fallback chaîne...")
            try:
                from core.provider import complete_stream as provider_stream
                gen = provider_stream(messages, model=model, max_tokens=max_tokens,
                                       tools=tools, tool_choice=tool_choice, timeout=timeout)
                yielded = False
                for chunk2 in gen:
                    yielded = True
                    yield chunk2
                if not yielded:
                    yield {'type': 'error', 'content': 'DeepSeek + fallbacks: tous les providers ont échoué'}
            except Exception as pe:
                logging.error(f"[FALLBACK] Stream fallback échoué: {pe}")
                yield {'type': 'error', 'content': f'DeepSeek + fallbacks: {pe}'}
            return
        yield chunk


def ask(prompt, system=None, model=None, max_tokens=500, timeout=30):
    """Helper simple pour une completion one-shot.
    Accepte prompt en string ou messages en liste (compatibilité)."""
    if isinstance(prompt, list):
        messages = prompt
    else:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
    choice = _ds_complete(messages, model, max_tokens, tools=None, tool_choice=None, timeout=timeout)
    return choice['message']['content']
