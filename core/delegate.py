"""Délégation de sous-agents pour Santana.
Permet de spawner des tâches parallèles isolées avec leur propre contexte.
Pattern inspiré de Hermès Agent (delegate_task).

Chaque sous-agent reçoit un contexte réduit, exécute sa tâche,
et retourne un résultat consolidé.
"""

import json
import logging
import threading
import time
import uuid

logger = logging.getLogger(__name__)

# Verrou pour le swap de SESSION_ID : évite que deux appels concurrents
# à delegate_task() corrompent le session_id du parent. Même si le code
# n'est pas encore dans _PARALLEL_TOOLS, ce verrou prévient le pattern
# de race condition identifié dans l'audit juillet 2026.
_session_lock = threading.Lock()


async def delegate_task(goal: str, context: str = "") -> str:
    """Délègue une tâche à un sous-agent isolé.

    Le sous-agent exécute react_loop avec un contexte réduit,
    en parallèle de la conversation principale.

    Args:
        goal: L'objectif précis de la tâche déléguée
        context: Contexte additionnel (fichiers, infos, contraintes)

    Returns:
        Résultat textuel de la tâche
    """
    task_id = str(uuid.uuid4())[:8]
    logger.info(f"[DELEGATE] Tâche {task_id}: {goal[:80]}...")
    start = time.time()

    import agent.context as _ctx

    # Isolation de session : sans ça, react_loop() du sous-agent écrit dans
    # le MÊME session_buffer que la conversation principale (agent/context.py
    # expose SESSION_ID comme un global de module, pas par-appel) — le prompt
    # synthétique "[TÂCHE DÉLÉGUÉE ...]" polluerait le contexte que Serge voit.
    # On bascule sur un SESSION_ID temporaire pour la durée de la délégation,
    # puis on restaure celui du parent — sûr ici car delegate_task n'est pas
    # dans _PARALLEL_TOOLS (pas d'exécution concurrente avec le thread appelant
    # pendant que ce swap est actif).
    _parent_session_id = _ctx.SESSION_ID
    with _session_lock:
        _ctx.SESSION_ID = f"delegate-{task_id}-{uuid.uuid4()}"

    try:
        # Construire un message pour la sous-boucle
        prompt = f"[TÂCHE DÉLÉGUÉE {task_id}]\n"
        if context:
            prompt += f"Contexte: {context}\n\n"
        prompt += f"Objectif: {goal}\n\n"
        prompt += "Réponds UNIQUEMENT sur cette tâche. Sois concis et direct."

        # Exécuter dans un thread avec sa propre boucle react_loop
        from core.react_loop import react_loop

        # Désactiver le streaming pour les sous-agents
        response = await react_loop(prompt, stream_callback=None)

        elapsed = time.time() - start
        logger.info(f"[DELEGATE] Tâche {task_id} terminée ({elapsed:.1f}s, {len(response)} chars)")
        return response

    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"[DELEGATE] Tâche {task_id} échouée ({elapsed:.1f}s): {e}")
        return json.dumps({"task_id": task_id, "error": str(e), "duration_s": round(elapsed, 1)})
    finally:
        with _session_lock:
            _ctx.SESSION_ID = _parent_session_id
