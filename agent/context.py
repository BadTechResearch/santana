"""context.py — Gestion intelligente du contexte de session Santana.

Fonctions :
- init_session() : crée les tables de session
- push_exchange() : enregistre un échange utilisateur ↔ Santana
- get_session_buffer() : retourne le buffer de session (derniers messages)
- get_session_summary() : retourne le résumé automatique
- maybe_auto_summarize() : résumé sémantique toutes les N interactions
- get_context() : assemble le buffer + résumé + compression si nécessaire
- estimate_tokens() : estime le nombre de tokens du contexte
"""

import os
import json
import logging
from datetime import datetime

from core.db import get_db

BASE_DIR = os.path.expanduser("~/santana")

# ─── Configuration ─────────────────────────────────────────────────────

# Seuils de compression progressifs (copie du modèle Hermès)
COMPRESSION_CONFIG = {
    "buffer_max_messages": 20,       # Messages conservés dans le buffer
    "summarize_interval": 10,        # Résumé automatique toutes les N interactions
    "soft_warn_tokens": 4000,        # Alerte si le contexte dépasse 4K tokens
    "soft_trim_at": 8000,            # Compression douce si > 8K tokens estimés
    "hard_trim_at": 16000,           # Compression agressive si > 16K tokens
    "summary_max_chars": 500,        # Longueur max du résumé
    "protect_last_n": 5,             # Derniers messages protégés de la compression
}

SESSION_ID = datetime.now().strftime("%Y-%m-%d_%H")
MESSAGE_COUNTER = 0
_INITIALIZED = False


# ─── Initialisation ────────────────────────────────────────────────────

def init_session():
    """Crée les tables de session si elles n'existent pas."""
    global _INITIALIZED
    if _INITIALIZED:
        return
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS session_buffer (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_session_id ON session_buffer(session_id)''')
        c.execute('''CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            summary TEXT,
            exchange_count INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        _INITIALIZED = True
    except Exception as e:
        logging.error(f"[CONTEXT] Session init failure: {e}")


# ─── Buffer de session ────────────────────────────────────────────────

def push_exchange(role: str, content: str):
    """Ajoute un message au buffer de session.

    Args:
        role: 'user' ou 'assistant'
        content: Contenu du message
    """
    global MESSAGE_COUNTER
    init_session()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO session_buffer (session_id, role, content) VALUES (?, ?, ?)",
            (SESSION_ID, role, content[:1000])
        )
        conn.commit()

        # Garder seulement les N derniers (soft trim par défaut)
        max_messages = COMPRESSION_CONFIG["buffer_max_messages"]
        c.execute('''
            DELETE FROM session_buffer WHERE id NOT IN (
                SELECT id FROM session_buffer
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
            ) AND session_id = ?
        ''', (SESSION_ID, max_messages, SESSION_ID))
        conn.commit()
        MESSAGE_COUNTER += 1
    except Exception as e:
        logging.error(f"[CONTEXT] Push failure: {e}")


def get_session_buffer(protect_last: int = 0) -> str:
    """Retourne les messages de la session en cours.

    Args:
        protect_last: Nombre de derniers messages à protéger (ne pas résumer)

    Returns:
        Texte formaté du buffer, ou "" si vide
    """
    init_session()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT role, content FROM session_buffer WHERE session_id = ? ORDER BY id ASC",
            (SESSION_ID,)
        )
        rows = c.fetchall()
        if not rows:
            return ""
        lines = []
        for i, (role, content) in enumerate(rows):
            prefix = "👤 Serge" if role == "user" else "🤖 Santana"
            # Protéger les derniers messages de la troncature
            if protect_last and i >= len(rows) - protect_last:
                lines.append(f"{prefix}: {content}")
            else:
                lines.append(f"{prefix}: {content[:300]}")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"[CONTEXT] Buffer fetch failure: {e}")
        return ""


# ─── Résumé automatique ───────────────────────────────────────────────

