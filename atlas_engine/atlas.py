#!/usr/bin/env python3
"""
Atlas — Gardien de la mémoire Santana.

Atlas est le successeur du Steward et du Writer.
Il décide ce qui mérite d'être retenu, et l'écrit AUX BONS ENDROITS :
- SQLite (tables `registres`, `livres`) — pour la recherche vectorielle
- Fichiers .md (livres, registres, flux mensuel) — pour la lecture humaine
- Flux mensuel (flux-YYYY-MM.md) — pour la trace temporelle

Fusionne les capacités du Steward (scoring, filtrage, détection) et du Writer
(écriture SQLite, dédoublonnage cosinus, classification).
"""

import os, re, json, logging, sqlite3
from datetime import datetime
from core.db import get_db

BASE_DIR = os.path.expanduser("~/santana")
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
DB_PATH = os.path.join(BASE_DIR, "memory.db")

# ─── CONFIGURATION ──────────────────────────────────────────────────────

MAX_ENTRY_CHARS = 1500        # max chars par entrée dans un livre (V3: augmenté)
MAX_WRITE_PER_TURN = 5        # max écritures par échange (V3: augmenté)
STEWARD_INTERVAL = 1          # min échanges entre sauvegardes (V3: tous les échanges)
COSINE_DUP_THRESHOLD = 0.85   # seuil de dédoublonnage cosinus
MEMOIRE_CAUSALE = True        # lier les décisions à leurs résultats
AUTO_NETTOYAGE = True         # routine hebdomadaire de nettoyage

_LIVRES = ["psychologie", "famille", "projets", "vision_btr"]
_FLUX_FILE = f"flux-{datetime.now().strftime('%Y-%m')}.md"


# ─── MODÈLE VECTORIEL (MiniLM, singleton global) ────────────────────────

def _get_model():
    from atlas_engine.model_singleton import get_model
    return get_model()


def _cosine_similarity(a: str, b: str) -> float:
    try:
        model = _get_model()
        embs = model.encode([a[:200], b[:200]], normalize_embeddings=True, show_progress_bar=False)
        import numpy as np
        return float(embs[0] @ embs[1])
    except Exception as e:
        logging.error("[ATLAS] Cosine similarity fallback failed: %s", e)
        return 0.0


# ─── COMPTEUR D'ÉCHANGES (anti-spam) ───────────────────────────────────

_INIT_DONE = False

