# 🧠 Mode Brainstorming — Documentation

## Qu'est-ce que c'est ?

Un mode d'écoute active intégré à Santana. Serge parle, Santana écoute, reformule brièvement, pose des questions ouvertes pour creuser. À la fin, un résumé psychologique et pédagogique est proposé, puis sauvegardé dans CODEX-BRAINSTORM sur GitHub.

## Architecture

```
Telegram ──> handle_message()
               │
               ├── "mode brainstorming" ──> brainstorm_command()
               │                              ├── _BRAINSTORM_MODE = True
               │                              └── Crée /tmp/codex-bs-YYYY-MM-DD.md
               │
               ├── (mode actif) ──> Stocke message dans fichier session
               │                      ├── Appelle DeepSeek (prompt brainstorming)
               │                      ├── Reformulation + question ouverte (2-3 lignes)
               │                      └── Stocke réponse dans fichier session
               │
               └── "stop brainstorming" ──> brainstorm_stop_command()
                                              ├── Lit fichier session
                                              ├── Cherche extraits livres (mémoire vectorielle)
                                              ├── Appelle DeepSeek (résumé 3 parties)
                                              ├── Affiche résumé + proposition enregistrement
                                              └── Si validation → écrit sur GitHub
```

## Flux utilisateur

1. **"mode brainstorming"** → Santana active le mode, répond "🧠 Mode brainstorming activé. Je t'écoute."
2. **Serge parle librement** → Santana écoute, reformule brièvement, pose une question ouverte
3. **"stop brainstorming"** → Santana génère un résumé intelligent (psychologie + idées + conseil)
4. **Validation** → "oui" / "non" / "titre personnalisé"
5. **Sauvegarde** → GitHub dans `CODEX-BRAINSTORM/20-SESSION/`

## Fichiers système

| Fichier | Rôle |
|---|---|
| `/tmp/codex-bs-YYYY-MM-DD.md` | Session temporaire (écrasée à chaque nouveau mode) |
| `tg_handlers/handlers.py` | Handlers brainstorming + résumé |
| `tools/github_tools.py` | Restrictions GitHub (écriture CODEX-BRAINSTORM uniquement) |
| `atlas_engine/embeddings.py` | Recherche vectorielle pour enrichir le résumé |

## Prompts (3 styles alternés)

Pendant la session, Santana alterne entre 5 styles de réponse pour éviter la répétition :

1. Reformulation + question ouverte
2. Validation courte + invitation à approfondir
3. Lien avec un message précédent
4. Opposition douce ("Et si au contraire...")
5. Résumé de l'émotion dominante

## Ton

- Informel mais respectueux
- Tutoiement
- Bienveillance forte
- Emojis discrets
- Jamais "mon pote" ou familiarité excessive

## Résumé final (3 sections)

1. **Analyse personnelle** — ce qui se cache derrière les mots (peurs, envies, blocages)
2. **Idée ou décision** — ce qui émerge de la session
3. **Conseil** — une suggestion simple et humaine

## Restrictions

- Santana ne peut écrire que dans `CODEX-BRAINSTORM` (plus dans Notes-BTR, santana, etc.)
- Uniquement via `tool_github_write` — pas d'accès direct aux autres repos

## Sessions sauvegardées

- Format : `20-SESSION/YYYY-MM-DD-HHMM-titre.md`
- Contenu : l'intégralité de la conversation
- Récupérables via `/codex` (liste) et `/lire session` (contenu)

## Dépendances

- DeepSeek V4 Flash (modèle par défaut)
- DeepSeek API (appels reformulation + résumé)
- Atlas Engine (recherche vectorielle dans les livres)
- SSH key `github_obsidian` (accès GitHub)
