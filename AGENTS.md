# AGENTS.md — Règles pour les agents IA travaillant sur Santana

> Inspiré d'Andrej Karpathy. Adapté pour BTR Lab / Black Intelligence.

## 🔴 Règle absolue n°1 : Ne jamais supposer

Si une instruction est ambiguë, incomplète, ou manque de contexte :
→ **Demander clarification** à Serge. Ne pas avancer avec une supposition.

Les suppositions coûtent plus cher que les questions.

## 🔴 Règle absolue n°2 : KISS — Keep It Simple, Santana

- **Ne pas ajouter** d'abstraction, couche, framework, ou dépendance qui n'a pas été explicitement demandée.
- **Ne pas "améliorer"** ce qui fonctionne. Le code vivant a une raison d'être.
- **Ne pas réécrire** pour le plaisir. Un correctif de 3 lignes > une refactorisation de 300 lignes.
- **Préférer** `sqlite3` à SQLAlchemy, `requests` à httpx, `json` à pydantic, sauf si contrainte prouvée.
- **Pas de Docker. Pas de Redis. Pas de Postgres. Pas de GPU.** Ce n'est pas négociable.

## 🔴 Règle absolue n°3 : Scope strict

- **Modifier UNIQUEMENT** ce qui est nécessaire pour la tâche demandée.
- **Ne pas toucher** à `soul/` (IDENTITY.md, SOUL.md, CONDUCT.md, USER.md) sans accord écrit de Serge.
- **Ne pas toucher** à `docs/MEMORY-FROZEN-*.md`, aux fichiers `.frozen`, ni aux backups.
- **Laisser** les commentaires et le style existants. Ne pas "nettoyer" ce qui n'a pas été demandé.
- Si tu vois un bug hors scope pendant ton travail : le **signaler** dans la réponse finale. Ne pas le corriger.

## ⚡ Conventions techniques

| Règle | Valeur |
|---|---|
| **Langage** | Python 3.11+, snake_case, type hints |
| **Commentaires** | Français (sauf docs publiques) — expliquer le *pourquoi*, pas le *quoi* |
| **Tests** | `pytest` dans `tests/`. Toujours passer avant/après modification. |
| **Venv** | `~/santana/venv_new/bin/python3` — JAMAIS python3 global |
| **Service** | `systemctl --user` pour Santana. Jamais `systemctl` seul. |
| **Backup** | Avant modification critique : `cp -r ~/santana ~/santana-backup-$(date +%Y-%m-%d)` |
| **Formatage** | PEP 8, 100 caractères max, pas de `except:` nu, pas de `import *` |
| **Impératif** | Un brief = UNE tâche. Pas 5 en même temps. Finir avant de commencer autre chose. |

## 🧠 Architecture (à respecter)

```
santana.py          → Entry point. NE PAS modifier sans accord.
agent/              → Orchestrateur, planificateur, évaluateur, patterns
atlas_engine/       → Mémoire persistante, embeddings, classification
core/               → React loop, provider chain, cache, DB
tools/              → Web, GitHub, MCP, mémoire, code, VM security
tools/tools.json    → Registre des outils. NE PAS modifier sans accord.
memory/             → Données persistantes (SQLite + fichiers)
soul/               → Identité de Santana. NE PAS modifier sans accord.
docs/               → Documentation publique
skills/             → Compétences Santana (fichiers .md versionnables)
scripts/            → Scripts utilitaires (backup, compile check, etc.)
```

## 🚫 Ce qui est interdit

1. Modifier `soul/` sans accord de Serge
2. Modifier la mémoire frozen (`MEMORY-FROZEN-*.md`)
3. Ajouter des dépendances lourdes (Docker, Redis, PostgreSQL, MongoDB)
4. Créer un frontend web / dashboard / PWA sans demande explicite
5. Utiliser Claude API (DeepSeek Flash seulement — frugalité)
6. Remplacer SQLite par autre chose
7. Supprimer des fichiers sans avoir vérifié les imports et les tests
8. Pusher sur GitHub sans avoir exécuté `python scripts/check_compile.py` et les tests

## ✅ Workflow standard pour une modification

1. **Comprendre** — lire le fichier concerné, comprendre le flux
2. **Planifier** — proposer un plan en 3 étapes max avant de coder
3. **Backup** — `cp -r ~/santana ~/santana-backup-$(date +%Y-%m-%d)`
4. **Modifier** — changer UNIQUEMENT ce qui est nécessaire
5. **Vérifier** — `python scripts/check_compile.py` + tests liés
6. **Tester** — `cd ~/santana && venv_new/bin/python3 -c "import santana"` (pas de crash)
7. **Résumé** — expliquer ce qui a été changé, pourquoi, et ce qui n'a pas changé

## 🔥 Rappel : l'ADN de Santana

- Frugalité absolue : chaque token, chaque outil, chaque dépendance a un coût justifié
- Pas de suppositions, pas de flatterie, pas de bluff
- Signature asymétrique : chaque analyse doit apporter l'angle que personne d'autre n'a
- Tourne sur une VM à 7$/mois — c'est la contrainte de conception
- L'Afrique est le marché cible — pas la Silicon Valley