def _init_counter():
    global _INIT_DONE
    if _INIT_DONE:
        return
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS atlas_counter (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            exchange_count INTEGER DEFAULT 0,
            last_save_at TEXT
        )''')
        c.execute("INSERT OR IGNORE INTO atlas_counter (id, exchange_count, last_save_at) VALUES (1, 0, NULL)")
        # Table de causalité — lie les décisions à leurs résultats
        c.execute('''CREATE TABLE IF NOT EXISTS atlas_causalite (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER,
            decision_text TEXT,
            resultat TEXT,
            date_decision TEXT,
            date_resultat TEXT,
            statut TEXT DEFAULT 'en_cours',
            livre_concerne TEXT
        )''')
        # Table de nettoyage — dernière exécution
        c.execute('''CREATE TABLE IF NOT EXISTS atlas_cleanup (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_cleanup_at TEXT
        )''')
        c.execute("INSERT OR IGNORE INTO atlas_cleanup (id, last_cleanup_at) VALUES (1, NULL)")
        # Table registres — personnes, decisions, dates
        c.execute('''CREATE TABLE IF NOT EXISTS registres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT, content TEXT, context TEXT,
            tags TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        # Table livres — psychologie, famille, projets, vision_btr
        c.execute('''CREATE TABLE IF NOT EXISTS livres (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            livre TEXT, content TEXT, tag TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        _INIT_DONE = True
    except Exception as e:
        logging.error(f"[ATLAS] DB init failure: {e}")


def _get_count() -> int:
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT exchange_count FROM atlas_counter WHERE id = 1")
        row = c.fetchone()
        return row[0] if row else 0
    except Exception as e:
        logging.error("[ATLAS] Get count failed: %s", e)
        return 0


def _increment():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE atlas_counter SET exchange_count = exchange_count + 1 WHERE id = 1")
        conn.commit()
    except Exception as e:
        logging.error("[ATLAS] Increment exchange count failed: %s", e)


def _reset_count():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE atlas_counter SET exchange_count = 0, last_save_at = ? WHERE id = 1",
                  (datetime.now().isoformat(),))
        conn.commit()
    except Exception as e:
        logging.error("[ATLAS] Reset exchange count failed: %s", e)


# ─── DÉTECTION — INFOS IMPORTANTES ─────────────────────────────────────

def _contains_decision(text: str) -> bool:
    patterns = [
        r'\bje (choisis|décide|opte pour|lance|crée|fais|arrête|quitte|commence|démarre)\b',
        r'\bje vais (avec|lancer|créer|faire|arrêter|quitter|commencer|démarrer)\b',
        r'\bon va (faire|lancer|créer|démarrer|utiliser|partir sur)\b',
        r"\bc'est décidé\b",
        r"\bj'ai décidé (de |que )\b",
        r'\bje veux (absolument|vraiment|définitivement)\b',
        r'\bnouveau (projet|plan|objectif|but|sprint)\b',
        r'\bon (passe|change|abandonne|switch)\b',
    ]
    return any(re.search(p, text.lower()) for p in patterns)


def _contains_important_info(text: str) -> bool:
    text_lower = text.lower()

    # Dates
    if re.search(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', text):
        return True
    if re.search(r'\b\d{1,2}\s*(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s*\d{4}\b', text_lower):
        return True
    if re.search(r'\b(aujourd\'hui|demain|hier|la semaine prochaine|le mois prochain)\b', text_lower):
        return True

    # Chiffres significatifs
    if re.search(r'\b\d{3,}\b', text) or re.search(r'\b\d+[.,]\d+\s*(€|\$|%|k|m|gb|to|mo)\b', text_lower):
        return True

    # Noms propres
    stoplist = {'Merci', 'Très', 'Trop', 'Bon', 'Bien', 'Super', 'Parfait', 'Tout',
                'Avec', 'Pour', 'Sur', 'Mais', 'Donc', 'Voilà', 'Alors'}
    proper = [n for n in re.findall(r'\b[A-Z][a-zéèêëàâäùûüîïôö]{2,}\b', text) if n not in stoplist]
    if len(proper) >= 2:
        return True

    # Mots-clés BTR
    btr_kw = ['btr', 'bad tech', 'sinbad', 'livre', 'mémoire', 'workshop', 'roadmap',
              'deadline', 'release', 'version', 'commit', 'déploiement', 'production',
              'migration', 'architecture', 'stack', 'api', 'token']
    if any(kw in text_lower for kw in btr_kw):
        return True

    # Informations personnelles
    personal = ['ma femme', 'mon épouse', 'mon fils', 'ma fille', 'mon frère', 'ma sœur',
                'mon père', 'ma mère', 'ma famille', 'anniversaire', 'rendez-vous']
    if any(kw in text_lower for kw in personal):
        return True

    return False


def _contains_idea(text: str) -> bool:
    patterns = [
        r'\bet si on\b',
        r"\bj'ai (une|une petite|une nouvelle) idée\b",
        r'\bje (réfléchis|pense|imagine|envisage)\b',
        r'\bon pourrait (essayer|tenter|faire|ajouter|modifier)\b',
        r"\bc'est une (bonne|excellente|intéressante) idée\b",
    ]
    return any(re.search(p, text.lower()) for p in patterns)


def _is_important(user_msg: str, santana_resp: str) -> bool:
    """Scoring : décision=2pts, info=1pt, idée=1pt. ≥2 ou décision seule = sauvegarde."""
    combined = f"{user_msg} {santana_resp}"

    # Trop court → ignorer (sauf si c'est une décision claire)
    if len(combined.split()) < 5:
        return False

    # Salutation banale → ignorer
    short_social = re.search(
        r'^(merci|ok|dacc|super|parfait|bien|oui|non|salut|bonjour|cc|re|voyons|voilà)',
        user_msg.strip().lower()
    )
    if short_social and len(user_msg.split()) <= 5:
        return False

    has_decision = _contains_decision(combined)
    has_info = _contains_important_info(combined)
    has_idea = _contains_idea(combined)

    if has_decision:
        return True
    if has_info:
        return True
    if has_idea and len(combined.split()) >= 12:
        return True

    return False


# ─── DÉTECTION — PERSONNES, DATES, ÉMOTIONS ────────────────────────────

_PERSON_PATTERNS = [
    (r'\b(ma femme|mon épouse|mon mari)\s+(\w+)\b', 'conjoint'),
    (r'\b(mon fils|ma fille)\s+(\w+)\b', 'enfant'),
    (r'\b(mon frère|ma sœur)\s+(\w+)\b', 'fratrie'),
    (r'\b(mon père|ma mère)\s+(\w+)\b', 'parent'),
    (r'\b(maman|papa|tonton|tata|grand-mère|grand-père|mamie|papy)\b', 'famille'),
]
_PERSON_STOPLIST = {'fier', 'fière', 'content', 'heureux', 'triste', 'fatigué',
                    'là', 'ici', 'parti', 'revenu', 'arrivé', 'prêt', 'occupé',
                    'les', 'des', 'une', 'sur', 'dans', 'pour', 'avec', 'est', 'fait', 'note'}


def _extract_persons(text: str) -> list[dict]:
    results = []
    for pat, rel_type in _PERSON_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            if rel_type == "famille":
                name = m.group(0).strip().capitalize()
            else:
                name = m.groups()[-1].strip().capitalize()
            if name and len(name) > 2 and name.lower() not in _PERSON_STOPLIST:
                if not any(r["name"].lower() == name.lower() for r in results):
                    results.append({"name": name, "relation": rel_type, "context": text[:100]})
    return results


def _extract_dates(text: str) -> list[str]:
    patterns = [
        r'\b(\d{1,2})\s*(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s*(\d{4})?\b',
        r'\b(aujourd\'hui|demain|hier|la semaine prochaine|le mois prochain)\b',
        r'\b(avant|d\'ici|pour le|dans) \d+ (jours|semaines|mois)\b',
    ]
    found = []
    t = text.lower()
    for pat in patterns:
        for m in re.finditer(pat, t):
            found.append(m.group(0).strip())
    return list(set(found))


_EMOTION_MAP = {
    "colere": ["énervé", "colère", "furieux", "en colère", "rage"],
    "frustration": ["frustr", "agacé", "exaspéré", "ras-le-bol", "marre", "lassé", "écœuré"],
    "tristesse": ["triste", "déçu", "découragé", "abattu", "peine", "chagrin", "nostalgie", "nostalgique"],
    "joie": ["content", "heureux", "ravi", "enthousiaste", "super", "génial", "formidable"],
    "fierte": ["fier", "fière", "fierté", "accompli", "fier de", "réalisation"],
    "fatigue": ["fatigué", "épuisé", "crevé", "exténué", "vidé", "éreinté"],
    "excitation": ["excité", "hâte", "impatient", "enthousiaste", "motivé"],
}


def _detect_emotion(text: str) -> str:
    t = text.lower()
    for tag, keywords in _EMOTION_MAP.items():
        if any(kw in t for kw in keywords):
            return tag
    return "neutre"


# ─── WRITING — SQLite ───────────────────────────────────────────────────

def _write_registre_sql(reg_type: str, content: str, context: str = "", tags: str = ""):
    try:
        recent_conn = get_db()
        c = recent_conn.cursor()
        c.execute("SELECT content FROM registres WHERE type = ? ORDER BY id DESC LIMIT 20", (reg_type,))
        for row in c.fetchall():
            if _cosine_similarity(content, row[0]) > COSINE_DUP_THRESHOLD:
                return False
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO registres (type, content, context, tags) VALUES (?, ?, ?, ?)",
                  (reg_type, content[:300], context[:200], tags))
        conn.commit()
        logging.info(f"[ATLAS/SQL] {reg_type}: {content[:60]}")
        return True
    except Exception as e:
        logging.error(f"[ATLAS/SQL] Error: {e}")
        return False


def _write_livre_sql(livre_name: str, content: str, tag: str = "neutre"):
    try:
        condensed = content[:MAX_ENTRY_CHARS].strip()
        if len(content) > MAX_ENTRY_CHARS:
            condensed = condensed.rsplit(" ", 1)[0] + " [...]"

        dup_conn = get_db()
        c = dup_conn.cursor()
        c.execute("SELECT content FROM livres WHERE livre = ? ORDER BY id DESC LIMIT 10", (livre_name,))
        for row in c.fetchall():
            if _cosine_similarity(condensed, row[0][:200]) > COSINE_DUP_THRESHOLD:
                return False
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO livres (livre, content, tag) VALUES (?, ?, ?)",
                  (livre_name, condensed, tag))
        conn.commit()
        logging.info(f"[ATLAS/SQL] Livre {livre_name}: {condensed[:60]}")
        return True
    except Exception as e:
        logging.error(f"[ATLAS/SQL] Livre error: {e}")
        return False


# ─── WRITING — Fichiers .md ────────────────────────────────────────────

def _write_flux_md(content: str):
    """Écrit une entrée dans le flux mensuel."""
    try:
        flux_path = os.path.join(MEMORY_DIR, "flux", _FLUX_FILE)
        os.makedirs(os.path.dirname(flux_path), exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{now}] {content}\n"
        # Si le fichier n'existe pas, ajouter l'en-tête
        if not os.path.exists(flux_path):
            header = f"# Flux Santana — {datetime.now().strftime('%Y-%m')}\n\n"
            with open(flux_path, "w") as f:
                f.write(header)
        else:
            # Déduplication : vérifier les 5 dernières lignes
            try:
                with open(flux_path, "r") as f:
                    lines = f.readlines()
                last_5 = lines[-5:] if len(lines) >= 5 else lines
                content_hash = content[:80].lower().strip()
                for line in last_5:
                    if content_hash in line.lower():
                        return True
            except Exception:
                pass
        with open(flux_path, "a") as f:
            f.write(entry)
        return True
    except Exception as e:
        logging.error(f"[ATLAS/MD] Flux error: {e}")
        return False


def _write_registre_md(reg_type: str, entry: str):
    """Ajoute une ligne dans le fichier registre mensuel."""
    try:
        reg_path = os.path.join(MEMORY_DIR, "registre", f"registre-{datetime.now().strftime('%Y-%m')}.md")
        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        if not os.path.exists(reg_path):
            with open(reg_path, "w") as f:
                f.write(f"# Registre — {datetime.now().strftime('%Y-%m')}\n\n")
        with open(reg_path, "a") as f:
            f.write(f"- {entry}\n")
        return True
    except Exception as e:
        logging.error(f"[ATLAS/MD] Registre error: {e}")
        return False


def _write_livre_md(livre_name: str, content: str, tag: str = "neutre"):
    """Ajoute une entrée dans le fichier livre correspondant."""
    try:
        livre_path = os.path.join(MEMORY_DIR, "livres", f"{livre_name}.md")
        os.makedirs(os.path.dirname(livre_path), exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## {now} [{tag}]\n{content}\n"
        with open(livre_path, "a") as f:
            f.write(entry)
        return True
    except Exception as e:
        logging.error(f"[ATLAS/MD] Livre error: {e}")
        return False


# ─── CLASSIFICATION DE LIVRE ───────────────────────────────────────────

def _classify_livre(text: str) -> str | None:
    """Détermine dans quel livre ranger un texte."""
    from atlas_engine.classifier import detect_livre
    livre = detect_livre(text)
    if livre in _LIVRES:
        return livre
    # Fallback vectoriel
    try:
        from atlas_engine.embeddings import search
        results = search(text[:200], top_k=1)
        if results:
            livre = results[0][0].replace(".md", "")
            if livre in _LIVRES:
                return livre
    except Exception as e:
        logging.error("[ATLAS] Classification fallback vectoriel failed: %s", e)
    return None


# ─── MÉMOIRE CAUSALE ──────────────────────────────────────────────────

def _enregistrer_causalite(decision_text: str, livre: str = ""):
    """Enregistre une décision dans la table de causalité pour suivi."""
    if not MEMOIRE_CAUSALE:
        return
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO atlas_causalite (decision_text, date_decision, statut, livre_concerne, decision_id) VALUES (?, ?, 'en_cours', ?, (SELECT COALESCE(MAX(id),0)+1 FROM atlas_causalite))",
            (decision_text[:200], datetime.now().isoformat(), livre)
        )
        conn.commit()
        logging.info(f"[ATLAS/CAUSE] Décision enregistrée: {decision_text[:60]}")
    except Exception as e:
        logging.error(f"[ATLAS/CAUSE] Causal memory save failure: {e}")


def _resoudre_causalite(decision_prefix: str, resultat: str):
    """Marque une décision comme résolue avec son résultat."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "UPDATE atlas_causalite SET statut='resolue', resultat=?, date_resultat=? WHERE decision_text LIKE ? AND statut='en_cours' ORDER BY id DESC LIMIT 1",
            (resultat[:200], datetime.now().isoformat(), f"%{decision_prefix[:60]}%")
        )
        conn.commit()
    except Exception as e:
        logging.error(f"[ATLAS/CAUSE] Causal resolution failure: {e}")


# ─── AUTO-NETTOYAGE HEBDOMADAIRE ──────────────────────────────────────

def _nettoyage_hebdo():
    """Routine de nettoyage automatique (1x/semaine max)."""
    if not AUTO_NETTOYAGE:
        return
    try:
        # Vérifier si déjà fait cette semaine
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT last_cleanup_at FROM atlas_cleanup WHERE id = 1")
        row = c.fetchone()
        
        if row and row[0]:
            last = datetime.fromisoformat(row[0])
            # Si moins de 7 jours, on saute
            if (datetime.now() - last).days < 7:
                return
        
        # Détecter les décisions sans résultat depuis > 7 jours
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "SELECT id, decision_text FROM atlas_causalite WHERE statut='en_cours' AND date_decision < ?",
            (datetime.now().isoformat(),)  # fallback: prend tout
        )
        stale = c.fetchall()
        
        for dec_id, text in stale:
            logging.info(f"[ATLAS/CLEAN] Décision non résolue: {text[:60]}")
        
        # Marquer les décisions de +15 jours comme 'abandonnees'
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=15)).isoformat()
        c.execute(
            "UPDATE atlas_causalite SET statut='abandonnee' WHERE statut='en_cours' AND date_decision < ?",
            (cutoff,)
        )
        conn.commit()
        
        # Mettre à jour la date de dernier nettoyage
        c.execute("UPDATE atlas_cleanup SET last_cleanup_at = ? WHERE id = 1",
                  (datetime.now().isoformat(),))
        conn.commit()
        
        archived = len(stale)
        if archived:
            logging.info(f"[ATLAS/CLEAN] {archived} décisions anciennes marquées")
    except Exception as e:
        logging.error(f"[ATLAS/CLEAN] Cleanup failure: {e}")


# ─── HORODATAGE ENRICHI ───────────────────────────────────────────────

def _horodatage_enrichi(user_msg: str, santana_resp: str, livre: str = "") -> str:
    """Génère un horodatage avec humeur et contexte."""
    emotion = _detect_emotion(santana_resp or user_msg)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [ts]
    if emotion != "neutre":
        parts.append(f"[{emotion}]")
    if livre:
        parts.append(f"({livre})")
    return " ".join(parts)


# ─── POINT D'ENTRÉE PRINCIPAL ──────────────────────────────────────────

def learn(user_message: str, santana_response: str = ""):
    """
    Point d'entrée principal d'Atlas.
    Analyse l'échange, décide s'il mérite d'être retenu, et écrit.

    Args:
        user_message: Message de Serge
        santana_response: Réponse de Santana
    """
    try:
        from core.utils import strip_dsml
        santana_response = strip_dsml(santana_response)
    except Exception as e:
        logging.error("[ATLAS] strip_dsml fallback in learn() failed: %s", e)

    _init_counter()
    _nettoyage_hebdo()
    exchange_count = _get_count()

    # 1. Vérifier la fréquence (max 1 sauvegarde tous les STEWARD_INTERVAL échanges)
    if exchange_count < STEWARD_INTERVAL:
        logging.debug(f"[ATLAS] Ignoré (fréquence: {exchange_count}/{STEWARD_INTERVAL})")
        _increment()
        return None

    combined = f"{user_message} {santana_response[:500]}"

    # 2. Mode silence — si échange banal, on n'écrit RIEN
    if len(combined.split()) < 8:
        _increment()
        return None
    short_social = re.search(
        r'^(merci|ok|dacc|super|parfait|bien|oui|non|salut|bonjour|cc|re|voyons|voilà)',
        user_message.strip().lower()
    )
    if short_social and len(user_message.split()) <= 5:
        _increment()
        return None

    # 3. Scoring : est-ce que cet échange est important ?
    has_decision = _contains_decision(combined)
    has_info = _contains_important_info(combined)
    has_idea = _contains_idea(combined)

    # Résolution automatique de causalité (même pour échanges banals)
    _RESULTAT_PATTERNS = [
        r"\b(c'est fait|ça marche|j'ai fait|j'ai terminé|c'est bon|réussi|déployé|corrigé|fini|terminé)\b"
    ]
    if any(re.search(p, combined.lower()) for p in _RESULTAT_PATTERNS):
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT id, decision_text FROM atlas_causalite WHERE statut='en_cours' ORDER BY id DESC LIMIT 5")
            for dec_id, dec_text in c.fetchall():
                if _cosine_similarity(combined[:200], dec_text[:200]) > 0.65:
                    _resoudre_causalite(dec_text[:60], user_message[:200])
                    break
        except Exception as _ce:
            logging.debug(f"[ATLAS] Auto-resolve causalite: {_ce}")

    if not has_decision and not has_info and not (has_idea and len(combined.split()) >= 12):
        logging.info("[ATLAS] Ignoré (échange non significatif)")
        _increment()
        return None

    written = 0

    # 4. Extraire les entités
    persons = _extract_persons(combined)
    dates = _extract_dates(combined)

    # 5. Écrire dans les registres (SQLite + fichiers)
    for p in persons:
        if written >= MAX_WRITE_PER_TURN:
            break
        content = f"👤 **{p['name']}** ({p['relation']})"
        if _write_registre_sql("personnes", content, p['context']):
            _write_registre_md("personnes", f"[{datetime.now().strftime('%Y-%m-%d')}] {content}")
            written += 1

    for d in dates[:2]:
        if written >= MAX_WRITE_PER_TURN:
            break
        content = f"📅 **{d}**"
        if _write_registre_sql("dates", content, user_message[:100]):
            _write_registre_md("dates", f"[{datetime.now().strftime('%Y-%m-%d')}] {content}")
            written += 1

    # 6. Décisions
    if has_decision and written < MAX_WRITE_PER_TURN:
        content = user_message[:200]
        livre = _classify_livre(combined)
        _enregistrer_causalite(content, livre or "")
        if _write_registre_sql("decisions", content, santana_response[:100]):
            _write_registre_md("decisions", f"[{datetime.now().strftime('%Y-%m-%d')}] [DÉCISION] {content}")
            written += 1

    # 7. Écrire dans le livre approprié
    if santana_response and written < MAX_WRITE_PER_TURN:
        livre = _classify_livre(combined)
        if livre:
            tag = _detect_emotion(santana_response)
            content = f"{santana_response[:MAX_ENTRY_CHARS].strip()}"
            if len(santana_response) > MAX_ENTRY_CHARS:
                content = content.rsplit(" ", 1)[0] + " [...]"
            if _write_livre_sql(livre, content, tag):
                _write_livre_md(livre, content, tag)
                written += 1

    # 8. Écrire dans le flux mensuel
    if written > 0:
        livre_detecte = _classify_livre(combined) if 'livre' not in dir() else livre
        if not livre_detecte:
            livre_detecte = ""
        flux_ts = _horodatage_enrichi(user_message, santana_response, livre_detecte)
        flux_msg = user_message[:120].strip()
        _write_flux_md(f"{flux_ts} {flux_msg}")

    # 9. Rebuild index vectoriel si nécessaire
    if written > 0:
        try:
            from atlas_engine.embeddings import rebuild_if_needed
            rebuild_if_needed()
        except Exception as e:
            logging.error(f"[ATLAS] Index rebuild failure: {e}")

    _reset_count()
    logging.info(f"[ATLAS] ✅ {written} écriture(s)")
    return written


def learn_quick(context: str) -> int | None:
    """Version simplifiée : prend juste une chaîne de contexte."""
    parts = context.split("\n---\n", 1)
    user_msg = parts[0] if parts else context
    santana_resp = parts[1] if len(parts) > 1 else ""
    return learn(user_msg, santana_resp)


# ─── INTERFACE PUBLIQUE ────────────────────────────────────────────────

def get_registres(reg_type: str, limit: int = 20) -> list[dict]:
    """Lit les registres depuis SQLite."""
    results = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT content, context, tags, created_at FROM registres WHERE type = ? ORDER BY id DESC LIMIT ?",
                  (reg_type, limit))
        for row in c.fetchall():
            results.append({"content": row[0], "context": row[1], "tags": row[2], "date": row[3]})
    except Exception as e:
        logging.error(f"[ATLAS] Get registres read failure: {e}")
    return results


def get_livres(livre_name: str, limit: int = 20) -> list[dict]:
    """Lit les entrées d'un livre depuis SQLite."""
    results = []
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT content, tag, created_at FROM livres WHERE livre = ? ORDER BY id DESC LIMIT ?",
                  (livre_name, limit))
        for row in c.fetchall():
            results.append({"content": row[0], "tag": row[1], "date": row[2]})
    except Exception as e:
        logging.error(f"[ATLAS] Get livres read failure: {e}")
    return results
