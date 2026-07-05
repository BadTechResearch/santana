"""context.py — Gestion intelligente du contexte de session Santana.

Optimisé avec buffer RAM + lazy SQLite flush pour éliminer les écritures
disques à chaque message (gain ~100-150ms par message).

Fonctions :
- init_session() : crée les tables de session
- push_exchange() : enregistre un échange (RAM → SQLite toutes les 5 entrées)
- get_session_buffer() : retourne le buffer depuis la RAM
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

COMPRESSION_CONFIG = {
    "buffer_max_messages": 20,
    "summarize_interval": 10,
    "soft_warn_tokens": 4000,
    "soft_trim_at": 8000,
    "hard_trim_at": 16000,
    "summary_max_chars": 500,
    "protect_last_n": 5,
}

SESSION_ID = datetime.now().strftime("%Y-%m-%d_%H")
MESSAGE_COUNTER = 0
_INITIALIZED = False

# ─── Buffer RAM (P1.6 — évite SQLite à chaque message) ─────────────────
# Liste de dicts {"role": str, "content": str, "timestamp": str}
# Flush différé vers SQLite toutes les FLUSH_INTERVAL entrées
_RAM_BUFFER: list[dict] = []
_FLUSH_INTERVAL = 5         # Flush SQLite toutes les 5 entrées
_FLUSH_COUNTER = 0          # Nombre d'entrées depuis dernier flush


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


# ─── Buffer de session (RAM + lazy SQLite) ────────────────────────────

def push_exchange(role: str, content: str):
    """Ajoute un message au buffer — RAM d'abord, SQLite toutes les 5.

    Args:
        role: 'user' ou 'assistant'
        content: Contenu du message
    """
    global MESSAGE_COUNTER, _FLUSH_COUNTER
    init_session()

    # Ajouter au buffer RAM
    _RAM_BUFFER.append({
        "role": role,
        "content": content[:1000],
        "timestamp": datetime.now().isoformat(),
    })
    # Garder max N messages en RAM
    while len(_RAM_BUFFER) > COMPRESSION_CONFIG["buffer_max_messages"]:
        _RAM_BUFFER.pop(0)

    MESSAGE_COUNTER += 1
    _FLUSH_COUNTER += 1

    # Lazy flush SQLite — seulement toutes les 5 entrées
    if _FLUSH_COUNTER >= _FLUSH_INTERVAL:
        _flush_to_sqlite()


def _flush_to_sqlite():
    """Flush différé du buffer RAM vers SQLite."""
    global _FLUSH_COUNTER
    if not _RAM_BUFFER:
        _FLUSH_COUNTER = 0
        return
    try:
        conn = get_db()
        c = conn.cursor()
        for entry in _RAM_BUFFER:
            c.execute(
                "INSERT INTO session_buffer (session_id, role, content) VALUES (?, ?, ?)",
                (SESSION_ID, entry["role"], entry["content"])
            )
        # Garder max N en SQLite aussi
        max_m = COMPRESSION_CONFIG["buffer_max_messages"]
        c.execute('''
            DELETE FROM session_buffer WHERE id NOT IN (
                SELECT id FROM session_buffer
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?
            ) AND session_id = ?
        ''', (SESSION_ID, max_m, SESSION_ID))
        conn.commit()
        _FLUSH_COUNTER = 0
    except Exception as e:
        logging.error(f"[CONTEXT] SQLite flush failure: {e}")


def get_session_buffer(protect_last: int = 0) -> str:
    """Retourne les messages depuis le buffer RAM.

    Args:
        protect_last: Nombre de derniers messages à protéger (ne pas résumer)

    Returns:
        Texte formaté du buffer, ou "" si vide
    """
    if not _RAM_BUFFER:
        return ""
    lines = []
    for i, entry in enumerate(_RAM_BUFFER):
        prefix = "👤 Serge" if entry["role"] == "user" else "🤖 Santana"
        if protect_last and i >= len(_RAM_BUFFER) - protect_last:
            lines.append(f"{prefix}: {entry['content']}")
        else:
            lines.append(f"{prefix}: {entry['content'][:300]}")
    return "\n".join(lines)


# ─── Résumé automatique ───────────────────────────────────────────────

def maybe_auto_summarize():
    """Toutes les N interactions : résumé sémantique via MiniLM."""
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
    """Estime le nombre de tokens (version française améliorée)."""
    if not text:
        return 0
    words = len(text.split())
    if words < 3:
        return max(1, len(text) // 3)
    return max(1, int(words / 0.75))


# ─── Contexte assemblé avec compression progressive ───────────────────

def get_context() -> str:
    """Assemble le contexte de session avec compression progressive.

    Compression à 3 niveaux :
    1. < soft_warn_tokens → buffer complet + résumé si existe
    2. entre soft_trim_at et hard_trim_at → résumé + buffer protégé
    3. > hard_trim_at → résumé seul + messages protégés

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

    # Niveau 1
    if estimated < soft_warn:
        if summary:
            parts.append(f"[RÉSUMÉ SESSION]\n{summary}")
        if buffer:
            parts.append(f"[SESSION EN COURS]\n{buffer}")
        return "\n\n".join(parts)

    # Niveau 2
    if estimated < hard_trim:
        if summary:
            parts.append(f"[RÉSUMÉ SESSION]\n{summary}")
        buffer_protected = get_session_buffer(protect_last=protect_n)
        if buffer_protected:
            parts.append(f"[SESSION RÉCENTE]\n{buffer_protected}")
        logging.info(f"[CONTEXT] Compression douce: ~{estimated} tokens → résumé + {protect_n} derniers")
        return "\n\n".join(parts)

    # Niveau 3
    buffer_protected = get_session_buffer(protect_last=protect_n)
    if buffer_protected:
        parts.append(f"[SESSION RÉCENTE]\n{buffer_protected}")
    if summary:
        parts.append(f"[RÉSUMÉ SESSION]\n{summary}")
    logging.info(f"[CONTEXT] Compression agressive: ~{estimated} tokens → seulement {protect_n} derniers + résumé")
    return "\n\n".join(parts)


# ─── Reset de session ─────────────────────────────────────────────────

def reset_session():
    """Réinitialise le buffer, le compteur et force le flush SQLite."""
    global SESSION_ID, MESSAGE_COUNTER, _INITIALIZED, _RAM_BUFFER, _FLUSH_COUNTER
    # Flush avant reset
    _flush_to_sqlite()
    _RAM_BUFFER.clear()
    SESSION_ID = datetime.now().strftime("%Y-%m-%d_%H")
    MESSAGE_COUNTER = 0
    _FLUSH_COUNTER = 0
    _INITIALIZED = False
