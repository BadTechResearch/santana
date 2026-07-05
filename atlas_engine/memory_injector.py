#!/usr/bin/env python3
"""
Memory Injector V2 — MEMOIRE VIVANTE avec recherche vectorielle + SQLite.

Lit les registres et livres depuis SQLite (tables `registres`, `livres`).
Fallback fichiers Markdown si SQLite est vide ou indisponible.

Architecture :
- Flux : toujours inclus en entier (fichiers .md journaliers)
- Registres : depuis table SQLite `registres` (personnes, dates, décisions)
- Livres : top-k chunks sémantiques via embeddings (ou depuis table `livres`)
"""
import os
from core.db import get_db
import logging

from datetime import datetime
from core.utils import get_base_dir

BASE_DIR = get_base_dir()
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
DB_PATH = os.path.join(BASE_DIR, "memory.db")

MAX_VIVANTE_BYTES = 12_000   # 12 KB (était 16_000) — bon compromis qualité/vitesse
TOP_K = 5                     # chunks de livres (était 10)


def _read_file(path: str) -> str:
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        logging.error("[MEMORY_INJECTOR] _read_file echec: %s", path)
        return ""


def _get_flux() -> str:
    """Flux du mois en cours (rotation mensuelle). Fallback vers la semaine."""
    now = datetime.now()
    month = f"{now.year}-{now.month:02d}.md"
    flux_path = os.path.join(MEMORY_DIR, "flux", f"flux-{month}")
    content = _read_file(flux_path)
    if content:
        return f"[FLUX {now.year}-{now.month:02d}]\n{content}"
    # Fallback: fichier semaine
    week = now.strftime("%Y-%m-%d_semaine")
    flux_path = os.path.join(MEMORY_DIR, "flux", f"{week}.md")
    content = _read_file(flux_path)
    return f"[FLUX SEMAINE]\n{content}" if content else ""


def _get_registres() -> list[str]:
    """Registres depuis SQLite (table `registres`). Fallback fichiers .md."""
    parts = []

    # Essayer SQLite d'abord
    try:
        conn = get_db()
        c = conn.cursor()
        for reg_type in ["personnes", "dates", "decisions"]:
            c.execute(
                "SELECT content, context FROM registres WHERE type = ? ORDER BY id DESC LIMIT 15",
                (reg_type,)
            )
            rows = c.fetchall()
            if rows:
                lines = []
                for content, context in rows:
                    line = f"{content}"
                    if context:
                        line += f" ({context[:60]})"
                    lines.append(f"- {line}")
                parts.append(f"[REGISTRE {reg_type}]\n" + "\n".join(lines))
    except Exception as e:
        logging.error(f"[MEMORY_INJECTOR] SQLite registres read failure: {e}")

    # Fallback fichiers Markdown si SQLite n'a rien
    if not parts:
        for fname in ["personnes.md", "dates.md", "decisions.md"]:
            path = os.path.join(MEMORY_DIR, "registre", fname)
            content = _read_file(path)
            if content:
                if fname == "decisions.md" and len(content) > 2000:
                    content = content[:2000] + "\n[...]"
                parts.append(f"[REGISTRE {fname}]\n{content}")
    return parts


def _get_livres_vectoriel(query: str, top_k: int = TOP_K) -> list[str]:
    """
    Recherche vectorielle de chunks de livres pertinents pour la query.
    Retourne une liste de blocs formatés "[LIVRE fname — section]\n{extrait}".
    """
    try:
        from atlas_engine.embeddings import search
        results = search(query, top_k=top_k)
    except Exception as e:
        logging.error(f"[MEMORY_INJECTOR] Vector search fallback failure: {e}")
        return []

    if not results:
        return []

    parts = []
    seen_books = {}  # book → best_score pour éviter la redondance
    for fname, score, section, extrait in results:
        if fname not in seen_books or score > seen_books[fname]:
            seen_books[fname] = score
        parts.append(f"[LIVRE {fname} — {section}]\n{extrait}")

    return parts


def _get_livres_fallback() -> list[str]:
    """
    * Fallback : charge tous les livres tronqués à 1600 chars chacun.
    """
    livres_dir = os.path.join(MEMORY_DIR, "livres")
    if not os.path.exists(livres_dir):
        return []

    parts = []
    for fname in sorted(os.listdir(livres_dir)):
        if not fname.endswith(".md"):
            continue
        content = _read_file(os.path.join(livres_dir, fname))
        if content:
            parts.append(f"[LIVRE {fname}]\n{content[:1600]}")
    return parts


