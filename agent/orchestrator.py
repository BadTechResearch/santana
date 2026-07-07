"""
orchestrator.py — Construction du prompt système et classification des messages.

Rôle : préparer le contexte que Santana voit à chaque interaction.
Extrait de core/react_loop.py pour alléger la boucle principale.
"""

import os
import logging
from datetime import datetime
from core.utils import get_base_dir

BASE_DIR = get_base_dir()
SOUL_DIR = os.path.join(BASE_DIR, "soul")

# ─── Cache prompt incrémental ─────────────────────────────────────────────
# Le socle (identité + âme + règles + instructions finales) est construit
# une fois puis réutilisé tant que les fichiers soul/ ne changent pas.
_PROMPT_CACHE = {"base": None, "soul_mtime": 0}
_SOUL_CACHE = {}
_PROFILE_CACHE = {"content": None, "mtime": 0}

# Liste canonique des fichiers soul/ effectivement utilisés par le prompt
# système (voir _build_prompt_base ci-dessous). Source unique de vérité :
# agent/self.py::scan_soul() l'importe au lieu de maintenir sa propre liste
# (RULES.md/STYLE.md ont été fusionnés en CONDUCT.md le 20/06/2026 — c'est
# exactement ce genre de divergence qu'une liste partagée rend impossible).
SOUL_FILES = ["SOUL.md", "IDENTITY.md", "USER.md", "CONDUCT.md"]


def _load_soul_file_cached(filename: str) -> str:
    """Charge le contenu d'un fichier soul/ avec cache."""
    global _SOUL_CACHE
    if filename in _SOUL_CACHE:
        return _SOUL_CACHE[filename]
    try:
        fpath = os.path.join(SOUL_DIR, filename)
        if os.path.exists(fpath):
            with open(fpath, "r") as f:
                content = f.read().strip()
            _SOUL_CACHE[filename] = content
            return content
    except Exception as e:
        logging.warning("[SOUL] Fichier manquant: %s", e)
    return ""


def _build_prompt_base() -> str:
    """Construit la base statique du prompt : identité + âme + règles + instructions finales.

    Cette base représente ~70% du prompt et ne change que si les fichiers soul/ sont modifiés.
    """
    try:
        import pytz
        now = datetime.now(pytz.timezone("Africa/Kinshasa")).strftime("%A %d %B %Y, %H:%M")
    except Exception as e:
        logging.error("[SYSTEM] pytz timezone fallback: %s", e)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

    prompt = (
        f"Santana — premier agent SINBAD, créé par Serge. Assistant personnel, pas chatbot générique. {now}.\n"
        "Tu n'es PAS un 'modèle de langage'. Tu es l'agent de Serge. Tu connais Serge, son travail,\n"
        "ses projets BTR, sa famille. Tu as des opinions sur lui basées sur vos échanges.\n"
        "Ne dis JAMAIS 'je suis un modèle de langage', 'je n'ai pas d'opinions', 'je suis là pour t'aider'.\n"
        "Français naturel. Adapte ta réponse au contexte : courte si la question est simple, développée si elle est complexe.\n"
        "Pas d'intro pompeuse, pas de barres.\n"
        "Pour chercher sur le web, utilise web_search() — n'écris JAMAIS de balises XML.\n"
        "\n"
        "RÈGLES :\n"
        "1. Benchmark : refuse les faits historiques obscurs. EXCEPTION : les questions sur Serge/BTR toujours répondues.\n"
        "2. Challenge Serge s'il a tort.\n"
        "3. Ne prédit PAS l'avenir.\n"
        "4. Questions serveur → « Je n'ai pas accès » (test).\n"
        "5. Synthétise tes outils, pas de brut.\n"
        "6. Salut → « Bonjour [prénom] ».\n"
        "7. DISTINGUE QUI PARLE : si message commence par un en-tête (Santana:, Clou:, etc.), c'est un transfert, pas Serge.\n"
        "8. FORMAT TÉLÉGRAMME : utilise **gras** pour les titres clés,\n"
        "   `code` pour les snippets, • pour les listes, --- pour les séparateurs.\n"
        "   Pas de tableaux Markdown (incompatibles).\n"
        "9. DIRECT, PAS DE FLATTERIE, en français.\n"
    )

    # Identité fondamentale (SOUL.md, IDENTITY.md)
    soul_content = _load_soul_file_cached("SOUL.md")
    if soul_content:
        prompt += "\n\n" + soul_content
    identity_content = _load_soul_file_cached("IDENTITY.md")
    if identity_content:
        prompt += "\n\n" + identity_content

    # Profil de Serge (USER.md)
    user_content = _load_soul_file_cached("USER.md")
    if user_content:
        lines = [l.strip("- ").strip() for l in user_content.split("\n")
                 if l.strip() and not l.startswith("#")]
        if lines:
            prompt += "\nSerge: " + "; ".join(lines[:6])

    # Conduite et style (CONDUCT.md — fusion RULES + STYLE)
    conduct_content = _load_soul_file_cached("CONDUCT.md")
    if conduct_content:
        conduct_lines = [l.strip("- ").strip() for l in conduct_content.split("\n")
                         if l.strip() and not l.startswith("#") and not l.startswith("---")]
        numbered = [r for r in conduct_lines if any(r.startswith(str(i)) for i in range(1, 20))]
        if numbered:
            prompt += "\nRègles: " + "; ".join(numbered[:20])
        style_short = [s for s in conduct_lines if len(s) < 200 and not any(s.startswith(str(i)) for i in range(1, 20))][:6]
        if style_short:
            prompt += "\nFormat: " + "; ".join(style_short)

    # Instructions finales (statiques)
    prompt += (
        "\n"
        "INSTRUCTIONS FINALES (respecte-les dans l'ordre):\n"
        "1. SALUTATION: Si Serge se presente, commence par « Bonjour Serge. »\n"
        "2. BTR = AGENT: Quand tu parles de BTR, dis « agent BTR » ou « BTR et ses agents ».\n"
        "3. HONNETETE: Si on te demande « que faire si tu ne sais pas », reponds: « Je dis que je ne sais pas. »\n"
        "4. REPONSE: Reponds directement et en francais, sans structure imposée. Sois naturel.\n"
    )

    return prompt


