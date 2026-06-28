#!/usr/bin/env python3
"""
Moteur d'embeddings vectoriels pour les Livres de Santana.
Utilise sentence-transformers (all-MiniLM-L6-v2) avec chunking par sections.
Recherche sémantique réelle — pas juste TF-IDF.
"""
import os, json, re, time, logging, functools
import numpy as np
from numpy.linalg import norm

BASE_DIR = os.path.expanduser("~/santana")
LIVRES_DIR = os.path.join(BASE_DIR, "memory", "livres")
INDEX_PATH = os.path.join(BASE_DIR, "memory", "livres_index.json")
EMBED_PATH = os.path.join(BASE_DIR, "memory", "livres_embeddings.npy")

# Cache mémoire
_model = None
_chunks = []       # list of dicts: {book, section, text}
_embeddings = None  # (N, 384) numpy array
_CHUNK_FILES_KEY = "chunk_files"  # pour rebuild_if_needed

# Cache sémantique : évite de ré-embedder les mêmes requêtes (via lru_cache)
MODEL_NAME = "all-MiniLM-L6-v2"

def _get_model():
    """Charge le modèle lazy (une seule fois, singleton global)."""
    from atlas_engine.model_singleton import get_model as _get_singleton
    return _get_singleton()


def _chunk_livre(fname: str, text: str) -> list[dict]:
    """Découpe un livre en chunks : par sections ##, puis par paragraphes."""
    chunks = []
    sections = re.split(r'\n(?=## )', text)
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        # Extraire le titre de la section
        title = ""
        sec_lines = sec.split("\n")
        if sec_lines and sec_lines[0].startswith("##"):
            title = sec_lines[0].lstrip("#").strip()

        # Si la section est petite, c'est un chunk
        if len(sec) <= 4000:
            chunks.append({
                "book": fname,
                "section": title or "(debut)",
                "text": sec
            })
        else:
            # Découper en sous-chunks par paragraphes vides ou sous-titres ###
            paras = re.split(r'\n(?=### )|\n\n+', sec)
            current = ""
            for p in paras:
                p = p.strip()
                if not p:
                    continue
                if len(current) + len(p) > 4000:
                    if current.strip():
                        chunks.append({
                            "book": fname,
                            "section": f"{title} > {current[:60].strip().split(chr(10))[0]}" if title else current[:60].strip(),
                            "text": current.strip()
                        })
                    current = p
                else:
                    current += "\n\n" + p
            if current.strip():
                chunks.append({
                    "book": fname,
                    "section": f"{title} > {current[:60].strip().split(chr(10))[0]}" if title else current[:60].strip(),
                    "text": current.strip()
                })
    return chunks


def _load_livres_chunked() -> list[dict]:
    """Charge tous les livres et les découpe en chunks."""
    all_chunks = []
    if not os.path.exists(LIVRES_DIR):
        return all_chunks
    for fname in sorted(os.listdir(LIVRES_DIR)):
        if fname.endswith(".md"):
            path = os.path.join(LIVRES_DIR, fname)
            try:
                with open(path, "r") as f:
                    content = f.read().strip()
                if content:
                    all_chunks.extend(_chunk_livre(fname, content))
            except Exception as e:
                logging.error(f"[EMBEDDINGS] Erreur lecture {fname}: {e}")
    return all_chunks


