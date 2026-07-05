#!/usr/bin/env python3
"""
validate_prompt.py — Validation du prompt système de Santana

Vérifie que :
1. build_system_prompt() s'exécute sans erreur
2. Les fichiers soul (RULES.md, STYLE.md) sont chargés
3. Les règles critiques sont présentes
4. Aucune contradiction évidente
5. La mémoire vivante est injectée

Usage : python3 scripts/validate_prompt.py
Retourne 0 si OK, 1 si problème
"""

import os
import sys
import logging
import traceback

# Supprimer les logs pendant la validation
logging.disable(logging.CRITICAL)

BASE_DIR = os.path.expanduser("~/santana")
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

# Forcer la clé API pour les tests
os.environ.setdefault("DEEPSEEK_API_KEY", "test_key_for_validation")

ERRORS = []
WARNINGS = []

def err(msg):
    ERRORS.append(msg)
    print(f"  ❌ {msg}")

def warn(msg):
    WARNINGS.append(msg)
    print(f"  ⚠️  {msg}")

def ok(msg):
    print(f"  ✅ {msg}")

print("📝 Validation du prompt système Santana")
print("")

# ── 1. Vérifier que les fichiers soul existent ──────────────────────────────
print("1. Fichiers soul :")
soul_files = {
    "soul/SOUL.md": "Identité de Santana",
    "soul/RULES.md": "Règles de comportement",
    "soul/STYLE.md": "Style d'écriture",
    "soul/USER.md": "Profil Serge",
}
all_ok = True
for sf, desc in soul_files.items():
    if os.path.exists(sf):
        size = os.path.getsize(sf)
        if size < 50:
            warn(f"{sf} ({desc}) — fichier trop petit ({size} bytes)")
        else:
            ok(f"{sf} ({desc}) — {size} bytes")
    else:
        err(f"{sf} ({desc}) — FICHIER MANQUANT")
        all_ok = False

if not all_ok:
    print("  ❌ Fichiers soul manquants — arrêt")
    sys.exit(1)

# ── 2. Tenter de construire le prompt ───────────────────────────────────────
print("")
print("2. Construction du prompt :")
try:
    from agent.orchestrator import build_system_prompt, load_soul_file
    prompt = build_system_prompt(user_message="Test de validation")
    ok(f"build_system_prompt() exécutée — {len(prompt)} chars")
except Exception as e:
    err(f"build_system_prompt() a échoué : {e}")
    traceback.print_exc()
    sys.exit(1)

# ── 3. Vérifier la présence des règles ──────────────────────────────────────
print("")
print("3. Règles critiques dans le prompt :")
rules_check = [
    ("### 1.", "Règle 1 — Challenge Serge"),
    ("### 2.", "Règle 2 — Honnêteté"),
    ("### 3.", "Règle 3 — Sources"),
    ("Bonjour", "Salutation"),
    ("je ne sais pas", "Honnêteté intellectuelle"),
    ("agent Black Intelligence", "Vocabulaire Black Intelligence"),
    ("Atlas", "Mémoire Atlas"),
    ("DeepSeek", "Provider LLM"),
]
all_found = True
for rtext, rdesc in rules_check:
    if rtext.lower() in prompt.lower():
        ok(f"{rdesc} ('{rtext}')")
    else:
        warn(f"{rdesc} ('{rtext}') — INTROUVABLE")
        all_found = False

# ── 4. Vérifier les contradictions ──────────────────────────────────────────
print("")
print("4. Contradictions :")
contradictions = [
    ("ne réponds pas", "réponds toujours"),
    ("ne cite pas", "cite"),
    ("ne donne pas", "donne"),
]
found_any = False
for a, b in contradictions:
    if a.lower() in prompt.lower() and b.lower() in prompt.lower():
        warn(f"Contradiction possible : '{a}' ET '{b}' présents")
        found_any = True
if not found_any:
    ok("Aucune contradiction évidente détectée")

# ── 5. Vérifier l'injection mémoire ─────────────────────────────────────────
print("")
print("5. Injection mémoire vivante :")
if "Contexte récent" in prompt or "Mémoire" in prompt or "mémoire" in prompt:
    ok("Section mémoire présente dans le prompt")
else:
    warn("Aucune section mémoire détectée")

# ── 6. Vérifier la mémoire Atlas (si accessible) ────────────────────────────
print("")
print("6. Mémoire Atlas :")
try:
    from atlas_engine.atlas import learn
    ok("Module Atlas accessible (learn)")
except Exception as e:
    warn(f"Module Atlas non accessible : {e}")

# ── Rapport final ───────────────────────────────────────────────────────────
print("")
print("═" * 50)
if ERRORS:
    print(f"❌ ÉCHEC — {len(ERRORS)} erreur(s), {len(WARNINGS)} avertissement(s)")
    for e in ERRORS:
        print(f"   • {e}")
    sys.exit(1)
elif WARNINGS:
    print(f"⚠️  VALIDE — {len(WARNINGS)} avertissement(s) à vérifier")
    for w in WARNINGS:
        print(f"   • {w}")
    sys.exit(0)
else:
    print(f"✅ VALIDE — Aucun problème détecté")
    sys.exit(0)
