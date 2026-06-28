# Architecture Santana

> Dernière mise à jour : 27 mai 2026 — Refonte Mémoire Vivante V2

## Stack

- **LLM** : DeepSeek V4 Flash (api.deepseek.com)
- **Mémoire persistante** : SQLite WAL + sentence-transformers (all-MiniLM-L6-v2)
- **API** : Flask (PWA backend)
- **Telegram** : python-telegram-bot
- **Navigation web** : Playwright (Chrome CDP, port 5200)
- **MCP** : Server MCP JSON-RPC (outils système sécurisés)
- **Vision** : DeepInfra Qwen3-VL (analyse d'images)

## Services systemd

| Service | Rôle | Port |
|---------|------|------|
| santana-bot | Agent Telegram principal | — |
| santana-api | API REST Flask (PWA) | 5000 |
| santana-mcp | Serveur MCP (outils système) | 5001 |
| santana-chrome | Chrome headless (Playwright) | 5200 |

## Structure du projet

```
santana/
├── santana.py              # Point d'entrée, orchestrateur
├── api.py                  # Backend PWA Flask
├── mcp_server.py           # Serveur MCP JSON-RPC
├── playwright_server.py    # Serveur Playwright (navigateur CDP)
├── deepseek_client.py      # Client API DeepSeek
├── core/
│   ├── react_loop.py       # Boucle ReAct + mémoire 3 couches
│   └── utils.py            # Helpers (env, logging, formatage)
├── atlas_engine/           # Moteur mémoire vectorielle
│   ├── classifier.py       # Classification sémantique locale
│   ├── embeddings.py       # Embeddings all-MiniLM-L6-v2
│   ├── writer.py           # Writer V2 — écriture mémoire (zéro DeepSeek)
│   └── memory_injector.py  # Injection mémoire + détecteur conflits
├── routes/                 # Routes Flask
│   ├── chat.py             # Chat API
│   ├── common.py           # Routes communes
│   ├── files.py            # Gestion fichiers
│   ├── memory.py           # Routes mémoire
│   └── system.py           # Routes système
├── tg_handlers/
│   └── handlers.py         # Handlers Telegram
├── tools/                  # Outils Santana
│   ├── tools.py            # Registre d'outils
│   ├── tools.json          # Définitions OpenAI function-calling
│   ├── mcp.py              # Client MCP
│   ├── vision.py           # Analyse d'images (DeepInfra)
│   └── github_tools.py     # Outils GitHub (lecture/écriture repos)
├── memory/                 # Données mémoire
│   ├── memory.py           # Module mémoire SQLite
│   ├── livres/             # Livres vectoriels (fallback .md)
│   ├── registre/           # Registres (fallback .md)
│   ├── rendez_vous/        # Échéances
│   ├── flux/               # Flux hebdomadaires récents
│   ├── archive/            # Flux archivés (> 7 jours)
│   └── angles_morts/       # Angles morts identifiés
├── soul/                   # Identité Santana
│   ├── SOUL.md             # Personnalité
│   ├── USER.md             # Profil utilisateur
│   └── RULES.md            # Règles de comportement
├── docs/                   # Documentation
│   ├── ARCHITECTURE.md     # Ce fichier
│   ├── MEMOIRE_VIVANTE_V2.md  # Refonte mémoire V2
│   ├── README.md           # Index des docs
│   └── archive/            # Archives historiques
├── tests/                  # Tests unitaires
├── scripts/                # Scripts d'exploitation
└── knowledge/              # Base de connaissances
    ├── ia.md               # Connaissances IA
    └── psychologie.md      # Connaissances psychologie
```

## Architecture Mémoire — 3 Couches (V2)

```
┌─────────────────────────────────────────────────────────┐
│                    COUCHE OR                            │
│  Livres vectoriels (SQLite) + embeddings all-MiniLM    │
│  Recherche sémantique. Écriture condensée (300 chars). │
│  Registres CRUD : personnes, dates, décisions.         │
├─────────────────────────────────────────────────────────┤
│                    COUCHE ARGENT                         │
│  Résumé automatique toutes les 10 interactions.         │
│  Clustering sémantique all-MiniLM (gratuit, local).     │
│  Stocké dans table `session_summaries`.                 │
├─────────────────────────────────────────────────────────┤
│                    COUCHE BLEUE                          │
│  Buffer de session : 20 derniers échanges.              │
│  Table SQLite `session_buffer`.                         │
│  Lecture instantanée, pas de recherche vectorielle.     │
└─────────────────────────────────────────────────────────┘
```

**Changements clés V2 :**
- Zéro appel DeepSeek pour la mémoire — clustering MiniLM local et gratuit
- max_tokens 4000 → 8000
- Détecteur de conflits mémoire intégré
- Écriture limitée à 300 caractères par entrée
- Dédoublonnage cosinus (threshold 0.85)

## Modèle externe

- **Principal** : DeepSeek V4 Flash (api.deepseek.com)
- **Vision** : DeepInfra Qwen3-VL (via API)
- **Embeddings** : sentence-transformers all-MiniLM-L6-v2 (local, gratuit)

## Flux de traitement

```
Message Telegram
    │
    ├──→ Couche Bleue : push session_buffer (20 derniers)
    │
    ├──→ Couche Argent : résumé toutes les 10 interactions
    │
    └──→ Writer V2 : extraction entités → SQLite
            • Détection personnes/dates via regex + MiniLM
            • Détection décisions via marqueurs
            • Détection livre via classifier
            • Écriture SQLite + rebuild index si nécessaire
    │
    └──→ DeepSeek V4 Flash : génération réponse
            • Contexte : session_buffer + résumés + livres pertinents
```

## Sauvegardes

- Git push quotidien (5h00 UTC)
- Backup Telegram quotidien (4h00)
- Snapshots avant modification majeure

Voir [MEMOIRE_VIVANTE_V2.md](MEMOIRE_VIVANTE_V2.md) pour les détails de la refonte mémoire.
Voir `ARCHITECTURE.md` à la racine pour la vue d'ensemble des services.
