"""
fts_search.py — Recherche plein texte dans l'historique des conversations.

Utilise FTS5 (Full-Text Search v5) intégré à SQLite.
Table de contenu externe liée à session_buffer : 0 duplication, index seulement.

Usage :
    from tools.fts_search import fts_memory_search, init_fts
    results = fts_memory_search("bug mémoire reset")
"""

import json
import logging
from core.db import get_db

logger = logging.getLogger(__name__)

# ─── Initialisation FTS5 ────────────────────────────────────────────────

_FTS_INITIALIZED = False


def init_fts():
    """Crée la table virtuelle FTS5 pointant sur session_buffer (1 seule fois)."""
    global _FTS_INITIALIZED
    if _FTS_INITIALIZED:
        return
    try:
        conn = get_db()
        c = conn.cursor()

        # Table FTS5 en mode content= (externe : pas de copie des données)
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(
                content,
                session_id UNINDEXED,
                role UNINDEXED,
                content=session_buffer,
                content_rowid=id,
                tokenize='porter unicode61'
            )
        """)
        conn.commit()

        # Compter les lignes indexées
        indexed = c.execute("SELECT COUNT(*) FROM session_fts").fetchone()[0]
        total = c.execute("SELECT COUNT(*) FROM session_buffer").fetchone()[0]

        # Auto-rebuild si l'index externe est vide
        if indexed == 0 and total > 0:
            rebuild_fts()
            indexed = c.execute("SELECT COUNT(*) FROM session_fts").fetchone()[0]

        logger.info("[FTS] Initialisé : %d/%d messages indexés", indexed, total)
        _FTS_INITIALIZED = True
    except Exception as e:
        logger.error("[FTS] Init failure: %s", e)


def rebuild_fts():
    """Rebuild complet de l'index FTS5 (après restoration de backup, etc.)."""
    try:
        conn = get_db()
        conn.execute("INSERT INTO session_fts(session_fts) VALUES('rebuild')")
        conn.commit()
        indexed = conn.execute("SELECT COUNT(*) FROM session_fts").fetchone()[0]
        logger.info("[FTS] Rebuild terminé : %d messages indexés", indexed)
        return indexed
    except Exception as e:
        logger.error("[FTS] Rebuild failure: %s", e)
        return 0


# ─── Outil de recherche ─────────────────────────────────────────────────

def fts_memory_search(query: str, limit: int = 5) -> str:
    """Recherche plein texte dans tout l'historique des conversations.

    Args:
        query: Mots-clés, phrases exactes ("entre guillemets"), ou booléens
        limit: Nombre max de résultats (défaut: 5, max: 20)

    Returns:
        Texte formaté des résultats avec session, rôle, contenu tronqué
    """
    init_fts()

    if not query or not query.strip():
        return "❌ Requête vide."

    limit = min(max(limit, 1), 20)

    try:
        conn = get_db()
        c = conn.cursor()

        # FTS5 requête — on joint sur session_buffer pour récupérer les métadonnées
        c.execute("""
            SELECT sb.session_id, sb.role, substr(sb.content, 1, 500), sb.timestamp
            FROM session_fts f
            JOIN session_buffer sb ON f.rowid = sb.id
            WHERE session_fts MATCH ?
            ORDER BY sb.id DESC
            LIMIT ?
        """, (query, limit))

        rows = c.fetchall()

        if not rows:
            return f"🔍 Aucun résultat pour : « {query} »"

        results = [f"🔍 **{len(rows)} résultat(s)** pour : « {query} »\n"]
        for i, (session_id, role, content, timestamp) in enumerate(rows, 1):
            who = "👤 Serge" if role == "user" else "🤖 Santana"
            date = (timestamp or "?").split(".")[0]  # nettoie microsecondes
            results.append(
                f"**{i}.** [{session_id}] {who} · {date}\n"
                f"   > {content}\n"
            )

        return "\n".join(results)

    except Exception as e:
        logger.error("[FTS] Search error: %s", e)
        # Tentative de rebuild si l'index semble vide
        try:
            _c = get_db()
            count = _c.execute("SELECT COUNT(*) FROM session_fts").fetchone()[0]
            if count == 0:
                rebuild_fts()
                return f"⚠️ Index FTS vide, rebuild effectué. Relance ta recherche."
        except Exception:
            pass
        return f"❌ Erreur recherche : {str(e)}"
