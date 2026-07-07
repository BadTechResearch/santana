#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deepseek_client.py — Wrapper léger (anciennement client LLM complet).

Ré-exporte depuis core/provider.py, qui gère la chaîne complète :
DeepSeek → OpenRouter → Groq avec fallback automatique.

Conserve l'API publique historique pour compatibilité :
  - complete(), complete_stream(), ask()
  - DEEPSEEK_MODEL, DEEPSEEK_KEY, DEEPSEEK_URL
"""

import os
from core.provider import complete as _provider_complete
from core.provider import complete_stream as _provider_stream

# ── Constantes (conservées pour compatibilité) ────────────────
DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash').strip()
DEEPSEEK_PRO_MODEL = os.getenv('DEEPSEEK_PRO_MODEL', 'deepseek-v4-pro').strip()
DEEPSEEK_KEY = os.getenv('DEEPSEEK_API_KEY', '').strip()


def complete(messages, model=None, max_tokens=32000,
             tools=None, tool_choice='auto',
             provider='deepseek', timeout=120):
    """Appel LLM synchrone (délègue à core.provider)."""
    return _provider_complete(
        messages, model=model, max_tokens=max_tokens,
        tools=tools, tool_choice=tool_choice, timeout=timeout,
    )


def complete_stream(messages, model=None, max_tokens=32000,
                    tools=None, tool_choice='auto',
                    provider='deepseek', timeout=120):
    """Appel LLM streaming (délègue à core.provider)."""
    yield from _provider_stream(
        messages, model=model, max_tokens=max_tokens,
        tools=tools, tool_choice=tool_choice, timeout=timeout,
    )


def ask(prompt, system=None, model=None, max_tokens=500, timeout=30):
    """Helper simple pour une completion one-shot (délègue à core.provider)."""
    if isinstance(prompt, list):
        messages = prompt
    else:
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
    result = _provider_complete(
        messages, model=model, max_tokens=max_tokens,
        tools=None, tool_choice=None, timeout=timeout,
    )
    return result["message"]["content"]
