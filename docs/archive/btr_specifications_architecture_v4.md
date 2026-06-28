# Spécifications d'Architecture Santana — V4

*Document technique centralisé — Mai 2026*
*Auteur : Serge*
*Statut : SEULE source de vérité sur l'état actuel du code et de la maturité*

---

## Table des Matières

1. [Architecture Globale](#1-architecture-globale)
2. [Stack Technique Détaillé](#2-stack-technique-détaillé)
3. [Le Cœur : React Loop](#3-le-cœur-react-loop)
4. [La Mémoire Vivante](#4-la-mémoire-vivante)
5. [Services & Infrastructure](#5-services--infrastructure)
6. [Mécanismes de Résilience](#6-mécanismes-de-résilience)
7. [Sécurité](#7-sécurité)
8. [Décisions Architecturales (ADR)](#8-décisions-architecturales-adr)
9. [Audit de Maturité — 16/20](#9-audit-de-maturité--1620)
10. [Anomalies Actives](#10-anomalies-actives)
11. [Annexe : Feuille de Route Technique](#11-annexe-feuille-de-route-technique)

---

## 1. Architecture Globale

### Diagramme d'Architecture

Le système Santana suit une architecture **modulaire à 4 couches** :

```
┌─────────────────────────────────────────────────────────────┐
│                    INTERFACE (Telegram)                      │
│              python-telegram-bot · Handlers                   │
├─────────────────────────────────────────────────────────────┤
│                  ORCHESTRATEUR (ReAct Loop)                   │
│         react_loop() · tool dispatch · context window         │
├─────────────────────────────────────────────────────────────┤
│    ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│    │  DeepSeek │ │ Mémoire  │ │  Outils  │ │  Services│     │
│    │  V4 Flash │ │ Vivante  │ │ (MCP +   │ │ (Flask,  │     │
│    │  (API)    │ │ (SQLite) │ │  natifs)  │ │  MCP)    │     │
│    └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
├─────────────────────────────────────────────────────────────┤
│                  INFRASTRUCTURE (systemd)                     │
│   Santana · Santana-api · Santana-mcp · Santana-playwright       │
├─────────────────────────────────────────────────────────────┤
│                  HÉBERGEMENT (GCP → Oracle)                  │
│              Ubuntu 24.04 · 4 vCPU · 16 Go RAM                │
└─────────────────────────────────────────────────────────────┘
```

### Flux d'une Requête Typique

```
1. Utilisateur envoie un message Telegram
2. Handler Telegram reçoit le message
3. react_loop() construit le contexte :
   - Messages récents (6 derniers)
   - Mémoire narrative (Registre + Livres pertinents)
   - Résultats d'outils en cours
4. Appel à DeepSeek V4 Flash (api.deepseek.com)
5. Réponse parsée : actions outils ou réponse directe
6. Si actions outils → exécution → rebouclage (max 6 itérations)
7. Réponse finale envoyée à l'utilisateur
8. Sauvegarde dans les Flux + mise à jour mémoire
```

### Principes Architecturaux

1. **Immutable Core** — le moteur Python fait ~400 lignes, quasi immuable. Logique variable externalisée dans des fichiers Markdown (soul/SOUL.md, skills/*.md)
2. **Services isolés** — 4 services systemd séparés. Panne d'un service ≠ panne générale
3. **Fail-Soft** — chaque outil est wrappé dans try/except. Outil down != agent down
4. **Mobile-first** — architecture pensée développement/maintenance depuis un smartphone
5. **Frugalité** — stack à ~3.33€/mois. Pas de GPU, pas de microservices

---

## 2. Stack Technique Détaillé

### LLM & IA

| Composant | Technologie | Version | Justification |
|-----------|-------------|---------|---------------|
| LLM Principal | DeepSeek V4 Flash | deepseek-chat | Meilleur ratio qualité/coût. Images illimitées |
| API Endpoint | api.deepseek.com/v1/chat/completions | — | Direct, pas d'intermédiaire |
| Moteur mémoire | sentence-transformers | all-MiniLM-L6-v2 | 384 dims, 192MB RAM CPU |
| Vision (fallback) | Groq | — | Uniquement pour les images |
| Audio/Voice | faster-whisper | Lazy loading | Chargé à la demande |
| Architecture agent | ReAct (Reasoning + Acting) | Custom | Boucle raisonnement-action |

### Backend & Base de Données

| Composant | Technologie | Justification |
|-----------|-------------|---------------|
| Runtime | Python 3.12 | Stable, écosystème large |
| BDD Mémoire | SQLite WAL | Léger, pas de serveur |
| Web Framework | Flask | Léger, suffisant pour La Forge |
| PWA Interface | La Forge (Flask + HTML/JS) | Design BTR complet |

### Réseau & Communication

| Composant | Technologie | Justification |
|-----------|-------------|---------------|
| Messagerie | Telegram Bot API | Gratuit, fiable, interface mobile |
| Navigation web | Playwright | Service isolé port 5200 |
| Recherche web | Serper API | ~0.50€/mois, rapide |
| MCP Server | Custom Shell MCP | Lazy loading, health-check, circuit breaker |

### Infrastructure

| Composant | Actuel (GCP) | Cible (Oracle) |
|-----------|--------------|----------------|
| CPU | 4 vCPU (x86) | 4 vCPU (ARM Ampere A1) |
| RAM | 16 Go | 24 Go |
| Disque | 48 Go (limité) | 200 Go (allouable) |
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS |
| Coût | Gratuit (expire 11/07) | Gratuit à vie |
| Orchestration | systemd (4 services) | systemd (4 services) |

---

## 3. Le Cœur : React Loop

### Architecture du React Loop

```python
def react_loop(user_message, force_tool=None):
    1. Construire le contexte : système + historique + mémoire
    2. Appeler DeepSeek API (streaming)
    3. Analyser la réponse :
       a. Si outil détecté (<tool_call>...) :
          - Extraire nom et arguments
          - Exécuter l'outil
          - Ajouter résultat au contexte
          - Reboucler (retour en 2)
       b. Si réponse directe :
          - Envoyer à l'utilisateur
          - Sauvegarder dans les Flux
    4. Si > max_iterations (6) → forcer réponse
    5. Gérer les erreurs : mode dégradé si DeepSeek down
```

### Fonctionnalités du React Loop

| Fonctionnalité | Description | Statut |
|---------------|-------------|--------|
| Streaming | Réponses en temps réel via Telegram | ✅ |
| Tool calling | Détection et exécution d'outils | ✅ |
| Iterations limit | Max 6 itérations anti-boucle | ✅ |
| Mode dégradé | Outils réduits si DeepSeek down | ✅ |
| Context troncation | Troncature à ~20K tokens si débordement | ✅ |
| Strip DSML | Nettoyage des balises DSML | ✅ |
| Memory injection | Mémoire narrative dans le contexte | ✅ |

### Outils Disponibles

| Outil | Description | Source |
|-------|-------------|--------|
| web_search | Recherche web via Serper API | Natif |
| memory_query | Recherche sémantique dans les Livres (embeddings) | Natif |
| get_datetime | Date et heure actuelles | Natif |
| web_navigate | Navigation web via Playwright (service isolé) | MCP |

---

## 4. La Mémoire Vivante

### Architecture de la Mémoire

```
┌──────────────────────────────────────────────────┐
│                 LA MÉMOIRE VIVANTE                 │
├──────────────────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────┐ │
│ │ Registre │ │  Livres  │ │  Flux    │ │Angles│ │
│ │ (faits   │ │ (récits  │ │ (semaine │ │Morts │ │
│ │ stables) │ │thématiques│ │ en cours)│ │(lacunes│
│ └──────────┘ └──────────┘ └──────────┘ └──────┘ │
│                                                    │
│              Embedding Vectoriel                    │
│         sentence-transformers (384 dims)            │
│              Recherche sémantique                    │
└──────────────────────────────────────────────────┘
```

### Les 5 Composants

#### 📜 Le Registre
- **Stockage :** Fichier YAML/JSON versionné
- **Contenu :** Faits personnels (nom, préférences, décisions), horodatés et révisables
- **Taille :** < 100 entrées
- **Usage :** Injecté dans le contexte à chaque interaction

#### 📖 Les Livres
- **Stockage :** Documents Markdown dans ~/Santana/memory/books/
- **Contenu :** Récits thématiques (vision_btr.md, relations.md, apprentissages.md)
- **Limite :** 300 lignes actives par Livre. Rotation automatique
- **Embeddings :** Chunkés et vectorisés (sentence-transformers). ~70 chunks, 384 dimensions
- **Recherche :** Cosine similarity → top 3 résultats

#### 🌊 Les Flux
- **Stockage :** SQLite (memory.db)
- **Contenu :** 500 entrées de conversation maximum. Rotation FIFO
- **Usage :** Buffer de travail — les N derniers messages

#### 👻 Les Angles Morts
- **Stockage :** Fichier Markdown
- **Contenu :** Lacunes d'information (statut : Actif / Investigé / Résolu)
- **Objectif :** Santana sait ce qu'il ne sait pas

#### 📅 Les Rendez-vous
- **Mécanisme :** Timers systemd
- **Usage :** Suivis programmés, vérifications périodiques

### Pipeline Mémoire

```
1. Nouvelle conversation
2. Sauvegarde dans les Flux (SQLite, max 500)
3. Analyse du contenu :
   - Faits stables → Registre
   - Récits thématiques → Livres (avec embedding vectoriel)
   - Lacunes identifiées → Angles Morts
4. Consolidation hebdomadaire :
   - Flux → Livres (résumé)
   - Anciens Livres → Archive
5. Rotation si dépassement des limites
```

### Limites Mémoire (Testées Empiriquement)

| Limite | Valeur | Raison |
|--------|--------|--------|
| `rotate_memory()` | 500 entrées | Au-delà → contexte LLM trop lourd |
| Livres Markdown | 300 lignes actives | Au-delà → embeddings moins précis |
| Crash snapshots | 5 fichiers max | Au-delà → dérive disque |
| Context window | 6 messages + 8KB mémoire | Équilibre qualité/coût DeepSeek |

---

## 5. Services & Infrastructure

### Services systemd Actifs

| Service | Rôle | Port | Redémarrage |
|---------|------|------|-------------|
| Santana.service | Bot Santana principal — React Loop, handlers Telegram | — | always (5s delay) |
| Santana-api.service | API Flask — La Forge, endpoints /status, /memory, /chat | 5000 | always |
| Santana-mcp.service | MCP Server — navigation web, shell commands | — | always |
| Santana-playwright.service | Playwright — navigation web isolée | 5200 | always |

### Services Masqués/Inactifs

| Service | Raison | Action |
|---------|--------|--------|
| Santana-console.service | Console exposée sur le réseau | 🔒 Masqué (à supprimer) |
| Santana-rendez-vous.service | Rituel désactivé (Phase D supprimée) | ❌ Désactivé |
| Santana-veillee.service | Rituel désactivé (Phase D supprimée) | ❌ Désactivé |

**Règle :** Ne pas démasquer Santana-console. Ne pas réactiver les rituels.

### Mécanismes de Résilience

#### 🛡️ Mode Dégradé
- **Déclencheur :** DeepSeek API inaccessible (timeout, HTTP 500, erreur réseau)
- **Comportement :** Santana répond avec outils réduits. Message : "Je suis en mode dégradé"
- **Rétablissement :** Automatique dès que DeepSeek redevient accessible

#### ⚡ Circuit Breaker MCP
- **Seuil :** 3 échecs consécutifs du MCP Server
- **Action :** Circuit ouvert — arrêt des appels MCP pendant 30 secondes
- **Rétablissement :** Demi-ouverture après 30s. Si succès → circuit fermé

#### ❤️ Health-Check MCP
- **Fréquence :** Ping toutes les 30 secondes
- **Action si down :** Tentative de redémarrage automatique

#### 📸 Crash Snapshots
- **Déclencheur :** Crash du processus Santana
- **Stockage :** Copie de Santana.py + memory.db horodatée
- **Limite :** 5 snapshots max. Cron de nettoyage toutes les 30 minutes

---

## 6. Sécurité

| Mesure | Description | Statut |
|--------|-------------|--------|
| .env protégé | chmod 600, jamais dans le chat ni les logs | ✅ |
| TokenFilter | Token Telegram masqué dans tous les logs | ✅ |
| .gitignore | Cache, venv, snapshots, .env exclus du repo | ✅ |
| SSH key only | Pas de mot de passe SSH | ✅ |
| UFW firewall | Ports 22, 5000, 5200 uniquement | ✅ |
| Console masquée | Console service masqué (risque fuite) | 🔒 Masqué |
| Rate limiter | Limite de messages par intervalle anti-spam | ✅ |
| PID lock | Empêche les doubles instances du bot | ✅ |

### Secrets et Variables d'Environnement

```
TELEGRAM_TOKEN    → Bot Telegram      (jamais dans chat/logs)
CONSOLE_TOKEN     → Console (masqué)   (à supprimer)
DEEPSEEK_KEY      → API DeepSeek       (chmod 600)
GROQ_KEY          → API Groq (vision)  (chmod 600)
GROQ_MODEL        → Modèle Groq
SERPER_KEY        → API Serper (web)   (chmod 600)
CHAT_ID           → ID chat autorisé
```

---

## 7. Décisions Architecturales (ADR)

Chaque décision documentée avec son contexte, les alternatives considérées et la solution retenue.

### ADR 1 : DeepSeek plutôt qu'OpenRouter/Groq/Gemini
- **Contexte :** OpenRouter trop cher, Groq quotas épuisés, Gemini quotas épuisés, Mistral qualité insuffisante
- **Solution :** DeepSeek V4 Flash direct (api.deepseek.com, modèle deepseek-chat)
- **Conséquence :** Invariant critique : chaque message doit avoir "role" explicite (sinon 400 Bad Request)

### ADR 2 : Telegram plutôt que PWA
- **Contexte :** La Forge (Flask PWA) construite puis supprimée le 16/05/2026
- **Solution :** Interface 100% Telegram. Commandes /help, /statut, /lire
- **Justification :** Serge sur smartphone. Telegram plus rapide, plus fiable, pas de maintenance web

### ADR 3 : sentence-transformers plutôt que TF-IDF
- **Contexte :** TF-IDF testé en premier — pertinence ~7-8%
- **Solution :** all-MiniLM-L6-v2 (384 dims, 192MB RAM CPU). Pertinence 31%
- **Conséquence :** torch CPU suffisant. Version GPU (1.2G+) désinstallée

### ADR 4 : Limites mémoire empiriques
- **Limites :** 500 entrées, 300 lignes/Livre, 5 snapshots, 6 messages + 8KB contexte
- **Justification :** Testées empiriquement. Au-delà, qualité dégradée

### ADR 5 : Rituels et Disciplines supprimés
- **Date :** 16 mai 2026. Code supprimé
- **Raison :** Trop complexe pour l'usage réel. Non utilisé par Serge
- **Règle :** Ne pas recréer

### ADR 6 : generate_pdf supprimé
- **Raison :** Non utilisé dans la pratique. Dépendance inutile
- **Résidu :** Référence dans Santana.py (~lignes 98, 339, 343) à nettoyer

### ADR 7 : Architecture des services systemd
- **Configuration :** 4 services actifs, 3 masqués/désactivés
- **Règles :** Ne pas démasquer console, ne pas réactiver rituels

### ADR 8 : Migration Oracle (deadline)
- **Contexte :** GCP expire. Disque 48G limité
- **Plan :** Oracle Free Tier (prio 1), Hetzner ~5€ (plan B), GCP payant ~6€ (plan C)
- **Deadline :** 11 juillet 2026 — non négociable

### ADR 9 : OpenClaw différé
- **Règle :** Aucun travail sur plateforme vendable avant migration Oracle

---

## 8. Audit de Maturité — 16/20

> *[Cette section est la SEULE source de vérité sur les scores d'audit. Les autres documents ne contiennent qu'une mention macro de la progression.]*

### Score Global

- **Score actuel :** 16.0 / 20
- **Score initial :** 12.1 / 20
- **Progression :** +3.9 points
- **Correctifs appliqués :** 35

### Radar de Maturité — 6 Dimensions

| Dimension | Score | Pourcentage | Commentaire |
|-----------|-------|-------------|-------------|
| 🔒 Sécurité & Données | 18/20 | 90% | .env protégé, TokenFilter, .gitignore. Bonne hygiène proportionnée |
| 🛡️ Stabilité & Robustesse | 17/20 | 85% | Mode dégradé, circuit breaker, health-check, try/except sur chaque outil |
| 🏗️ Architecture & Modularité | 16/20 | 80% | Refactor core/ fait, lazy MCP, imports normalisés. Structure claire |
| 📚 Documentation | 15/20 | 75% | ADR 13p, DECISIONS.md, audits, guides. Bon mais dispersé |
| 🧠 Mémoire & Contexte | 14/20 | 70% | Mémoire vectorielle, pertinence 31%, limite 500 entrées |
| 🧪 Tests & Qualité | 13/20 | 65% | 74 tests, 23 nouveaux. 3 échecs préexistants. Couverture partielle |

### Top 3 Forces

1. **Sécurité : 18/20** — .env chmod 600, TokenFilter dans les logs, .gitignore, crash snapshots limités. Bonne hygiène de sécurité proportionnée aux risques
2. **Stabilité : 17/20** — Mode dégradé, health-check MCP, circuit breaker, try/except sur chaque outil. Le système ne tombe jamais complètement
3. **Architecture : 16/20** — Refactor en core/services/channels/tools réussi, lazy loading, imports normalisés. La structure est claire et maintenable

### Top 3 Faiblesses

1. **Tests : 13/20** — 3 tests échouent (sentence-transformers absent de l'env de test). Couverture encore partielle, pas de CI
2. **Mémoire : 14/20** — Pertinence 31% des embeddings, limité à 500 entrées. La mémoire narrative est fonctionnelle mais pas encore "intelligente"
3. **Infrastructure : 12/20** — GCP Cloud Shell va expirer (deadline 11/07/2026). Pas de backup automatisé complet, disque limité à 48G

### Détail des 6 Dimensions

#### 🔒 Sécurité & Données (18/20 — +5 pts depuis l'audit initial)

**Points forts :**
- .env chmod 600, jamais dans le chat, jamais dans les logs
- TokenFilter masque le token Telegram dans tous les logs
- .gitignore exclut cache, venv, snapshots, .env
- SSH key only, UFW firewall restrictif
- PID lock empêche les doubles instances

**Points faibles :**
- console.py encore masqué (pas supprimé) — pourrait être une surface d'attaque
- Pas d'audit de sécurité externe

#### 🛡️ Stabilité & Robustesse (17/20 — +6 pts)

**Points forts :**
- Mode dégradé : DeepSeek down → Santana répond avec outils réduits
- Circuit breaker MCP : 3 échecs → arrêt 30s
- Health-check MCP : ping toutes les 30s
- Crash snapshots : backup auto en cas de crash, limite 5 fichiers

**Points faibles :**
- Pas de monitoring externe (UptimeRobot, Healthchecks.io)
- Redémarrage quotidien nécessaire pour contourner un bug python-telegram-bot

#### 🏗️ Architecture & Modularité (16/20 — +4 pts)

**Points forts :**
- Architecture 4 couches (Interface → Orchestrateur → Services → Infrastructure)
- Services systemd isolés : 1 panne ≠ tout le système
- Lazy loading MCP : chargé à la demande
- Imports normalisés (from core.x import...)

**Points faibles :**
- Des doublons persistent entre Santana.py et api.py (variables base/allowed — NEW1)
- Refactor du cœur partiel : certains modules encore dans Santana.py

#### 📚 Documentation (15/20 — +5 pts)

**Points forts :**
- ADR complet (13 pages)
- DECISIONS.md avec 12 décisions documentées
- Rapports d'audit, guides, runbooks

**Points faibles :**
- Documentation dispersée entre plusieurs fichiers
- Pas de site centralisé
- AGENT_RULES.md orienté Hermès-agent, utile mais spécifique

#### 🧠 Mémoire & Contexte (14/20 — +3 pts)

**Points forts :**
- Mémoire vectorielle opérationnelle (sentence-transformers, 384 dims)
- Pipeline de consolidation : Flux → Livres → Archive
- Rotation automatique à 500 entrées

**Points faibles :**
- Pertinence des embeddings à 31% (cible : 50%+)
- Chunking sémantique pas encore optimisé
- TF-IDF abandonné mais code résiduel possible

#### 🧪 Tests & Qualité (13/20 — +3 pts)

**Points forts :**
- 74 tests unitaires (23 nouveaux dans le Cycle 3)
- Tests de deepseek_client et memory_steward

**Points faibles :**
- 3 tests échouent (sentence-transformers absent de l'environnement de test)
- Pas de CI (GitHub Actions)
- Couverture partielle — pas de tests d'intégration ni de stress

---

## 9. Anomalies Actives

Problèmes identifiés, non bloquants, suivis en priorité. **Ce document est la seule source de suivi des anomalies.**

| ID | Description | Gravité | Solution prévue |
|----|-------------|---------|-----------------|
| C3 | execute_tool dispatcher — certains outils ne passent pas par le bon chemin | 🟡 Moyenne | Refactor du dispatcher dans Phase B finalisée |
| NEW1 | Variables base/allowed Flask dupliquées dans Santana.py et api.py | 🟡 Moyenne | Centraliser dans un fichier config partagé |
| NEW2 | .gitignore manquant historiquement — repo pollué | 🟢 Faible | ✅ Résolu le 19/05 |
| NEW4 | console.py en mode dev — exposé sur le réseau | 🔴 Haute | Service masqué, à supprimer en prochaine session |
| MEM1 | Pertinence embeddings à 31% — doit monter à 50%+ | 🟡 Moyenne | Optimisation du chunking, chunking sémantique |
| DISK1 | Disque 48G GCP — structurellement limité | 🔴 Haute | Migration Oracle — deadline 11/07 |

### ⚠️ Risque Opérationnel Majeur

**Deadline cloud : 11 juillet 2026.** GCP Cloud Shell prend fin. Si la migration Oracle n'est pas faite à temps, Santana perd son infrastructure.

**Blocage :** Aucun travail sur Phase G (OpenClaw) avant cette migration.

---

## 10. Annexe : Feuille de Route Technique

### 🔴 Phase H — Migration Oracle (deadline : 11/07/2026)

**Objectif :** Quitter GCP Cloud Shell avant expiration.
**Durée :** 3 sessions (~5h total).
**Risque si échec :** Perte d'infrastructure, Santana hors ligne.
**Blocage :** Toute autre phase bloquée.

### 🟡 Améliorations Techniques Prioritaires

- **Mémoire :** Optimiser le chunking des Livres (70 chunks → chunking sémantique par paragraphe)
- **Tests :** Ajouter sentence-transformers à l'env de test (corrige les 3 échecs)
- **CI :** GitHub Actions → pytest automatique à chaque push
- **Cleanup :** Supprimer console.py, centraliser base/allowed Flask
- **MCP :** Ajouter plus d'outils (emails, agenda, CRM)

### 🟢 Vision Long Terme

- **Phase G :** Santana Marketing — création de contenu et analyse de marché
- **L'Exécuteur :** Sous-agent MCP + Playwright complet, mémoire professionnelle dédiée
- **OpenClaw :** Plateforme multi-agents, héritage YAML du noyau Santana
- **Multi-tenant :** Architecture agent par client, isolation complète

---

*Document généré le 21 mai 2026. Source unique de vérité sur l'architecture et la maturité du code.*
*Bad Technology Research — "For the ones who feel."*
