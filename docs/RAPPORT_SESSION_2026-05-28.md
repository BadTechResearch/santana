# 📋 Rapport de session — 28 mai 2026

## Refonte complète du mode brainstorming + nettoyage Santana

---

### Contexte

Serge a testé Santana et identifié plusieurs incohérences : compteurs d'outils divergents entre `/start` et `/statut`, outils morts déclarés mais non fonctionnels, absence de mode brainstorming dédié, livres mémoire en désordre (Vision BTR fourre-tout de 1462 lignes), et dépendance à Notes-BTR (appelé à disparaître).

Décision : créer un espace brainstorming dédié, détaché de BLACK-INTELLIGENCE et de Notes-BTR.

---

### 1. Création de CODEX BRAINSTORM

**Problème :** Santana écrivait partout (Notes-BTR, santana, obsidian-vault-btr). Pas d'espace dédié au brainstorming.

**Solution :**
- Création du repo `BadTechResearch/CODEX-BRAINSTORM`
- Structure à 6 dossiers : INBOX, IDEA, SESSION, DECISION, REFERENCE, ARCHIVE
- `INDEX.md` sommaire vivant
- `README.md` guide d'utilisation

**Fichiers :** Nouveau repo GitHub
**Commit :** `2626257` (structure initiale), `ca8739e` (documentation)

---

### 2. Restrictions GitHub (write/list/read)

**Problème :** Santana pouvait lire/écrire dans n'importe quel repo GitHub (santana, Notes-BTR, obsidian-vault-btr). Risque de modification accidentelle.

**Solution :**
- `github_write` refuse toute écriture hors de `CODEX-BRAINSTORM`
- `github_read` ne lit que dans `CODEX-BRAINSTORM`
- `github_list_files` idem
- `github_list_repos` n'affiche que CODEX-BRAINSTORM
- Cache GitHub nettoyé : Notes-BTR et obsidian-vault-btr supprimés

**Fichier :** `tools/github_tools.py`
**Commits :** `22a4fcd`, `be8aff3`, `9b0b8ec`

---

### 3. Nettoyage des stubs d'outils

**Problème :** 5 outils déclarés dans `tools.json` mais non implémentés (firecrawl_crawl, wikidata_query, libretranslate, world_news_api, nager_date). Les stubs retournaient "pas encore implémenté".

**Solution :**
- Suppression des 5 entrées dans `tools.json`
- Suppression des 5 fonctions stubs dans `tools/tools.py`
- Passage de 18 à 13 outils fonctionnels

**Fichiers :** `tools/tools.json`, `tools/tools.py`
**Commits :** `22a4fcd`

---

### 4. Alignement /start et /statut

**Problème :** `/start` affichait 8 outils (liste en dur), `/statut` affichait 4 outils (comptage différent). Informations contradictoires.

**Solution :**
- Les deux commandes utilisent désormais le comptage dynamique via `TOOLS`
- Liste générée automatiquement à partir de `tools.json`

**Fichier :** `tg_handlers/handlers.py`
**Commits :** `22a4fcd`, `be8aff3`

---

### 5. Mode brainstorming V1 — structure de base

**Problème :** Aucun mode brainstorming n'existait. Serge devait parler normalement, aucune capture organisée.

**Solution :**
- Commande `mode brainstorming` (texte libre)
- Création fichier session temporaire `/tmp/codex-bs-YYYY-MM-DD.md`
- Stockage des messages utilisateur + réponses Santana
- Commande `mode brainstorming terminé` → proposition de sauvegarde
- Validation oui/non/titre → écriture dans CODEX-BRAINSTORM/20-SESSION/

**Fichier :** `tg_handlers/handlers.py`
**Commits :** `22a4fcd`, `be8aff3`

---

### 6. Mode brainstorming V2 — réponse DeepSeek au lieu d'echo

**Problème :** Santana répondait "🧠 Reçu : [copie des 200 premiers caractères]". Aucune valeur ajoutée.

**Solution :**
- Appel à DeepSeek avec contexte complet de la session (3000 derniers caractères)
- Reformulation + question ouverte en 2-3 lignes
- Fallback si DeepSeek indisponible
- Stockage complet, plus de troncature à 200 caractères

**Fichier :** `tg_handlers/handlers.py`
**Commit :** `f9f55e9`

---

### 7. Mode brainstorming V3 — résumé intelligent

**Problème :** La fin de session affichait juste "Messages échangés : X" et "Fichier : /tmp/...". Pas de valeur ajoutée.

**Solution :**
- Appel DeepSeek avec la session pour générer 3 sections :
  1. Analyse personnalité (traits, peurs, motivations)
  2. Idées et décisions (concepts, actions)
  3. Productivité (blocages, priorités, patterns)
- Résumé affiché à la place du simple comptage

