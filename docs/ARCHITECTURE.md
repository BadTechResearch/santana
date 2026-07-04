# Architecture Santana

> Mise à jour : 4 juillet 2026 — Post-refactoring P0/P1

## Stack

| Couche | Technologie | Rôle |
|--------|-------------|------|
| **LLM Principal** | DeepSeek V4 Flash (api.deepseek.com) | Génération de réponses (tokens texte) |
| **Fallback 1** | Nous/StepFun (step-3.7-flash:free) | Secondaire si DeepSeek indisponible |
| **Fallback 2** | OpenRouter (deepseek/deepseek-v4-flash) | Troisième ligne si les deux premiers échouent |
| **Mémoire persistante** | SQLite WAL (centralisé via `core/db.py`) | Embeddings vectoriels + données structurées |
| **Embeddings** | sentence-transformers all-MiniLM-L6-v2 | Vectorisation locale, recherche sémantique |
| **Messagerie** | python-telegram-bot / discord.py | Canaux Telegram et Discord |
| **API** | Flask | Interface REST, endpoints webhooks |
| **Recherche web** | Serper API | Recherche Google en temps réel |
| **Exécution code** | Subprocess sandboxé | Python/Bash/JS en environnement contrôlé |
| **Orchestration** | Hermes Agent framework | Boucle ReAct, délégation, skills |

## Services systemd

| Service | Rôle | Dépendances |
|---------|------|-------------|
| `santana.service` | Agent principal (Telegram + Discord + API) | réseau, disque (SQLite WAL) |

Architecture mono-service : un seul processus Python (`santana.py`) sert tous les canaux.
Le multi-threading est géré en interne (boucle asyncio + délégation thread-safe).

## Structure du projet

```
santana/
├── santana.py                # Point d'entrée — orchestre le démarrage
├── deepseek_client.py        # Client direct API DeepSeek (streaming, stats)
│
├── agent/                    # Modules de l'agent
│   ├── __init__.py
│   ├── self.py               # Auto-analyse dynamique du code, des outils et du prompt
│   ├── context.py            # Gestion de la fenêtre de contexte
│   ├── evaluator.py          # Évaluation de la qualité des réponses
│   ├── securite.py           # Audit de sécurité, rate limiting, surveillance
│   ├── orchestration.py      # Orchestration de workflows complexes
│   ├── orchestrator.py       # Ordonnancement des tâches (rôle distinct d'orchestration)
│   ├── patterns.py           # Patterns réutilisables de comportement
│   ├── proactive.py          # Comportements proactifs (tasks cron-like)
│   ├── souverainete.py       # Vérification de souveraineté (pas de fuite mémoire/tools)
│   └── tracabilite.py        # Traçabilité des décisions et actions
│
├── core/                     # Moteur central
│   ├── __init__.py
│   ├── react_loop.py         # Boucle ReAct principale — cycle pensée/action/observation
│   ├── provider.py           # Chaîne de providers LLM (DeepSeek → Nous → OpenRouter)
│   ├── db.py                 # Base SQLite centralisée (WAL, get_metrics_db, CREATE TABLE)
│   ├── cost_governor.py      # Gouverneur de coûts (ALERT/THROTTLE/STOP)
│   ├── delegate.py           # Délégation de tâches à des sous-agents
│   ├── cache.py              # Cache mémoire (résultats d'outils, embeddings)
│   ├── disambiguate.py       # Désambiguïsation des requêtes utilisateur
│   ├── json_logger.py        # Logger structuré JSON
│   └── utils.py              # Helpers (env, logging, formatage, dates)
│
├── tools/                    # Registre d'outils de l'agent
│   ├── __init__.py
│   ├── tools.py              # Registre central + dispatch des outils
│   ├── tools.json            # Définitions OpenAI function-calling (générées)
│   ├── code_exec.py          # Exécution sandboxée (Python/Bash/JS)
│   ├── web_search.py         # Recherche web via Serper API
│   ├── social_search.py      # Recherche réseaux sociaux (Twitter/Reddit)
│   ├── github_tools.py       # Opérations GitHub (lecture/écriture repos)
│   ├── mcp.py                # Client MCP pour outils système
│   ├── memory_ops.py         # Opérations mémoire (lecture/écriture SQLite)
│   ├── registry.py           # Registre des outils disponibles
│   ├── skills_manager.py     # Gestion des skills (création/chargement)
│   ├── guardian.py           # Garde-fous (vérifications pré-exécution)
│   ├── vm_security.py        # Sécurité VM (whitelist commandes)
│   ├── youtube.py            # Recherche/analyse YouTube
│   └── cost_governor.py      # Tracking budget token par outil
│
├── memory/                   # Données mémoire persistante
│   ├── livres/               # Livres vectoriels (base de connaissances)
│   ├── registre/             # Registres (personnes, décisions, dates)
│   ├── rendez_vous/          # Échéances et rappels
│   └── flux/                 # Flux d'activité hebdomadaires
│
├── soul/                     # Identité et règles de Santana
│   ├── SOUL.md               # Personnalité et philosophie
│   ├── USER.md               # Profil de l'utilisateur
│   └── RULES.md              # Règles strictes de comportement
│
├── tests/                    # Tests unitaires (pytest)
│   ├── test_system_integrity.py  # Suite de référence (imports, config, outils)
│   ├── test_self.py          # Tests du module self.py
│   ├── test_tools.py         # Tests du registre d'outils
│   ├── test_context.py       # Tests de gestion de contexte
│   ├── test_memory.py        # Tests de la couche mémoire
│   └── test_*.py             # Autres tests unitaires
│
├── scripts/                  # Scripts d'exploitation
│   ├── check_rate_limit.py   # Vérification des limites API via agent.securite
│   └── ...                   # Scripts de maintenance et audit
│
├── docs/                     # Documentation
│   ├── ARCHITECTURE.md       # Ce fichier
│   └── README.md             # Index de la documentation
│
├── .notes/                   # Notes internes préservées
│   ├── INVARIANTS.md         # Invariants système
│   └── EMERGENCY.md          # Procédures d'urgence
│
├── .github/workflows/        # CI/CD
│   └── test.yml              # Pipeline pytest + pytest-cov
│
├── knowledge/                # Base de connaissances
├── requirements.txt          # Dépendances Python
├── pytest.ini                # Configuration pytest
└── .gitignore                # Fichiers ignorés par git
```