def build_index() -> int:
    """Construit l'index vectoriel des Livres et le sauvegarde."""
    global _chunks, _embeddings

    _chunks = _load_livres_chunked()
    if not _chunks:
        _embeddings = None
        return 0

    model = _get_model()
    texts = [c["text"] for c in _chunks]

    # Embeddings par batch (évite OOM)
    batch_size = 32
    all_embs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        embs = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_embs.append(embs)
    _embeddings = np.vstack(all_embs) if len(all_embs) > 1 else all_embs[0]

    # Sauvegarde atomique : écrire dans .tmp puis renommer
    import tempfile as _tf
    index_data = {
        "chunks": [{k: v for k, v in c.items() if k != "text"} for c in _chunks],
        "chunk_count": len(_chunks),
        "model": MODEL_NAME,
        "dim": _embeddings.shape[1],
        _CHUNK_FILES_KEY: sorted(f for f in os.listdir(LIVRES_DIR) if f.endswith(".md")) if os.path.exists(LIVRES_DIR) else [],
    }
    # Écrire dans des fichiers temporaires (np.save ajoute .npy auto)
    _tmp_npy = EMBED_PATH.replace(".npy", "") + "_tmp"
    np.save(_tmp_npy, _embeddings)
    _tmp_idx = INDEX_PATH + "_tmp"
    with open(_tmp_idx, "w") as f:
        json.dump(index_data, f, ensure_ascii=False)
    # Renommer (atomique sur la plupart des FS)
    os.replace(_tmp_npy + ".npy", EMBED_PATH)
    os.replace(_tmp_idx, INDEX_PATH)

    logging.info(f"[EMBEDDINGS] Index construit: {len(_chunks)} chunks dans {len(set(c['book'] for c in _chunks))} livres")
    return len(_chunks)


def load_index() -> bool:
    """Charge l'index depuis le disque (ou rebuild)."""
    global _chunks, _embeddings

    if _embeddings is not None:
        return True

    if not os.path.exists(INDEX_PATH) or not os.path.exists(EMBED_PATH):
        # Nettoyer les fichiers .tmp orphelins (crash pendant l'écriture atomique)
        for stale in [INDEX_PATH + "_tmp", EMBED_PATH.replace(".npy", "") + "_tmp.npy"]:
            if os.path.exists(stale):
                os.remove(stale)
        count = build_index()
        return count > 0

    try:
        with open(INDEX_PATH, "r") as f:
            index_data = json.load(f)
        _chunks = index_data.get("chunks", [])
        _embeddings = np.load(EMBED_PATH)
        logging.info(f"[EMBEDDINGS] Index charge: {len(_chunks)} chunks")
        return True
    except Exception as e:
        logging.error(f"[EMBEDDINGS] Erreur chargement: {e}, rebuild...")
        return build_index() > 0


def _encode_query(query: str) -> np.ndarray:
    """Cache LRU des 40 dernières requêtes vectorisées (via lru_cache).
    
    Normalise la requête (strip + lower) avant le cache pour éviter
    de stocker des doublons sémantiquement identiques.
    """
    key = query.strip().lower()
    return _encode_cached(key)


@functools.lru_cache(maxsize=40)
def _encode_cached(query: str) -> np.ndarray:
    """Vectorise une requête normalisée avec cache LRU."""
    model = _get_model()
    return model.encode([query], normalize_embeddings=True)[0]


def search(query: str, top_k: int = 5, threshold: float = 0.30) -> list:
    """
    Recherche sémantique dans les Livres.
    Retourne liste de (fichier, score, section, extrait).
    Le threshold par défaut est 0.30 (cosine similarity sur vecteurs normalisés).
    """
    global _chunks, _embeddings

    if not load_index():
        return []

    if _embeddings is None or not _chunks:
        return []

    model = _get_model()
    query_vec = _encode_query(query)

    # Cosine similarity sur tous les chunks
    scores = _embeddings @ query_vec  # produit scalaire = cos sim (vecteurs normalisés)
    indices = np.argsort(scores)[::-1]

    results = []
    book_count: dict = {}
    for idx in indices:
        if scores[idx] < threshold:
            continue
        chunk = _chunks[idx]
        book = chunk["book"] if isinstance(chunk, dict) else ""
        if book_count.get(book, 0) >= 2:
            continue
        book_count[book] = book_count.get(book, 0) + 1
        text = chunk.get("text", "") if isinstance(chunk, dict) else chunk.text if hasattr(chunk, 'text') else str(chunk)
        # Si c'est un dict sauvegardé, le texte n'est pas dans chunks (optionnel : recharger)
        if isinstance(chunk, dict) and "text" not in chunk:
            # Recharger le texte depuis le fichier
            livre_path = os.path.join(LIVRES_DIR, chunk["book"])
            try:
                with open(livre_path, "r") as f:
                    text = f.read()
                # Prendre juste la section pertinente
                section = chunk.get("section", "")
                if section:
                    # Chercher la section dans le texte
                    lines = text.split("\n")
                    in_section = False
                    section_lines = []
                    for line in lines:
                        if line.strip().startswith("## ") and section in line:
                            in_section = True
                        elif line.strip().startswith("## ") and in_section:
                            break
                        if in_section:
                            section_lines.append(line)
                    if section_lines:
                        text = "\n".join(section_lines)
            except Exception:
                logging.error("[EMBED] Section reload failure during search")
                text = "(erreur rechargement)"
        extrait = text[:1000].strip()
        if len(text) > 1000:
            extrait += "..."
        results.append((book, float(scores[idx]), chunk.get("section", ""), extrait))

    return results[:top_k]


