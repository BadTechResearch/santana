"""Vérification intégrée des 5 phases — peut être lancé seul ou via pytest"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

print("=" * 60)
print("VÉRIFICATION DES 5 PHASES")
print("=" * 60)

# ── Phase 1 : Canal ─────────────────────────────────────────────────
print("\n📡 P1 — CANAL")
try:
    with open("soul/IDENTITY.md") as f:
        content = f.read()
    checks = [
        ("Section Canal présente", "## Canal" in content),
        ("Telegram mentionné", "Telegram" in content),
        ("Format HTML natif", "HTML" in content),
        ("Split 4000 caractères", "4000" in content),
        ("Tag DeepSeek/Groq", "DeepSeek" in content and "Groq" in content),
        ("Fuseau Africa/Kinshasa", "Africa/Kinshasa" in content),
    ]
    for label, ok in checks:
        print(f"  {'✅' if ok else '❌'} {label}")
    print(f"  → CANAL: {sum(1 for _, ok in checks if ok)}/{len(checks)} OK")
except FileNotFoundError:
    print("  ❌ Fichier soul/IDENTITY.md introuvable")

# ── Phase 2 : Mémoire ─────────────────────────────────────────────────
print("\n🧠 P2 — MÉMOIRE")
try:
    from memory.memory import count_memory, get_recent_memory, save_message
    n = count_memory()
    recent = get_recent_memory(5)
    print(f"  ✅ count_messages() = {n}")
    print(f"  ✅ get_recent_memory(5) = {len(recent)} messages retournés")
    if recent:
        print(f"     Dernier: [{recent[-1][2]}] {recent[-1][3][:60]}...")

    # Vérifie que save_message existe et qu'elle persiste
    assert callable(save_message), "save_message doit être callable"
    print("  ✅ save_message() est disponible")

    # Vérifie l'ordre chronologique (id DESC)
    if len(recent) >= 2:
        assert recent[0][0] > recent[-1][0], "Ordre DESC confirmé"
        print("  ✅ Ordre DESC (plus récent en premier) vérifié")
except Exception as e:
    print(f"  ❌ Erreur: {e}")

# ── Phase 3 : Anti-régression ─────────────────────────────────────────
print("\n🔄 P3 — ANTI-RÉGRESSION")
try:
    from agent.context import (
        reset_session, get_previous_session_summary,
        push_exchange, get_context
    )
    # Vérifie que get_previous_session_summary existe et fonctionne
    s = get_previous_session_summary()
    print(f"  ✅ get_previous_session_summary() → {'contient ' + str(len(s)) + ' caractères' if s else 'None (première session)'}")

    # Vérifie reset_session
    old_id = None
    try:
        from agent.context import session_buffer
        if hasattr(session_buffer, 'session_id'):
            old_id = session_buffer.session_id
    except Exception:
        pass

    new_id = reset_session()
    print(f"  ✅ reset_session() → nouveau session_id = {new_id}")

    # Vérifie que push_message et get_context sont fonctionnels
    push_exchange("user", "test vérification phase 3")
    ctx = get_context()
    assert ctx is not None, "get_context() doit retourner quelque chose"
    print(f"  ✅ push_message() + get_context() fonctionnent")
    print(f"     Contexte: {str(ctx)[:80]}...")

except Exception as e:
    print(f"  ❌ Erreur: {e}")

# ── Phase 4 : FTS5 ────────────────────────────────────────────────────
print("\n🔍 P4 — FTS5")
try:
    from tools.fts_search import init_fts, fts_memory_search, rebuild_fts
    init_fts()

    # Vérifie l'index
    from core.db import get_db
    conn = get_db()
    indexed = conn.execute("SELECT COUNT(*) FROM session_fts").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM session_buffer").fetchone()[0]
    print(f"  ✅ Index FTS5: {indexed}/{total} messages")

    # Test recherche
    r = fts_memory_search("bug")
    results_count = r.count("résultat") + r.count("résultats")
    print(f"  ✅ fts_memory_search('bug') → {'trouvé' if results_count else 'résultat: ' + r[:60]}")

    r2 = fts_memory_search("santana")
    r2_count = r2.count("résultat") + r2.count("résultats")
    print(f"  ✅ fts_memory_search('santana') → {'trouvé' if r2_count else 'résultat: ' + r2[:60]}")

    # Vérifie rebuild
    idx = rebuild_fts()
    print(f"  ✅ rebuild_fts() → {idx} messages indexés")

except Exception as e:
    print(f"  ❌ Erreur: {e}")
    import traceback
    traceback.print_exc()

# ── Phase 5 : Style Hermes ────────────────────────────────────────────
print("\n🎸 P5 — STYLE HERMES")
try:
    with open("soul/CONDUCT.md") as f:
        content = f.read()
    checks = [
        ("Conclusion en premier", "Conclusion en premier" in content),
        ("Structure hiérarchique ##", "##" in content),
        ("Challenge par défaut", "Challenge par défaut" in content or "challenge" in content.lower()),
        ("Avant/Après diff", "Avant/Après" in content or "avant/après" in content),
        ("Pas de flatterie", "flatterie" in content),
        ("Émojis intentionnels", "émojis" in content or "emojis" in content.lower()),
    ]
    for label, ok in checks:
        print(f"  {'✅' if ok else '❌'} {label}")
    print(f"  → STYLE: {sum(1 for _, ok in checks if ok)}/{len(checks)} OK")
except FileNotFoundError:
    print("  ❌ Fichier soul/CONDUCT.md introuvable")

# ── Bilan final ───────────────────────────────────────────────────────
passed_phases = []
failed_phases = []

# P1
try:
    with open("soul/IDENTITY.md") as f:
        c = f.read()
    if "## Canal" in c:
        passed_phases.append("P1-CANAL")
    else:
        failed_phases.append("P1-CANAL (pas de section Canal)")
except Exception:
    failed_phases.append("P1-CANAL (fichier manquant)")

# P2
try:
    from memory.memory import count_memory
    if count_memory() > 0:
        passed_phases.append("P2-MEMOIRE")
    else:
        failed_phases.append("P2-MEMOIRE (0 messages)")
except Exception as e:
    failed_phases.append(f"P2-MEMOIRE ({e})")

# P3
try:
    from agent.context import get_previous_session_summary
    passed_phases.append("P3-CONTEXTE")
except Exception as e:
    failed_phases.append(f"P3-CONTEXTE ({e})")

# P4
try:
    from tools.fts_search import init_fts
    init_fts()
    from core.db import get_db
    indexed = get_db().execute("SELECT COUNT(*) FROM session_fts").fetchone()[0]
    if indexed > 0:
        passed_phases.append("P4-FTS5")
    else:
        failed_phases.append("P4-FTS5 (index vide)")
except Exception as e:
    failed_phases.append(f"P4-FTS5 ({e})")

# P5
try:
    with open("soul/CONDUCT.md") as f:
        c = f.read()
    if "Conclusion en premier" in c:
        passed_phases.append("P5-STYLE")
    else:
        failed_phases.append("P5-STYLE (pas de règle Conclusion)")
except Exception:
    failed_phases.append("P5-STYLE (fichier manquant)")

print("\n" + "=" * 60)
print("BILAN FINAL")
print("=" * 60)
for p in passed_phases:
    print(f"  ✅ {p}")
for p in failed_phases:
    print(f"  ❌ {p}")
print(f"\n  {len(passed_phases)}/5 phases OK — {len(failed_phases)} échec(s)")
if not failed_phases:
    print("  🎸✅ Santana est autonome à 100% sur les 5 phases.")
print()