## Architecture mémoire — 3 Couches

```
┌──────────────────────────────────────────────────────────────┐
│                    COUCHE BLEUE (Session Buffer)              │
│  Buffer des N derniers échanges (configurable).              │
│  Table SQLite `session_buffer`. Lecture instantanée.        │
│  Pas de recherche vectorielle — accès direct FIFO.           │
├──────────────────────────────────────────────────────────────┤
│                    COUCHE ARGENT (Résumés)                    │
│  Résumé automatique périodique des interactions.              │
│  Clustering sémantique via all-MiniLM (local, gratuit).      │
│  Stocké dans `session_summaries` (SQLite).                   │
├──────────────────────────────────────────────────────────────┤
│                    COUCHE OR (Livres vectoriels)               │
│  Livres vectoriels SQLite + embeddings all-MiniLM.           │
│  Recherche sémantique complète. Écriture condensée.          │
│  Registres CRUD : personnes, dates, décisions.               │
│  Détecteur de conflits (similarité cosinus ≥ 0.85).          │
└──────────────────────────────────────────────────────────────┘
```

**Caractéristiques :**
- Zéro appel LLM pour le clustering mémoire — all-MiniLM local et gratuit
- Écriture limitée (~300 caractères par entrée)
- Dédoublonnage cosinus (threshold 0.85)
- Centralisé via `core/db.py` (get_metrics_db() pour toutes les connexions)
- WAL mode pour performances concurrentes

## Modèle externe

| Usage | Fournisseur | Modèle | Coût |
|-------|-------------|--------|------|
| **LLM Principal** | DeepSeek (direct) | deepseek-v4-flash | $0.14/M input (cache miss), $0.0028/M (cache hit), $0.28/M output |
| **LLM Fallback 1** | Nous/StepFun | step-3.7-flash:free | Gratuit |
| **LLM Fallback 2** | OpenRouter | deepseek/deepseek-v4-flash | $0.14/M input, $0.28/M output |
| **Embeddings** | Local (sentence-transformers) | all-MiniLM-L6-v2 | Gratuit |
| **Recherche web** | Serper API | — | Payant (facturation au hit) |