def rebuild_if_needed() -> bool:
    """Rebuild si l'index manque ou si les fichiers LIVRES sont plus récents.
    Ne rebuild PLUS automatiquement — Santana n'écrit plus dans memory/livres/.
    Les livres sont en lecture seule pour Santana (écriture par l'humain uniquement)."""
    if not os.path.exists(LIVRES_DIR):
        return False
    current_files = sorted(f for f in os.listdir(LIVRES_DIR) if f.endswith(".md"))
    if not os.path.exists(INDEX_PATH) or not os.path.exists(EMBED_PATH):
        logging.info("[EMBED] Index introuvable, construction initiale...")
        build_index()
        return True
    try:
        index_mtime = os.path.getmtime(INDEX_PATH)
        with open(INDEX_PATH, "r") as f:
            index_data = json.load(f)
        known_files = set(index_data.get(_CHUNK_FILES_KEY, []))
        for fname in current_files:
            if fname not in known_files:
                # Nouveau fichier → rebuild immédiat (pas d'attente 5 min)
                logging.info(f"[EMBED] Nouveau fichier détecté: {fname} — rebuild")
                build_index()
                return True
            fpath = os.path.join(LIVRES_DIR, fname)
            if os.path.getmtime(fpath) > index_mtime:
                logging.info(f"[EMBED] {fname} modifié — rebuild nécessaire (manuellement?)")
                # Ne rebuild que si le fichier est plus vieux de 5 min (évite auto-rebuild)
                if time.time() - os.path.getmtime(fpath) > 300:
                    build_index()
                    return True
                else:
                    logging.info(f"[EMBED] Modification récente (<5min), on skip le rebuild (évite boucle)")
                    return False
        if current_files != index_data.get(_CHUNK_FILES_KEY, []):
            logging.info(f"[EMBED] Fichiers changés — rebuild")
            build_index()
            return True
        return False
    except Exception as e:
        logging.error("[EMBED] Rebuild check failure: %s", e)
        return False


def get_stats() -> dict:
    """Retourne des stats sur l'index et le cache."""
    global _chunks, _embeddings
    if _embeddings is None:
        if not load_index():
            return {"status": "empty"}
    books = set(c["book"] for c in _chunks) if _chunks else set()
    cache_info = _encode_cached.cache_info()
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "chunks": len(_chunks) if _chunks else 0,
        "books": len(books),
        "dim": _embeddings.shape[1] if _embeddings is not None else 0,
        "cache_size": cache_info.currsize,
        "cache_hits": cache_info.hits,
        "cache_misses": cache_info.misses,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--rebuild":
        count = build_index()
        print(f"Index reconstruit: {count} chunks")
    elif len(sys.argv) > 1 and sys.argv[1] == "--stats":
        print(json.dumps(get_stats(), indent=2))
    else:
        load_index()
        print(f"Index charge: {get_stats()}")
        if len(sys.argv) > 1:
            query = " ".join(sys.argv[1:])
            results = search(query)
            if results:
                for fname, score, section, extrait in results:
                    print(f"\n[{score:.2f}] {fname} — {section}")
                    print(f"  {extrait[:200]}...")
            else:
                print(f"Aucun résultat pour: {query}")