def maybe_auto_summarize():
    """Toutes les N interactions : résumé sémantique via MiniLM.
    N = COMPRESSION_CONFIG['summarize_interval']
    """
    global MESSAGE_COUNTER
    interval = COMPRESSION_CONFIG["summarize_interval"]
    if MESSAGE_COUNTER < interval or MESSAGE_COUNTER % interval != 0:
        return
    try:
        buffer = get_session_buffer()
        if not buffer:
            return

        from atlas_engine.model_singleton import get_model
        model = get_model()
        lines = buffer.split("\n")
        if len(lines) < 3:
            return

        embs = model.encode(lines, normalize_embeddings=True, show_progress_bar=False)
        import numpy as np

        # Grouper par similarité
        groups = []
        used = set()
        for i in range(len(lines)):
            if i in used:
                continue
            group = [i]
            used.add(i)
            for j in range(i + 1, len(lines)):
                if j in used:
                    continue
                sim = float(embs[i] @ embs[j])
                if sim > 0.75:
                    group.append(j)
                    used.add(j)
            groups.append(group)

        # Construire le résumé
        topics = []
        for g in groups:
            topic_text = " | ".join(lines[idx][:80] for idx in g[:3])
            topics.append(topic_text[:150])

        max_chars = COMPRESSION_CONFIG["summary_max_chars"]
        summary = "Session: " + " // ".join(topics[:5])
        summary = summary[:max_chars]

        # Sauvegarder
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO session_summaries (session_id, summary, exchange_count) VALUES (?, ?, ?)",
            (SESSION_ID, summary, MESSAGE_COUNTER)
        )
        conn.commit()
        logging.info(f"[CONTEXT] Résumé auto: {len(groups)} sujets")
    except Exception as e:
        logging.error(f"[CONTEXT] Auto-summarize failure: {e}")


def get_session_summary() -> str:
    """Retourne le résumé de la session en cours."""
    init_session()
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT summary FROM session_summaries WHERE session_id = ?",
            (SESSION_ID,)
        )
        row = c.fetchone()
        return row[0] if row else ""
    except Exception as e:
        logging.error(f"[CONTEXT] Summary fetch failure: {e}")
        return ""


# ─── Estimation tokens ────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Estime le nombre de tokens. Version améliorée pour le français.

    Prend en compte la densité lexicale du français (plus de tokens par caractère).
    """
    if not text:
        return 0
    words = len(text.split())
    if words < 3:
        return max(1, len(text) // 3)
    # Français : ~1 token pour 0.75 mot (vs ~1 pour 1.3 mot en anglais)
    return max(1, int(words / 0.75))


# ─── Contexte assemblé avec compression progressive ───────────────────

def get_context() -> str:
    """Assemble le contexte de session avec compression progressive.

    Compression à 3 niveaux (inspiré du système Hermès) :
    1. En-dessous de soft_warn_tokens → buffer complet + résumé si existe
    2. Entre soft_trim_at et hard_trim_at → résumé + buffer protégé (N derniers)
    3. Au-dessus de hard_trim_at → résumé seul + messages protégés

    Returns:
        Contexte formaté, ou "" si vide
    """
    init_session()
    buffer = get_session_buffer()
    summary = get_session_summary()
    estimated = estimate_tokens(buffer)

    soft_warn = COMPRESSION_CONFIG["soft_warn_tokens"]
    soft_trim = COMPRESSION_CONFIG["soft_trim_at"]
    hard_trim = COMPRESSION_CONFIG["hard_trim_at"]
    protect_n = COMPRESSION_CONFIG["protect_last_n"]

    parts = []

    # Niveau 1 : tout va bien
    if estimated < soft_warn:
        if summary:
            parts.append(f"[RÉSUMÉ SESSION]\n{summary}")
        if buffer:
            parts.append(f"[SESSION EN COURS]\n{buffer}")
        return "\n\n".join(parts)

    # Niveau 2 : compression douce
    if estimated < hard_trim:
        if summary:
            parts.append(f"[RÉSUMÉ SESSION]\n{summary}")
        # Protéger les N derniers messages
        buffer_protected = get_session_buffer(protect_last=protect_n)
        if buffer_protected:
            parts.append(f"[SESSION RÉCENTE]\n{buffer_protected}")
        logging.info(f"[CONTEXT] Compression douce: ~{estimated} tokens → résumé + {protect_n} derniers")
        return "\n\n".join(parts)

    # Niveau 3 : compression agressive
    buffer_protected = get_session_buffer(protect_last=protect_n)
    if buffer_protected:
        parts.append(f"[SESSION RÉCENTE]\n{buffer_protected}")
    if summary:
        parts.append(f"[RÉSUMÉ SESSION]\n{summary}")
    logging.info(f"[CONTEXT] Compression agressive: ~{estimated} tokens → seulement {protect_n} derniers + résumé")
    return "\n\n".join(parts)


# ─── Reset de session ─────────────────────────────────────────────────

def reset_session():
    """Réinitialise le compteur, l'ID de session et force la réinitialisation des tables."""
    global SESSION_ID, MESSAGE_COUNTER, _INITIALIZED
    SESSION_ID = datetime.now().strftime("%Y-%m-%d_%H")
    MESSAGE_COUNTER = 0
    _INITIALIZED = False