La chaîne de providers (`core/provider.py`) tente DeepSeek direct en premier. Si DeepSeek échoue (timeout, erreur API, saturation), le fallback tente Nous/StepFun, puis OpenRouter.

## Gouverneur de coûts

`core/cost_governor.py` implémente un budget tracking :

```
record_usage(prompt_tokens, completion_tokens, cached_tokens)
  → Met à jour le compteur cumulé avec les prix réels DeepSeek
  
check_cost_governor(estimated_cost) → OK | ALERT | THROTTLE | STOP
  ALERT   (≥ 80% du budget) : log + notification
  THROTTLE (≥ 95% du budget) : ralentit les appels LLM coûteux
  STOP    (≥ 100% du budget) : bloque tout nouvel appel LLM
```

Budget par défaut : $0.01 (configurable via `DEEPSEEK_COST_LIMIT`).

## Flux de traitement d'un message

```
Message entrant (Telegram / Discord / API)
    │
    ├──→ Provider Chain
    │      1. core/provider.py sélectionne le provider actif
    │      2. Appel LLM avec le message + contexte mémoire
    │
    ├──→ Boucle ReAct (react_loop.py)
    │      1. Analyse du message → plan d'actions
    │      2. Dispatch des outils (tools.py → dispatch)
    │      3. Observation des résultats
    │      4. Nouvel appel LLM avec les observations
    │      5. Itération jusqu'à réponse finale ou limite
    │
    ├──→ Couche Mémoire
    │      • Mise à jour du buffer de session
    │      • Extraction d'entités → écriture livres/registres
    │      • Résumé périodique (toutes les N interactions)
    │      • Détection de conflits
    │
    ├──→ Cost Governor
    │      • record_usage() avec tokens réels
    │      • check_cost_governor() avant chaque nouvel appel LLM
    │
    └──→ Réponse → canal d'origine
```

## Services platformes

| Plateforme | Technologie | État |
|------------|-------------|------|
| **Telegram** | python-telegram-bot | ✅ Production |
| **Discord** | discord.py | ✅ Production |
| **API REST** | Flask | ✅ Production |

## Sécurité

| Mécanisme | Description |
|-----------|-------------|
| **VM Security** | Whitelist des commandes autorisées, patterns dangereux bloqués |
| **Cost Governor** | Budget maximum, arrêt automatique (STOP) si dépassé |
| **Rate Limiting** | Surveillance des appels API via `agent.securite` |
| **Souveraineté** | Vérification que les outils SOCIAL n'exposent pas tous les outils |
| **Audit** | Traçabilité complète via `agent/tracabilite.py` |

## CI/CD

Pipeline GitHub Actions (`.github/workflows/test.yml`) :
- **Étape 1** : Vérification des limites API (`scripts/check_rate_limit.py`)
- **Étape 2** : Tests unitaires avec pytest + pytest-cov (couverture)
- Déclenché sur push et pull request vers `main`

## Tables SQLite

Centralisées dans `core/db.py`, 9 tables créées automatiquement au premier appel :

| Table | Usage |
|-------|-------|
| `agents` | Profils des agents |
| `conversations` | Historique des conversations |
| `memory` | Entrées mémoire vectorielle |
| `skills` | Skills enregistrés |
| `metrics` | Métriques d'utilisation |
| `sessions` | Sessions actives |
| `session_buffer` | Buffer des N derniers échanges |
| `session_summaries` | Résumés de sessions |
| `cost_tracking` | Tracking des coûts LLM |

## Notes sur l'évolution

- **Juin 2026** : Refonte complète du système mémoire (V2), centralisation SQLite
- **Juillet 2026** : Correction P0/P1 (sécurité, outils GitHub, cost governor, CI, delegate_task, self.py)
  - Provider chain corrigée : DeepSeek natif en premier
  - Cost governor branché sur prix réels DeepSeek
  - Documentation nettoyée (archives session supprimées)
