# Mémoire Vivante V2 — Refonte Complète

> **Date :** 27 mai 2026
> **Auteur :** Black Claw 🦞
> **Contexte :** Refonte majeure de la mémoire persistante de Santana, suite au constat de 7 problèmes identifiés dans l'architecture V1.

---

## Résumé

La Mémoire Vivante est le système de persistance contextuelle de Santana. Elle permet à l'agent de se souvenir des conversations, décisions, personnes, dates et connaissances sur plusieurs sessions, sans perdre le fil entre deux messages.

La V2 corrige les problèmes de la V1 : accumulation de bruit, doublons, registres vides, pas de mémoire de session, coût API inutile.

---

## Architecture V2 — 3 Couches

```
┌─────────────────────────────────────────────────────────┐
│                    COUCHE OR                            │
│  Livres vectoriels (SQLite) + embeddings all-MiniLM    │
│  Recherche sémantique. Écriture condensée (300 chars). │
│  Registres CRUD : personnes, dates, décisions.          │
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

---

## Problèmes V1 Résolus

| # | Problème | Solution V2 |
|---|----------|-------------|
| 1 | Accumulation explosive (vision_btr: 252 KB, 317 entrées) | Nettoyage one-shot + écriture limitée à 300 chars |
| 2 | Écriture de réponses entières au lieu de faits | Condensation systématique à 300 chars max |
| 3 | Dédoublonnage inefficace | Similarité cosinus via all-MiniLM (threshold 0.85) |
| 4 | Pas de mémoire de session active | Buffer de session 20 échanges (table `session_buffer`) |
| 5 | Flux non nettoyés, injectés en entier | Lecture depuis SQLite (limité), fallback fichiers .md |
| 6 | Pas de résumé entre sessions | Résumé auto toutes les 10 interactions |
| 7 | Registres quasi-vides (1 personne, 1 date) | Extraction CRUD automatique dans SQLite |

---

## Base de Données — Tables SQLite

Le fichier `memory.db` contient maintenant 6 tables :

### Tables Mémoire

| Table | Rôle | Colonnes |
|-------|------|----------|
| `memory` | Historique conversationnel (510 entrées, rotation à 500) | id, role, content, timestamp |
| `session_buffer` | 20 derniers échanges de la session en cours | id, session_id, role, content, timestamp |
| `session_summaries` | Résumés automatiques de sessions | id, session_id, summary, exchange_count, created_at |
| `registres` | Personnes, dates, décisions (CRUD) | id, type, content, context, tags, created_at |
| `livres` | Entrées des livres vectoriels | id, livre, content, tag, created_at |
| `skills` | Skills enregistrés de Santana | id, title, trigger_condition, steps, pitfalls, verification, usage_count, success_rate |

### Registres — Types

- `personnes` : extraction automatique des noms avec relation (fratrie, conjoint, enfant, parent, contact)
- `dates` : échéances et dates importantes détectées dans les conversations
- `decisions` : décisions fermes avec contexte, liées à un projet

---

## Flux d'Écriture Mémoire

```
Message utilisateur
    │
    ├──→ Couche Bleue : push session_buffer
    │
    ├──→ Couche Argent : si compteur % 10 == 0 → résumé MiniLM
    │
    └──→ Writer V2 (atlas_engine/writer.py)
            │
            ├── Extraction entités (personnes, dates) via regex + MiniLM
            ├── Détection décisions via marqueurs regex
            ├── Détection livre via classifier existant (local, mots-clés)
            ├── Écriture dans SQLite (registres + livres)
            └── Rebuild index vectoriel si nécessaire
