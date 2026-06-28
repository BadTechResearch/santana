import os, json, logging
import sys
sys.path.insert(0, os.path.expanduser("~/santana"))

def detect_livre(text: str) -> str:
    text = text.lower()
    if any(w in text for w in ['famille', 'epouse', 'sanaa', 'enfant', 'amael', 'jokebed', 'frere', 'soeur', 'parent']):
        return 'famille'
    if any(w in text for w in ['btr', 'bad technology', 'openclaw', 'santana', 'roadmap', 'phase', 'migration', 'oracle', 'hetzner', 'agent', 'discipline', 'forge', 'memoire vivante']):
        return 'vision_btr'
    if any(w in text for w in ['projet', 'build', 'developp', 'code', 'feature', 'deploie', 'commit', 'sinbad']):
        return 'projets'
    if any(w in text for w in ['ressens', 'emotion', 'frustre', 'content', 'triste', 'anxieux', 'fier', 'peur', 'stress', 'joie', 'colere']):
        return 'psychologie'
    # Fallback LLM si les mots-clés n'ont rien trouvé
    return _llm_detect_livre(text)


def _llm_detect_livre(text: str) -> str:
    """Fallback LLM pour la détection de livre quand les mots-clés échouent."""
    try:
        prompt = (
            "Classe ce message dans UN SEUL livre Santana parmi : famille, vision_btr, projets, psychologie.\n"
            "Reponds UNIQUEMENT par le nom du livre, rien d'autre.\n"
            "Si aucun ne correspond, reponds 'aucun'.\n\n"
            f"Message : {text[:500]}"
        )
        from deepseek_client import ask
        result = ask([{"role": "user", "content": prompt}], max_tokens=200).strip().lower()
        livres = {'famille', 'vision_btr', 'projets', 'psychologie'}
        for livre in livres:
            if livre in result:
                return livre
        return ''
    except Exception as e:
        logging.error(f"[CLASSIFIER] LLM fallback error: {e}")
        return ''
