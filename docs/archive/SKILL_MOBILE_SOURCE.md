# Développer un agent IA depuis un smartphone — Guide de survie

**Bad Technology Research — Mai 2026**

---

## 0. Avant-propos : qui sommes-nous pour parler de ça ?

Ce guide est le résultat de la construction complète de **Symbad** — un agent IA autonome —
depuis un **smartphone Android** (Oppo Reno 15 Pro), via **SSH dans Chrome**,
avec **DeepSeek V4 Flash** comme modèle.

Le fondateur du projet, Serge, n'est pas développeur.
Il fait du **vibe coding** : il parle à une IA, elle génère du code, il le déploie.
Tout, absolument tout, a été fait depuis un téléphone.

Ce document est le concentré de tout ce qu'on a appris.
Il est direct, technique, humain. Il ne t'infantilise pas.
Il te dit la vérité sur ce qui est dur, et comment on a survécu.

---

## 1. Contexte matériel

| Élément | Détail |
|---------|--------|
| Smartphone | Android (Oppo Reno 15 Pro) |
| Interface | SSH via Chrome (cloud.google.com) |
| Clavier | Gboard (tactile, pas de clavier physique) |
| Modèle utilisé | DeepSeek V4 Flash |
| Infrastructure | VM GCP Ubuntu 24.04, 4 vCPU, 16 Go RAM |

**Ce qu'on N'utilise PAS :**
- **Nano / Vim** : inutilisables sur mobile (navigation tactile impossible, copier-coller défaillant)
- **Termux** : testé, buggé, abandonné (copier-coller rigoureux, instable)

**Ce qu'on utilise :**
- **SSH via Chrome** : stable, fiable, import/export de fichiers
- **cat > fichier << 'XEOF'** : remplace Nano pour l'écriture
- **python3 << 'XEOF'** : pour l'exécution de scripts Python
- **DeepSeek V4 Flash** : seul LLM viable pour le vibe coding mobile (quota images illimité)

---

## 2. LE PROBLÈME CENTRAL : Android corrompt le copier-coller

C'est LE problème qui a failli tuer le projet. Il n'est documenté nulle part.

### 2.1 Ce qui se passe

Quand tu copies un bloc de code depuis une conversation avec un LLM
et que tu le colles dans le terminal SSH via Chrome, Android modifie :

- Les guillemets simples ' deviennent ' ou '
- Les guillemets doubles " deviennent " ou "
- Les tirets - deviennent — (tiret cadratin)
- Les backticks disparaissent ou deviennent '
- Les sauts de ligne sont ajoutés ou supprimés
- Les blocs longs (plus de 80 lignes) sont tronqués

Résultat : le code arrive cassé dans le terminal. Python hurle. On recommence.
Parfois 3, 4, 5 fois pour un seul bloc.

### 2.2 La solution : Heredoc Python

La méthode python3 << 'XEOF' ... XEOF traite tout le code comme un bloc littéral.
Les guillemets simples restent des guillemets simples.
Rien n'est modifié par le shell. Cette méthode a sauvé le projet.

### 2.3 Règles associées

- Jamais plus de 50 lignes par bloc. Au-delà, Android tronque.
- Jamais de sed sur du code Python. sed est fragile.
- Toujours valider avec python3 -m py_compile fichier.py avant d'exécuter.
- Utiliser des scripts Python plutôt que des commandes shell longues.

---

## 3. Le déploiement instable

### 3.1 Ce qui arrivait avant

On modifiait le fichier Python directement. On redémarrait le service.
Si le code était cassé, le service ne redémarrait pas. On découvrait l'erreur après coup.
Pas de backup automatique. Pas de rollback facile.

### 3.2 La solution : safe_edit.sh

Un script qui automatise tout :
1. Backup automatique du fichier actuel
2. Validation syntaxique (py_compile)
3. Remplacement du fichier
4. Redémarrage du service
5. Vérification que le service est actif
6. Rollback automatique si échec

Règle d'or : ne jamais modifier un fichier .py directement.
Toujours passer par safe_edit.sh ou par un script Python patch.

---

## 4. La fragilité du code source

### 4.1 Ce qui arrivait avant

Le code faisait 600 lignes. Tout était codé en dur : prompt système, outils, règles, skills.
Modifier le comportement = modifier le code = risquer un bug.

### 4.2 La solution : Architecture "Immutable Core"

Le moteur Python devient petit (400 lignes) et quasi immuable.
Toute la logique variable est externalisée dans des fichiers Markdown.