def build_memoire_vivante(query: str = "", top_k: int = TOP_K) -> str:
    """
    Construit la MEMOIRE VIVANTE intelligemment :

    1. Flux semaine (toujours inclus, entier)
    2. Registres (toujours inclus, entiers)
    3. Livres :
       - Si query fournie → recherche vectorielle top-k chunks
       - Sinon → fallback tronqué (1600 chars/livre)
    4. Applique la limite 20 KB

    Args:
        query: Dernier message de l'utilisateur (pour recherche vectorielle)
        top_k: Nombre de chunks de livres à inclure (défaut: 10)

    Returns:
        Texte formaté pour injection dans le system prompt, ou "" si vide.
    """
    parts = []

    # 1. Registres (priorité haute — stable, toujours inclus en premier)
    parts.extend(_get_registres())

    # 2. Livres — vectoriel ou fallback
    if query:
        livres_parts = _get_livres_vectoriel(query, top_k)
        if livres_parts:
            parts.extend(livres_parts)
        else:
            # Vector search n'a rien trouvé → fallback
            livres_parts = _get_livres_fallback()
            if livres_parts:
                parts.extend(livres_parts)
                logging.info(
                    "[MEMORY_INJECTOR] Vector search returned 0 results, fallback used"
                )
        logging.info(
            f"[MEMORY_INJECTOR] Query mode: {len(livres_parts)} livre chunks"
        )
    else:
        livres_parts = _get_livres_fallback()
        if livres_parts:
            parts.extend(livres_parts)

    # 3. Flux en dernier (tronqué en premier si dépassement)
    flux = _get_flux()
    if flux:
        parts.append(flux)

    if not parts:
        return ""

    result = "\n\n".join(parts)

    # Limite 16 KB
    raw = result.encode("utf-8")
    if len(raw) > MAX_VIVANTE_BYTES:
        result = raw[:MAX_VIVANTE_BYTES].decode("utf-8", errors="replace")
        # Couper au dernier saut de ligne propre
        last_nl = result.rfind("\n")
        if last_nl > 0:
            result = result[:last_nl]
        result += "\n\n[...tronqué à 16 KB...]"

    return result


# ─── DÉTECTEUR DE CONFLITS (V2 — Bonus) ───────────────────────────────────
# Compare toute nouvelle information avec les décisions existantes.
# Utilise all-MiniLM (déjà chargé) pour la similarité cosinus.

def _load_decision_texts() -> list[str]:
    """Charge les décisions depuis SQLite (source vivante)."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT content FROM registres WHERE type='decisions' ORDER BY id DESC LIMIT 30")
        rows = [r[0] for r in c.fetchall() if "[DÉCISION]" in r[0] or len(r[0]) > 20]
        if rows:
            return rows
    except Exception as e:
        logging.error("[MEMORY_INJECTOR] _load_decision_texts SQLite echec: %s", e)
    # Fallback fichier registre mensuel
    decisions_path = os.path.join(MEMORY_DIR, "registre", f"registre-{datetime.now().strftime('%Y-%m')}.md")
    try:
        with open(decisions_path) as f:
            return [l.strip() for l in f if "[DÉCISION]" in l]
    except Exception:
        return []


def detect_conflicts(user_message: str, threshold: float = 0.75) -> str:
    """
    Vérifie si le message de l'utilisateur contredit une décision existante.
    Retourne un texte d'alerte ou "" si aucun conflit.
    """
    if not user_message or len(user_message) < 20:
        return ""

    decisions = _load_decision_texts()
    if not decisions:
        return ""

    try:
        from atlas_engine.embeddings import _get_model
        model = _get_model()  # singleton caché — ne recharge plus à chaque appel

        # Vectoriser le message + les décisions
        all_texts = [user_message[:300]] + [d[:200] for d in decisions]
        embs = model.encode(all_texts, normalize_embeddings=True, show_progress_bar=False)

        query_vec = embs[0]
        import numpy as np

        conflicts = []
        for i, decision in enumerate(decisions):
            sim = float(query_vec @ embs[i + 1])
            if sim > threshold:
                # Vérifier s'il y a une contradiction lexicale
                msg_lower = user_message.lower()
                dec_lower = decision.lower()
                # Mots de changement d'avis
                change_markers = [
                    "finalement", "en fait", "non", "plus", "arrête", "quitte",
                    "change", "annule", "oublie", "pas ça", "autre"
                ]
                if any(m in msg_lower for m in change_markers):
                    conflicts.append(decision[:120])

        if conflicts:
            alert = "⚠️ Serge, attention : ce que tu dis semble contredire ces décisions précédentes :\n"
            for c in conflicts[:3]:
                alert += f"  • {c}\n"
            alert += "(Vérifie avant de changer de cap.)"
            return alert

        return ""
    except Exception as e:
        logging.error(f"[CONFLICT] Conflict detection failure: {e}")
        return ""
