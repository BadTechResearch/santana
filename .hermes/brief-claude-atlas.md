# Brief Claude Code — Diagnostic Mémoire Vivante (Atlas) de Santana

## Contexte

Tu travailles sur l'agent **Santana** dans `~/santana/`. Tu es en mode **diagnostic seulement** — tu peux lire et exécuter du code Python, mais tu NE DOIS PAS modifier de fichiers. Aucune modification, aucun commit, aucun restart.

Tu as accès à `~/santana/venv_new/bin/python3` comme environnement Python.

## Objectif

Analyser en profondeur le système **Atlas** (la mémoire vivante de Santana) et produire un rapport qui :
1. Attribue une note sur 10 à chaque composant avec preuves
2. Identifie toutes les anomalies, bugs, problèmes de qualité
3. Propose des correctifs précis (fichier, ligne, code) pour atteindre 10/10 partout
4. Vise à créer la **meilleure mémoire vivante au monde** : unique, dynamique, peu chère (CPU), couvrant court/moyen/long terme

## Architecture du système

```
atlas_engine/
├── atlas.py          (665 lignes) — Point d'entrée learn(), écriture livres/registres/flux
├── embeddings.py     (304 lignes) — Index vectoriel, search(), build_index()
├── memory_injector.py — build_memoire_vivante() (fallback texte)

memory/
├── livres/           — 4 livres .md (connaissances durables, chunkés en vecteurs)
│   ├── vision_btr.md     (191KB, 3914 lignes)
│   ├── famille.md        (78KB, 1410 lignes)
│   ├── projets.md        (73KB, 1465 lignes)
│   └── psychologie.md    (13KB, 215 lignes)
├── registre/         — 5 fichiers .md (faits structurés)
│   ├── decisions.md      (65 entrées, figé au 25 mai)
│   ├── personnes.md      (2 entrées)
│   ├── dates.md          (1 entrée)
│   ├── registre-2026-05.md
│   └── registre-2026-06.md (138 lignes, figé au 3 juin)
├── flux/             — 2 fichiers .md (trace temporelle)
│   ├── flux-2026-05.md (379 lignes)
│   └── flux-2026-06.md (433 lignes, figé au 3 juin)
└── livres_embeddings.npy  (index vectoriel, 399 chunks, 4 livres, 384d)
```

## État actuel (diagnostics préliminaires)

### De Hermès (architecte) :
| Composant | Note | Problème |
|-----------|------|----------|
| vision_btr.md | 3/10 | 191KB dump non filtré, pollue toutes les recherches |
| famille.md | 4/10 | 1410 lignes brutes non curatées |
| projets.md | 6/10 | Correct mais figé depuis 24 jours |
| psychologie.md | 7/10 | Propre mais secondaire |
| décisions.md | 3/10 | Figé au 25 mai (24 jours sans mise à jour) |
| personnes.md | 5/10 | Trop peu d'entrées |
| dates.md | 3/10 | 1 seule entrée |
| Flux | 5/10 | Figé au 3 juin (15 jours sans) |
| Recherche vectorielle | 5/10 | Pas de pondération fraîcheur |
| Mémoire court-terme (SQLite) | 4/10 | 8 souvenirs seulement |
| **Total** | **4.5/10** | |

### De Santana (auto-diagnostic) :
- PyTorch/libtorch pourrait avoir un problème de chargement → **À VÉRIFIER par toi**
- Le fallback texte fonctionne (charge les livres tronqués à 1600 chars)
- Note auto-attribuée : 5/10

## Travail à faire par Claude Code

### 1. Vérifier le moteur vectoriel
```bash
cd ~/santana && ~/santana/venv_new/bin/python3 -c "
from atlas_engine.embeddings import search
results = search('test mémoire vivante', top_k=3, threshold=0.20)
print(len(results), 'results')
for r in results: print(r)
"
```

### 2. Analyser chaque livre
- Lire le contenu réel de chaque .md
- Estimer le ratio signal/bruit (combien de lignes utiles vs conversations brutes)
- Identifier les sections obsolètes, les doublons, le bruit

### 3. Analyser les registres
- Vérifier la qualité du parsing (regex personnes, dates, décisions)
- Identifier les fausses entrées (mots ordinaires classés comme "contacts")
- Vérifier la fraîcheur des données

### 4. Tester learn() en conditions réelles
```python
from atlas_engine.atlas import learn
learn("message test", "réponse test")  # vérifier si ça écrit dans flux/registres
```

### 5. Vérifier si learn() est bien appelé dans react_loop
```bash
grep -n "learn\|atlas" ~/santana/core/react_loop.py
```

### 6. Analyser le fallback memory_injector
- Lire memory_injector.py
- Comprendre comment le fallback texte fonctionne
- Évaluer sa qualité

## Ce que tu dois produire

Un rapport structuré avec :
1. **Note sur 10 pour chaque composant** (preuve à l'appui : lignes de code, output de commandes, extraits de fichiers)
2. **Anomalies découvertes** (y compris celles que Hermès et Santana ont ratées)
3. **Correctifs précis** : fichier, ligne, code à changer
4. **Vision 10/10** : à quoi ressemblerait la mémoire idéale, étape par étape

## Contraintes

- N'interromps PAS Santana (ne pas toucher au service systemd)
- Ne modifie AUCUN fichier
- Le budget de la mémoire doit rester CPU-only (pas de GPU)
- Le coût doit être proche de zéro (DeepSeek Flash budget)
- Le rapport doit être aussi précis que les miens (Hermès) — preuves par commandes réelles

## Format de sortie

Markdown structuré, avec sections, tableaux, extraits de code et commandes exécutées.