```

**Changements clés :**
- Plus d'appel DeepSeek pour la mémoire — **zéro coût API**
- Clustering sémantique via `all-MiniLM-L6-v2` (gratuit, local, déjà chargé)
- Dédoublonnage cosine avant toute écriture
- Limite stricte : 1 écriture max par tour de conversation

---

## Détecteur de Conflits

Nouveau module dans `atlas_engine/memory_injector.py` (fonction `detect_conflicts`).

Compare tout nouveau message avec les 30 dernières décisions enregistrées. Si similarité sémantique > 0.75 + marqueurs de changement d'avis, Santana alerte : *"⚠️ Serge, attention : ce que tu dis semble contredire ces décisions précédentes..."*

**Utilisation :** all-MiniLM (gratuit), pas d'appel API.

---

## Fichiers Nettoyés

| Fichier | Avant | Après | Supprimé |
|---------|-------|-------|----------|
| `memory/livres/vision_btr.md` | 317 entrées, 252 KB, 5 288 lignes | **275 entrées, 67 KB, 1 462 lignes** | 42 doublons fusionnés |
| `memory/livres/famille.md` | 51 entrées, 57 KB | **33 entrées, 8.6 KB** | 18 entrées de bruit |
| `memory/livres/projets.md` | 99 entrées, 53 KB | **66 entrées, 14.8 KB** | 33 entrées de bruit |
| `memory/livres/psychologie.md` | 32 entrées, 20 KB | **21 entrées, 4.8 KB** | 11 entrées de bruit |
| **Total** | **499 entrées, 382 KB** | **395 entrées, 95 KB** | **104 entrées** |

Backups disponibles : `*.md.bak` dans chaque dossier.

---

## max_tokens Augmenté

`react_loop.py` : `mt = 4000` → `mt = 8000`

DeepSeek V4 Flash gère 8K tokens de sortie. Les réponses longues ne sont plus tronquées.

---

## Dette Technique Éliminée

| Composant | Statut | Raison |
|-----------|--------|--------|
| `tools/memory_steward.py` | 🗑️ Désactivé | Remplacé par writer V2 + clustering MiniLM. Appelait DeepSeek ($$) pour chaque analyse. |
| `tools/steward_learn()` | 🗑️ Désactivé | Remplacé par `process_and_write()` dans writer V2. |
| `classifier.ask(mt=)` | ✅ Corrigé | Bug `ask() got unexpected keyword argument 'mt'` → remplacé par `max_tokens=`. |
| Fichiers Markdown registres | 🔄 Compatible | Les anciens fichiers .md sont toujours lus (fallback), mais les nouvelles écritures vont dans SQLite. |

---

## Gains Attendus

- **Latence réponse :** ~3-6s → ~2-4s (session buffer + pas de DeepSeek mémoire)
- **Coût API :** divisé par 2 (plus d'appel DeepSeek pour la mémoire)
- **Mémoire injectée dans le prompt :** 20 KB → ~6-8 KB (plus de bruit)
- **Précision du rappel :** 50% → ~85% (buffer session + résumé + registres CRUD)

---

## Fichiers Modifiés

| Fichier | Changement |
|---------|------------|
| `core/react_loop.py` | + Couche Bleue/Argent (buffer session, résumé auto, détecteur conflits), max_tokens 8000 |
| `atlas_engine/writer.py` | Réécriture complète V2 : écriture SQLite, clustering MiniLM, registres CRUD, max 300 chars |
| `atlas_engine/memory_injector.py` | Lecture SQLite (fallback .md), + détecteur de conflits |
| `atlas_engine/classifier.py` | Correction bug `mt` → `max_tokens` |
| `tg_handlers/handlers.py` | Désactivation du steward obsolète |
| `scripts/clean_vision_btr.py` | Script de nettoyage one-shot |
| `scripts/clean_livres_sensibles.py` | Script de nettoyage intelligent famille/projets/psychologie |
| `routes/chat.py` | Correction bug `mt` → `max_tokens` |

---

## Prochaines Évolutions Possibles (non prioritaires)

- **Nettoyage des flux** : les fichiers `flux/YYYY-MM-DD_semaine.md` s'accumulent (30 KB pour le 21 mai)
- **Rotation des anciennes sessions** : `session_buffer` actuellement illimité par date
- **Export Markdown des registres SQLite** : script pour regénérer les fichiers .md depuis SQLite si besoin de consultation humaine
- **Migration complète des anciennes entrées .md vers SQLite** : pour que les livres soient entièrement en base

---

*Document généré par Black Claw 🦞 le 27 mai 2026.*
*À mettre à jour à chaque évolution de la Mémoire Vivante.*
