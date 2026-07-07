#!/usr/bin/env python3
"""Test de la chaîne de providers après modifications."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Nettoyer les caches .pyc
base = os.path.dirname(os.path.abspath(__file__))
for root, dirs, files in os.walk(base):
    for f in files:
        if f.endswith('.pyc') and '__pycache__' in root:
            os.remove(os.path.join(root, f))

from core.utils import load_env
load_env('.env')

from core.provider import _get_env, PROVIDER_CHAIN, _init_providers

print("=== 1. Test _get_env() ===")
env = _get_env()
print(f"Keys: {list(env.keys())}")
print(f"deepseek_key: {bool(env.get('deepseek_key'))} (len={len(env.get('deepseek_key', ''))})")
print(f"groq_key: {bool(env.get('groq_key'))} (len={len(env.get('groq_key', ''))})")

print("\n=== 2. Test _init_providers() ===")
_init_providers()
print(f"PROVIDER_CHAIN: {[p['name'] for p in PROVIDER_CHAIN]}")
for p in PROVIDER_CHAIN:
    print(f"  {p['name']}: model={p['model']}, key_len={len(p['key'])}")

print("\n=== 3. Test import santana.py sanity ===")
# Vérifier que santana.py peut importer correctement
from core.utils import load_env as load_env2
print("load_env disponible dans santana.py scope: OK")
