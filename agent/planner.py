#!/usr/bin/env python3
"""Planner — Plan-and-Execute pour tâches complexes Santana.

Détecte quand une requête utilisateur mérite un plan avant exécution,
et injecte une instruction de planification structurée dans le prompt.

Importé par orchestrator.py (fallback silencieux si absent).
"""

import re
import logging

logger = logging.getLogger(__name__)

# Seuils
_COMPLEX_THRESHOLD_CHARS = 60       # en dessous → pas besoin de plan
_MULTI_STEP_THRESHOLD = 3           # mots-clés multi-étapes minimum
_MAX_PLAN_STEPS = 5                 # étapes max dans le plan


def needs_planning(text: str) -> bool:
    """Détermine si une requête utilisateur nécessite une planification.

    Critères (au moins 1 suffit) :
    1. Message long (>60 chars) AVEC mots-clés multi-étapes
    2. Mention explicite de plan/stratégie/projet
    3. Demande de comparaison ou choix raisonné
    """
    if not text or len(text.strip()) < _COMPLEX_THRESHOLD_CHARS:
        return False

    t = text.lower().strip()

    # Mots-clés multi-étapes
    multi_step = [
        r'\bd abord\b.*\bpuis\b', r'\bensuite\b.*\bensuite\b',
        r'\b(étape|phase|partie)\s+\d', r'\bpremièrement\b.*\bdeuxièmement\b',
        r'\bplan\b', r'\bstratégie\b', r'\bcalendrier\b', r'\broadmap\b',
        r'\bcompar(e|aison)\b', r'\bchoisir\b.*\bentre\b',
        r'\bprojet\b', r'\bmigration\b', r'\barchitecture\b',
        r'\brédiger\b.*\b(plan|structure)\b', r'\borga(nise|nisation)\b',
        r'\bplusieurs\b.*\b(étape|phase|partie)\b',
        r'\bdécouper\b', r'\béclater\b', r'\bstructurer\b',
        r'\bque dois-je\b', r'\bcomment (faire|procéder|lancer|démarrer)\b',
    ]
    multi_hits = sum(1 for p in multi_step if re.search(p, t))
    if multi_hits >= 1:
        return True

    # Projets long (message > 150 chars) avec signaux d'action
    if len(t) > 150:
        action_signals = [
            r'\b(je|on|nous)\s+(veux|voulons|dois|devons|peut|pouvons)\b',
            r'\bil (faut|faudrait)\b', r'\bbesoin\b.*\b(aide|conseil|avis)\b',
        ]
        if any(re.search(p, t) for p in action_signals):
            return True

    return False


def get_planning_instruction(text: str) -> str:
    """Retourne une instruction de planification injectée dans le prompt.

    La chaîne retournée est concaténée au prompt système pour guider
    Santana vers une exécution structurée (plan → valider → exécuter).

    Args:
        text: Message utilisateur brut.

    Returns:
        Bloc d'instruction formaté pour le prompt.
    """
    t = text.strip()

    plan_block = f"""

## PLANIFICATION REQUISE

L'utilisateur a envoyé une demande complexe qui nécessite une exécution structurée.

**Requête :** {t[:200]}

### Règles Plan-and-Execute

1. **Analyser** la demande → identifier les sous-tâches (max {_MAX_PLAN_STEPS})
2. **Ordonner** les étapes par dépendance (quoi faire d'abord, quoi faire ensuite)
3. **Pour chaque étape**, déterminer l'outil le plus adapté
4. **Exécuter** les étapes une par une, en t'inspirant du plan
5. **Ajuster** si une étape échoue ou révèle une info inattendue
6. **Synthétiser** le résultat final en une réponse organisée

### Format de plan

```
📋 Plan :
1. [outil] → [action précise]
2. [outil] → [action précise]
...
```

Tu n'as pas besoin d'afficher le plan complet à l'utilisateur — il sert de guide interne.
Mais si l'utilisateur demande explicitement de voir le plan, affiche-le avec des émojis 📋.
"""
    return plan_block