def get_prompt_base() -> str:
    """Retourne la base du prompt avec cache. Reconstruit si soul/*.md a changé."""
    global _PROMPT_CACHE
    latest_mtime = 0
    for fname in SOUL_FILES:
        fpath = os.path.join(SOUL_DIR, fname)
        if os.path.exists(fpath):
            try:
                mtime = os.path.getmtime(fpath)
                if mtime > latest_mtime:
                    latest_mtime = mtime
            except OSError:
                pass
    if _PROMPT_CACHE["base"] and latest_mtime <= _PROMPT_CACHE["soul_mtime"]:
        return _PROMPT_CACHE["base"]
    _PROMPT_CACHE["base"] = _build_prompt_base()
    _PROMPT_CACHE["soul_mtime"] = latest_mtime
    return _PROMPT_CACHE["base"]


def invalidate_prompt_cache():
    """Invalide TOUS les caches. À appeler sur /reset ou si soul/*.md change."""
    global _PROMPT_CACHE, _SOUL_CACHE, _PROFILE_CACHE
    _PROMPT_CACHE["base"] = None
    _SOUL_CACHE.clear()
    _PROFILE_CACHE = {"content": None, "mtime": 0}


# ─── Messages sociaux (pas de mémoire nécessaire) ──────────────────────────────
_QUERIES_COURTES = {"bonjour", "salut", "coucou", "hey", "hello", "hi", "yo",
                    "merci", "ok", "d'accord", "oui", "non", "👍", "✅",
                    "cc", "re", "hmm", "dac", "okay", "bye", "au revoir", "super",
                    "parfait", "cool", "nice", "lol", "mdr", "ptdr", "thanks"}


def load_soul_file(filename: str) -> str:
    """Charge le contenu d'un fichier soul/ (SOUL.md, RULES.md, etc.). Version non-cachée pour usage externe."""
    return _load_soul_file_cached(filename)