**Fichier :** `tg_handlers/handlers.py`
**Commit :** `e6f1bc0`

---

### 8. Résumé enrichi par la mémoire vectorielle

**Problème :** Le résumé n'utilisait pas les livres de Santana (psychologie, vision_btr, etc.). Analyse trop générique.

**Solution :**
- Recherche vectorielle dans les livres via `atlas_engine.embeddings.search()`
- Passage des extraits pertinents dans le prompt DeepSeek
- Résumé connecté aux connaissances réelles de Santana

**Fichier :** `tg_handlers/handlers.py`
**Commit :** `e5f51d2`

---

### 9. Correction du ton : informel + bienveillance

**Problème :** Le ton était trop formel ("Analyse psychologique", "tu projettes dans Santana une quête"), et la fin disait "Salut mon pote" — incohérent.

**Solution :**
- Prompt modifié : "Tu es quelqu'un de bienveillant" au lieu de "psychologue"
- Règles : ton informel, tutoiement, phrases courtes, pas de jargon psy
- Interdiction de "mon pote", "mec", "mon frère"
- Cohérence entre le ton pendant la session ET le résumé final

**Fichiers :** `tg_handlers/handlers.py`
**Commits :** `d7c9c36`, `2ce56e3`

---

### 10. Variation des réponses (5 styles)

**Problème :** Santana répétait toujours le même pattern reformulation + question ouverte.

**Solution :**
- 5 styles alternés en fonction du nombre de tours :
  1. Reformulation + question ouverte
  2. Validation courte + invitation à approfondir
  3. Lien avec un message précédent
  4. Opposition douce ("Et si au contraire...")
  5. Résumé de l'émotion dominante

**Fichier :** `tg_handlers/handlers.py`
**Commit :** `e6f1bc0`

---

### 11. Emojis discrets + clarification titre

**Problème :** Pas assez d'emojis dans les réponses. Message "donne un titre" pas clair.

**Solution :**
- Emojis discrets dans les réponses pendant le brainstorming (💭🌱✨🫂🔥)
- Emojis dans le résumé final
- Message clarifié : "donne un titre (ex: reflexion peur validation)"

**Fichier :** `tg_handlers/handlers.py`
**Commit :** `4e6c911`

---

### 12. Fix DeepSeek V4 (champ type manquant)

**Problème :** DeepSeek V4 renvoyait erreur 400 "missing field type" sur les messages tool.

**Solution :**
- Ajout du champ `"type": "tool"` dans les messages tool_call de `core/react_loop.py`

**Fichier :** `core/react_loop.py`
**Commit :** `9b58956`

---

### 13. Stabilisation watchdog systemd

**Problème :** Santana tué toutes les minutes par le watchdog systemd (NOTIFY_SOCKET non défini).

**Solution :**
- Ping watchdog toutes les 30s via tâche asynchrone dans `_post_init`
- Ajout de `Type=notify` et `WatchdogSec=90` dans le service systemd

**Fichiers :** `santana.py`, `/etc/systemd/system/santana.service`
**Commits :** `804ce6e`, `e47664f`

---

### 14. Documentation

**Problème :** Aucune documentation sur l'implémentation du mode brainstorming.

**Solution :**
- `docs/MODE_BRAINSTORMING.md` dans santana : architecture complète, flux, restrictions
- `README.md` dans CODEX-BRAINSTORM : guide d'utilisation pour nouveaux arrivants

**Fichiers :** `docs/MODE_BRAINSTORMING.md`, `CODEX-BRAINSTORM/README.md`
**Commits :** `7ae40ba`, `ca8739e`

---

### 15. Nettoyage des livres Santana

**Problème :** Vision BTR = 1462 lignes (fourre-tout : PDFs, émotions, décisions, réflexions).

**Solution :**
- Vision BTR : 1462 → 682 lignes (PDFs supprimés, contenu pur vision)
- Famille : 156 → 464 lignes (réflexions personnelles déplacées)
- Projets : 296 → 814 lignes (décisions techniques déplacées)
- Psychologie : 107 lignes (inchangé)

**Fichiers :** `memory/livres/*.md`
**Commit :** `22a4fcd`

---

### Statistiques

| Métrique | Valeur |
|---|---|
| Commits aujourd'hui | 15 |
| Fichiers modifiés | ~12 |
| Nouvelles fonctionnalités | 1 (mode brainstorming) |
| Outils supprimés | 5 (stubs morts) |
| Repos créés | 1 (CODEX-BRAINSTORM) |
| Sessions brainstorming enregistrées | 4 |
| Lignes de documentation écrites | ~134 |
| Bugs DeepSeek corrigés | 1 (champ type) |
| Livres restructurés | 3 (Vision BTR, Famille, Projets) |
