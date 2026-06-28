"""disambiguate.py — Résolution d'ambiguïté dans les messages utilisateur.

Analyse le message entrant + le buffer de session pour détecter
les références implicites et les expliciter avant envoi au LLM.

Stratégie : pattern-matching uniquement (pas de LLM, < 5ms).
"""

import re
import logging
from agent.context import get_session_buffer

# ─── Marqueurs d'ambiguïté ────────────────────────────────────────────

# Pronoms et démonstratifs qui signalent une référence au contexte
_AMBIGUOUS_MARKERS = re.compile(
    r'\b(ce|cet|cette|ces|il|elle|ils|elles|le|la|les)\b'
    r'|\b(ça|cela|ceci|celui|celle|ceux|celles)\b'
    r'|\b(leur|leurs|lui|eux|elles)\b'
    r'|\b(oui|non|si)\b'
    r'|^c\'est\b'
    r'|\bc\'est\s+(pas|juste|vrai|faux|ça|un|une)\b'
    r'|\bce\s+(problème|sujet|point|message|que|dont)\b'
    r'|\bcet(te)?\s+(ambiguïté|idée|concept|projet|système|histoire)\b'
    r'|\bla\s+(même\s+)?(question|chose|raison|façon)\b'
    r'|\ben\s+(fait|réalité|effet)\b'
    r'|\b(c\'est\s+)?pourquoi\b'
    r'|\bcomment\s+ça\b',
    re.IGNORECASE
)

# Mots trop courts / bruit (ne pas traiter les messages triviaux)
_MIN_MESSAGE_LENGTH = 15

# Messages totalement autonomes (pas de désambiguïsation)
_CLEAR_INTENTS = re.compile(
    r'^(bonjour|salut|bonsoir|hello|hi|hey|cc|coucou|re|ok|okay|dac|merci|'
    r'montre-moi|donne-moi|calcule|combien|qui|quand|où)\b',
    re.IGNORECASE
)


def _get_last_exchanges(n: int = 3) -> list[dict]:
    """Récupère les N derniers échanges (user + assistant) du buffer de session.
    
    Returns:
        Liste de dicts {"role": "user"/"assistant", "content": str}
        dans l'ordre chronologique (user puis assistant).
    """
    buf = get_session_buffer()
    if not buf:
        return []

    exchanges = []
    for line in buf.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('👤 Serge:'):
            exchanges.append({"role": "user", "content": line[len('👤 Serge:'):].strip()})
        elif line.startswith('🤖 Santana:'):
            exchanges.append({"role": "assistant", "content": line[len('🤖 Santana:'):].strip()})

    # Retourne les N derniers échanges complets (paires user+assistant)
    # On cherche les dernières paires complètes
    pairs = []  # Liste de paires : [[user, assistant], [user, assistant], ...]
    i = len(exchanges) - 1
    while i >= 1 and len(pairs) < n:
        if exchanges[i]["role"] == "assistant" and exchanges[i-1]["role"] == "user":
            pairs.append([exchanges[i-1], exchanges[i]])  # [user, assistant]
            i -= 2
        else:
            i -= 1

    # Les paires sont du plus récent au plus ancien → inverser pour ordre chronologique
    pairs.reverse()

    # Aplatir : [user, assistant, user, assistant, ...]
    result = []
    for user_msg, ass_msg in pairs:
        result.append(user_msg)
        result.append(ass_msg)
    return result


def disambiguate(user_message: str) -> str:
    """Désambiguïse un message utilisateur en y injectant le contexte pertinent.
    
    Args:
        user_message: Le message brut de l'utilisateur
    
    Returns:
        Le message original ou une version enrichie avec le contexte résolu.
        Format : "[Contexte: ...] \n\nmessage original"
    """
    msg = user_message.strip()
    if not msg or len(msg) < _MIN_MESSAGE_LENGTH:
        return user_message  # Trop court ou vide, pas d'ambiguïté possible

    # Messages clairs (salutations, commandes pures) → pas de désambiguïsation
    if _CLEAR_INTENTS.match(msg.lower()):
        return user_message

    # Vérifier la présence de marqueurs d'ambiguïté
    if not _AMBIGUOUS_MARKERS.search(msg):
        return user_message  # Pas de marqueur → message autonome

    # Récupérer les derniers échanges
    last = _get_last_exchanges(2)
    if not last:
        return user_message  # Pas d'historique → pas de résolution possible

    # Construire le contexte pertinent
    context_parts = []
    for i in range(0, len(last), 2):
        if i + 1 < len(last):
            user_part = last[i]["content"][:500]
            santana_part = last[i+1]["content"][:500]
            if user_part or santana_part:
                context_parts.append(f"Utilisateur: {user_part}\nSantana: {santana_part}")

    if not context_parts:
        return user_message

    # Injection du contexte comme préfixe
    # On ne modifie PAS le message original — on le préfixe
    context_str = " -- ".join(context_parts)
    
    # Nettoyer les sauts de ligne dans le contexte pour garder un bloc compact
    context_str = context_str.replace('\n', ' / ')
    # Tronquer si trop long
    if len(context_str) > 2000:
        context_str = context_str[:2000] + "..."

    enriched = (
        f"[Référence aux échanges précédents : {context_str}]\n\n"
        f"{user_message}"
    )

    logging.debug(f"[AMBIGUÏTÉ] Message enrichi : {enriched[:300]}...")
    return enriched