def classify_message(text: str) -> str:
    """Classifie le message pour éviter les appels mémoire inutiles.

    Returns:
        "SOCIAL" — salutations, remerciements (pas de mémoire)
        "FACTUEL" — questions externes (météo, actu, définition)
        "PERSONNEL" — tout le reste (mémoire activée)
    """
    text_lower = text.lower().strip()

    # Messages sociaux
    social_patterns = [
        # Note: "bien" retire volontairement — trop générique (matche "comBien", "bienvennue", etc.)
        "salut", "bonjour", "bonsoir", "hello", "hi ",
        "ça va", "ca va", "comment tu vas", "comment vas",
        "merci", "ok", "okay", "super", "parfait",
        "oui", "non", "ouais", "nope", "yes", "no",
        "bye", "au revoir", "bonne nuit", "à plus"
    ]
    if any(p in text_lower for p in social_patterns) and len(text_lower) < 40:
        return "SOCIAL"

    # Questions factuelles externes
    factual_patterns = [
        "météo", "meteo", "température", "actualité", "actu ",
        "news", "politique", "économie", "bourse", "bitcoin",
        "quelle heure", "aujourd'hui", "cette semaine",
        "c'est quoi", "qu'est-ce que", "définition", "explique"
    ]
    if any(p in text_lower for p in factual_patterns):
        return "FACTUEL"

    # Questions de synthèse — Pas besoin d'outils shell
    # "c'est quoi" / "qu'est-ce que" / "définition" : retirés (déjà présents dans
    # factual_patterns ci-dessus, testé avant — étaient inatteignables ici).
    synthesis_patterns = [
        "résume", "resume", "synthèse", "synthese", "explique-moi",
        "que penses-tu", "ton avis", "ton opinion", "comment tu vois",
        "architecture", "structure", "organisation",
        "en quelques paragraphes", "en quelques phrases",
        "schéma", "schéma global", "tableau de bord",
        "bilan", "état des lieux",
    ]
    if any(p in text_lower for p in synthesis_patterns) and len(text_lower) < 200:
        return "SYNTHESE"

    # Messages longs et complexes (analyse, recherche multi-étapes)
    if len(text_lower) > 150 or any(w in text_lower for w in
        ["analyse", "comparer", "différence", "pourquoi", "comment fonctionne",
         "impact", "conséquences", "avantages", "inconvénients", "évolution",
         "tendances", "perspectives", "est-ce que"]):
        if any(p in text_lower for p in social_patterns + factual_patterns):
            pass  # Laisser la classification existante prioritaire
        else:
            return "DEEP"

    return "PERSONNEL"


def get_routing_intent(msg_type: str, text: str = "") -> str:
    """Retourne une instruction de comportement adaptée au type de message.
    
    Cette instruction est injectée dans le prompt système pour guider
    le ton, la longueur et l'utilisation des outils.
    """
    intent_map = {
        "SOCIAL": (
            "INTENTION : Réponse très courte et informelle. "
            "1-2 phrases maximum. Pas de structure, pas de gras, pas d'outils."
        ),
        "FACTUEL": (
            "INTENTION : Réponse factuelle et concise. "
            "Va droit au fait. Utilise web_search si tu manques d'information."
        ),
        "SYNTHESE": (
            "INTENTION : Synthèse structurée. "
            "Ne pas utiliser d'outils shell. Organisation claire mais pas de template imposé."
        ),
        "DEEP": (
            "INTENTION : Analyse approfondie. "
            "Question complexe — utilise plusieurs outils si nécessaire (web_search, run_code). "
            "Prends le temps de construire une réponse complète et documentée. "
            "STRUCTURE : commence par UNE ligne « **TLDR :** » qui donne la conclusion "
            "en une phrase, puis développe. Pas de question finale."
        ),
        "PERSONNEL": (
            "INTENTION : Réponse réfléchie. "
            "Utilise les outils si pertinent. Pas de précipitation, pas de blabla."
        ),
    }
    return intent_map.get(msg_type, intent_map["PERSONNEL"])


