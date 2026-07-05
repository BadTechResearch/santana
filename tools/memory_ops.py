"""Outils mémoire de Santana (memory_query, atlas)."""

import os
import logging

from core.db import get_db
from core.utils import get_base_dir

BASE_DIR = get_base_dir()

_TZ = None
try:
    import pytz
    _TZ = pytz.timezone("Europe/Brussels")
except Exception as e:
    logging.error("[MEMORY_OPS] pytz fallback: %s", e)

# Atlas
_ATLAS_OK = True
try:
    from atlas_engine.atlas import learn as _atlas_learn
except Exception as _ae:
    _ATLAS_OK = False
    logging.error(f"[ATLAS] Atlas import failure: {_ae}")


def tool_memory_query(query: str) -> str:
    """Recherche dans la mémoire vectorielle (livres) + conversation."""
    try:
        return _tool_memory_query(query)
    except Exception as e:
        logging.error(f"[MEMORY_OPS] memory_query error: {e}")
        return "Outil temporairement indisponible"


def _tool_memory_query(query: str) -> str:
    try:
        from atlas_engine.embeddings import search as livres_search, rebuild_if_needed
        rebuild_if_needed()
        livres_results = livres_search(query)
        livres_text = ""
        if livres_results:
            parts = []
            for result in livres_results:
                if len(result) == 4:
                    fname, score, section, extrait = result
                else:
                    fname, score, extrait = result[0], result[1], result[2]
                    section = ""
                header = f"[{fname}]"
                if section:
                    header += f" → {section}"
                header += f" (pertinence: {score:.0%})"
                parts.append(header)
                parts.append(extrait[:400])
            livres_text = "\n\n".join(parts)

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT role, content, timestamp FROM memory WHERE content LIKE ? ORDER BY timestamp DESC LIMIT 10",
            (f"%{query}%",),
        )
        rows = c.fetchall()

        memory_text = ""
        if rows:
            memory_text = "\n".join(
                f"[{ts}] {role}: {content[:400]}" for role, content, ts in rows
            )

        if not livres_text and not memory_text:
            return f"Aucun souvenir trouve sur: {query}"

        output = []
        if livres_text:
            output.append("=== Livres ===")
            output.append(livres_text)
        if memory_text:
            output.append("=== Memoire conversation ===")
            output.append(memory_text)
        return "\n\n".join(output)
    except Exception as e:
        return f"Erreur memoire: {str(e)}"


def tool_atlas(context: str) -> str:
    """Analyse la conversation et decide quoi retenir via Atlas."""
    if not _ATLAS_OK:
        return "Atlas non disponible."
    try:
        parts = context.split("\n---\n", 1)
        user_msg = parts[0] if parts else context
        resp = parts[1] if len(parts) > 1 else ""
        result = _atlas_learn(user_msg, resp)
        return f"Atlas: {result} ecriture(s)" if result else "Rien a retenir"
    except Exception as e:
        logging.error(f"[MEMORY_OPS] atlas error: {e}")
        return f"Erreur Atlas: {str(e)}"