| Fichier | Rôle |
|---------|------|
| soul/SOUL.md | Personnalité de l'agent |
| soul/USER.md | Ce que l'agent sait de l'utilisateur |
| soul/RULES.md | Contraintes comportementales |
| skills/*.md | Compétences apprises |
| tools/tools.json | Définitions des outils |

Résultat : modifier le comportement, c'est éditer un fichier Markdown.
Aucune ligne de Python n'est touchée. Aucun bug possible.

---

## 5. Le debugging impossible sur mobile

### 5.1 Ce qui arrivait avant

Les logs étaient un flux texte brut. Sur le terminal mobile, tail -f est illisible :
le texte défile, le scroll tactile est imprécis, il n'y a pas de couleurs.
Impossible de trouver une erreur dans 200 lignes de log.

### 5.2 La solution : Logs structurés + PWA

- Logs avec tags : [TOOL], [SKILL], [API], [VOICE], [REACT]
- PWA avec onglet Logs : interface web lisible, scroll fluide, erreurs en rouge
- TokenFilter : le token Telegram est masqué dans les logs

---

## 6. La fragilité en cascade

### 6.1 Ce qui arrivait avant

Un outil qui plante -> Symbad qui crash -> plus aucune réponse.
Une base de données corrompue -> tout le service down.

### 6.2 La solution : Fail-Soft + Services isolés

- Fail-Soft : chaque outil est wrappé dans un try/except.
  Si un outil est down, Symbad répond avec les outils restants.
- Services systemd isolés : Symbad, API Flask, Console, Playwright
  sont des services séparés. Si l'un tombe, les autres continuent.
- Watchdog : redémarrage automatique si Symbad est muet plus de 30 minutes.
- Redémarrage quotidien : contourne le bug de freeze de python-telegram-bot.

---

## 7. La perte de travail

### 7.1 Ce qui arrivait avant

Un bug -> tout le progrès de la session était perdu.
Pas de versionnage. Pas de sauvegarde automatique.

### 7.2 La solution : Snapshots systématiques + Git + Telegram

- Snapshot manuel après CHAQUE modification réussie.
  Ne jamais enchaîner deux modifications sans sauvegarder la première.
- Git push quotidien (5h00 UTC) vers GitHub privé.
- Backup Telegram quotidien (4h00 UTC) : code + base de données.
- HEAL.sh : diagnostic complet en une commande.
- EMERGENCY.md : procédures d'urgence pour chaque panne.

---

## 8. Méthodologie de travail sur smartphone

### 8.1 La session type

1. Informer le LLM : "Je suis sur Android. Génère des blocs de moins de 50 lignes."
2. Snapshoter l'état actuel avant de commencer.
3. Appliquer les modifications bloc par bloc, en validant chaque bloc.
4. Tester immédiatement après chaque modification.
5. Sauvegarder dès que ça fonctionne.

### 8.2 Ce qu'il ne faut jamais faire

- Modifier un fichier .py directement
- Utiliser sed sur du Python
- Copier-coller un bloc de plus de 50 lignes
- Enchaîner deux modifications sans sauvegarder la première
- Redémarrer un service sans avoir validé la syntaxe avant

### 8.3 Ce qu'il faut toujours faire

- python3 -m py_compile avant chaque déploiement
- sudo systemctl is-active hermes après chaque redémarrage
- bash ~/hermes/HEAL.sh en cas de doute
- Sauvegarder après chaque étape réussie

---

## 9. Outils validés et abandonnés

| Outil | Statut | Raison |
|-------|--------|--------|
| SSH via Chrome | Valide | Stable, fiable |
| cat > fichier << 'XEOF' | Valide | Remplace Nano |
| python3 << 'XEOF' | Valide | Scripts fiables |
| safe_edit.sh | Valide | Déploiement sécurisé |
| HEAL.sh | Valide | Diagnostic urgence |
| DeepSeek V4 Flash | Valide | Seul LLM viable (images illimitées) |
| PWA (6 onglets) | Valide | Interface de pilotage |
| Nano | Abandonné | Inutilisable sur tactile |
| Termux | Abandonné | Buggy, copier-coller défaillant |
| sed sur Python | Abandonné | Corruption par Android |
| tail -f dans le terminal | Abandonné | Illisible sur mobile |

---

## 10. Philosophie du développement mobile

- "La contrainte est un avantage." Coder sur téléphone force à la simplicité radicale.
- "Zéro magie." Pas de framework lourd, pas d'abstraction inutile.
- "Le code doit pouvoir être lu depuis un téléphone."
- "Une chose à la fois." Une modification = un test = un snapshot.
- "La documentation n'est pas optionnelle."

La majorité des bugs ne viennent pas de l'intelligence du code,
mais de sa mutabilité. Externaliser le comportement hors du code Python
est la meilleure défense contre les bugs chroniques.

---

*Document rédigé par Serge et DeepSeek,*
*Bad Technology Research, mai 2026.*