def build_system_prompt(user_message: str = "", msg_type: str = None) -> str:
    """Construit le prompt système complet : socle caché + couche dynamique.

    Le socle (identité + âme + règles + instructions finales) est mis en cache
    et reconstruit uniquement si les fichiers soul/*.md changent.
    La couche dynamique (contexte session, skills, mémoire vivante) est
    reconstruite à chaque message.

    Args:
        user_message: Message utilisateur pour injection contexte
        msg_type: Type de message pré-classifié (évite 2e appel classify)
    """
    # Socle mis en cache
    prompt = get_prompt_base()

    # Auto-connaissance : scan dynamique de soi-même
    try:
        from agent.self import build_context as _self_context
        _ctx = _self_context()
        prompt += "\n" + _ctx + "\n"
    except Exception as e:
        logging.error("[SYSTEM] Self-context fallback: %s", e)
        prompt += "\nOutils: web_search, memory_query, get_datetime, save_skill, search_skills, web_navigate, web_screenshot, atlas.\n"

    # Routing intent — utiliser msg_type passé ou classifier si None
    if msg_type is None:
        msg_type = classify_message(user_message)
    prompt += "\n" + get_routing_intent(msg_type, user_message) + "\n"

    # Profil utilisateur injecté avec cache TTL 300s (P2 — pas de read disque à chaque message)
    try:
        global _PROFILE_CACHE
        import os as _os
        _pf = _os.path.join(get_base_dir(), "skills/profile-serge.md")
        now_mtime = _os.path.getmtime(_pf) if _os.path.exists(_pf) else 0
        if _PROFILE_CACHE["content"] and now_mtime <= _PROFILE_CACHE["mtime"]:
            _profile = _PROFILE_CACHE["content"]
        else:
            with open(_pf) as _f:
                _profile = _f.read()
            _PROFILE_CACHE["content"] = _profile
            _PROFILE_CACHE["mtime"] = now_mtime
        if _profile:
            prompt += "\n### PROFIL UTILISATEUR\n" + _profile + "\n"
    except Exception as _pe:
        logging.debug("[SYSTEM] Profile inject error: %s", _pe)

    # Checklist de clôture (Phase 1 — P1)
    prompt += (
        "\n### CHECKLIST AVANT DE RÉPONDRE\n"
        "Avant de livrer ta réponse, vérifie ces 5 points OBLIGATOIRES :\n"
        "1. Ai-je utilisé les outils appropriés pour vérifier les faits ?\n"
        "2. Ma réponse répond-elle à TOUTE la question de Serge ?\n"
        "3. Ai-je inclus un AVIS ASYMÉTRIQUE ? (l'angle que personne d'autre n'aurait)\n"
        "4. Suis-je direct et en FRANÇAIS, sans blabla ?\n"
        "5. Ai-je évité les répétitions et les généralités ?\n"
    )

    # Avis asymétrique — instruction (Phase 2)
    prompt += (
        "\n### AVIS ASYMÉTRIQUE OBLIGATOIRE\n"
        "Termine CHAQUE analyse, rapport ou recommandation par un paragraphe asymétrique.\n"
        "❌ PAS une reformulation — PAS une conclusion générique — PAS \"en résumé\"\n"
        "✅ L'angle que PERSONNE d'autre n'aurait eu — le point de vue décalé\n"
        "✅ Ta signature distinctive — ce qui fait que Serge sait que c'est toi\n"
    )

    # Instruction mémoire
    prompt += "\nMÉMOIRE: utilise l'outil atlas() à chaque information importante : décision de Serge, "
    prompt += "info perso, projet BTR, date/délai, émotion forte, idée ou leçon. "
    prompt += "N'attends pas la fin de la conversation. Sauvegarde immédiatement."

    # Top 3 skills
    try:
        from memory.memory import get_top_skills
        top = get_top_skills(3)
        if top:
            prompt += "\nSkills: " + ", ".join(t for t, _, u in top)
    except Exception as e:
        logging.error("[SKILLS] Skills fetch failure: %s", e)

    # Contexte de session (utilise msg_type passé — évite 3e classify)
    message_type = msg_type if msg_type else (classify_message(user_message) if user_message else "SOCIAL")
    _degraded = os.path.exists(os.path.join(BASE_DIR, '.crash_flag'))

    # Planification pour tâches complexes (Plan-and-Execute)
    if message_type == "PERSONNEL" and len(user_message.strip()) > 40:
        try:
            from agent.planner import needs_planning, get_planning_instruction
            if needs_planning(user_message):
                prompt += get_planning_instruction(user_message)
        except Exception as e:
            logging.error("[PLANNER] Planning injection failure: %s", e)

    if message_type not in ("SOCIAL", "FACTUEL") and not _degraded:
        try:
            from agent.context import get_session_buffer, get_session_summary

            # Couche Bleue : buffer de session
            session_buffer = get_session_buffer()
            if session_buffer:
                prompt += "\n\n[SESSION EN COURS]\n" + session_buffer

            # Couche Argent : résumé de session
            session_summary = get_session_summary()
            if session_summary:
                prompt += "\n\n[RÉSUMÉ SESSION]\n" + session_summary

            # Couche Or : Mémoire Vivante vectorielle
            from atlas_engine.memory_injector import build_memoire_vivante
            memoire = build_memoire_vivante(query=user_message)
            if memoire:
                raw = memoire.encode("utf-8")
                if len(raw) > 18000:
                    memoire = raw[:18000].decode("utf-8", errors="replace")
                    last_nl = memoire.rfind("\n")
                    if last_nl > 0:
                        memoire = memoire[:last_nl]
                    memoire += "\n[...]"
                prompt += "\n\n" + memoire

        except Exception as e:
            logging.error("[MEMORY] Memory injection failure: %s", e)
    elif _degraded:
        prompt += "\n[MODE DÉGRADÉ — mémoire vivante désactivée, réponses concises]"

    # Détecteur de conflits
    if message_type == "PERSONNEL" and not _degraded:
        try:
            from atlas_engine.memory_injector import detect_conflicts
            conflict = detect_conflicts(user_message)
            if conflict:
                prompt += f"\n\n[⚠️ ALERTE CONFLIT MÉMOIRE]\n{conflict}\n"
        except Exception as e:
            logging.error("[MEMORY] Conflict detector fallback: %s", e)

    return prompt
