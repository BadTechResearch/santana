#!/usr/bin/env python3
"""Deep debug: test _init_providers step by step."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.utils import load_env
load_env('.env')

# Import provider module but force reload
import importlib
import core.provider
importlib.reload(core.provider)

# Monkey-patch to see what happens
original_init = core.provider._init_providers

def debug_init():
    global PROVIDER_CHAIN
    PROVIDER_CHAIN = core.provider.PROVIDER_CHAIN
    PROVIDER_CHAIN.clear()
    env = core.provider._get_env()
    print(f"[DEBUG _init] env keys: {list(env.keys())}")
    print(f"[DEBUG _init] deepseek_key repr: {repr(env.get('deepseek_key', ''))}")
    print(f"[DEBUG _init] deepseek_key bool: {bool(env.get('deepseek_key', ''))}")
    
    if env.get("deepseek_key"):
        print("[DEBUG _init] CONDITION PASSED for deepseek")
        PROVIDER_CHAIN.append({"name": "deepseek"})
    else:
        print("[DEBUG _init] CONDITION FAILED for deepseek")
        
    if env.get("groq_key"):
        print("[DEBUG _init] CONDITION PASSED for groq")
        PROVIDER_CHAIN.append({"name": "groq"})
    else:
        print("[DEBUG _init] CONDITION FAILED for groq")

core.provider._init_providers = debug_init
core.provider._init_providers()
print(f"Final PROVIDER_CHAIN: {[p['name'] for p in core.provider.PROVIDER_CHAIN]}")
