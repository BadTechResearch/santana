"""Délégation de sous-agents pour Santana.
Permet de spawner des tâches parallèles isolées avec leur propre contexte.
Pattern inspiré de Hermès Agent (delegate_task).

Chaque sous-agent reçoit un contexte réduit, exécute sa tâche,
et retourne un résultat consolidé.
"""

import json
import logging
import time
import uuid

logger = logging.getLogger(__name__)


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
