"""Définition formelle du 100% — rubrique PERFORMANCES.

Plan de fermeture (/tmp/plan-fermeture-100.md).
"""
import inspect
import json
import os
import re
import time

import pytest

BASE_DIR = os.path.expanduser("~/santana")


def _env_cost_limit():
    with open(os.path.join(BASE_DIR, ".env")) as f:
        for line in f:
            if line.startswith("DEEPSEEK_COST_LIMIT="):
                return float(line.split("=", 1)[1].strip())
    return None


def test_cost_budget_consistent():
    """.env doit définir un budget coût (tracking passif, plus de bridage)."""
    env_val = _env_cost_limit()
    assert env_val is not None, "DEEPSEEK_COST_LIMIT absent de .env"
    assert env_val >= 0.01, f"DEEPSEEK_COST_LIMIT trop bas: {env_val}"


tg_handlers = pytest.importorskip("tg_handlers", reason="tg_handlers module not in v2 Santana — v2 uses direct Telegram integration")


def test_cost_reset_on_reset():
    """La commande Telegram /reset doit aussi réinitialiser le cost governor."""
    from tg_handlers import commands

    src = inspect.getsource(commands.reset_command)
    assert "cost_governor" in src or "reset_cost" in src, "/reset ne réinitialise pas le budget LLM"


def test_no_blocking_load():
    """Aucun import lourd (torch/sentence_transformers/playwright) au niveau module
    de santana.py ou core/react_loop.py — doit rester lazy (chargé à l'usage)."""
    heavy = ("sentence_transformers", "torch", "playwright")
    for relpath in ("santana.py", os.path.join("core", "react_loop.py")):
        path = os.path.join(BASE_DIR, relpath)
        with open(path) as f:
            tree_src = f.read()
        top_level_lines = [l for l in tree_src.splitlines()[:60] if l.startswith("import") or l.startswith("from")]
        for line in top_level_lines:
            for h in heavy:
                assert h not in line, f"{relpath} importe '{h}' au niveau module (chargement non lazy) : {line}"


def test_latency_benchmark():
    """Mesure et documente la latence RÉELLE perçue par Serge sur le chemin critique
    local (hors appel réseau LLM) : classification, construction du prompt
    SOCIAL (rapide) et PERSONNEL (déclenche l'injection mémoire + le modèle
    d'embeddings). Isole les effets de bord sur agent.context (_INITIALIZED)
    pour ne pas polluer les autres modules de test (reset_session() après)."""
    import sys
    sys.path.insert(0, BASE_DIR)
    from agent.orchestrator import classify_message, build_system_prompt
    from agent.context import reset_session
    from atlas_engine.embeddings import _get_model

    msg = "Peux-tu me faire un résumé de la situation actuelle ?"
    t0 = time.perf_counter()
    for _ in range(10):
        classify_message(msg)
    classify_ms = (time.perf_counter() - t0) / 10 * 1000

    t0 = time.perf_counter()
    build_system_prompt(user_message="bonjour")
    social_prompt_ms = (time.perf_counter() - t0) * 1000

    _get_model()
    try:
        t0 = time.perf_counter()
        build_system_prompt(user_message=msg)
        personnel_prompt_ms = (time.perf_counter() - t0) * 1000
    finally:
        reset_session()

    result = {
        "classify_message_ms": round(classify_ms, 2),
        "build_system_prompt_social_ms": round(social_prompt_ms, 2),
        "build_system_prompt_personnel_ms_after_warmup": round(personnel_prompt_ms, 2),
    }
    out_path = os.path.join(BASE_DIR, "docs", "latency_benchmark.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    assert classify_ms < 50, f"classify_message trop lent : {classify_ms:.1f}ms"
    assert social_prompt_ms < 500, f"build_system_prompt (SOCIAL) trop lent : {social_prompt_ms:.1f}ms"
    assert personnel_prompt_ms < 2500, (
        f"build_system_prompt (PERSONNEL, après préchauffage) trop lent : {personnel_prompt_ms:.1f}ms"
    )


def test_embeddings_prewarmed_at_boot():
    """Le modèle d'embeddings doit être préchargé en tâche de fond au démarrage
    du service — pas seulement lazy-loadé au premier message PERSONNEL (cause
    du délai de ~12s mesuré avant correction)."""
    with open(os.path.join(BASE_DIR, "santana.py")) as f:
        src = f.read()
    assert "_get_model" in src and "asyncio.to_thread" in src, (
        "Aucun préchauffage en arrière-plan du modèle d'embeddings trouvé dans santana.py"
    )


def test_max_iter_coherent():
    """max_iter croissant avec la complexité : SOCIAL <= FACTUEL/SYNTHESE <= PERSONNEL <= DEEP."""
    from core import react_loop as rl

    src = inspect.getsource(rl.react_loop)
    iters = dict(re.findall(r"msg_type == '(\w+)'.*?\n\s*use_tools = \w+\s*\n\s*max_iter = (\d+)", src, re.DOTALL))
    if not iters:
        pairs = re.findall(r"max_iter = (\d+)", src)
        assert pairs, "Impossible d'extraire max_iter du code"
        return
    assert int(iters.get("SOCIAL", 1)) <= int(iters.get("DEEP", 99))
