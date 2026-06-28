# FAQ — Développement mobile

**Bad Technology Research — Mai 2026**

---

## Q : Pourquoi mon code est-il cassé quand je le copie-colle ?

Android modifie les caractères pendant le copier-coller.
Guillemets, tirets, backticks mutent. Utilise `python3 << 'XEOF' ... XEOF`
pour traiter le code comme un bloc littéral.

## Q : Quelle est la taille maximale d'un bloc ?

50 lignes maximum. Au-delà, Android tronque le bloc.

## Q : Puis-je utiliser Nano ou Vim ?

Non. Ils sont inutilisables sur mobile (navigation tactile impossible).
Utilise `cat > fichier << 'XEOF'` pour écrire des fichiers.

## Q : Puis-je utiliser Termux ?

Non. Testé, buggé, copier-coller défaillant.
Utilise SSH via Chrome (cloud.google.com).

## Q : Quel LLM utiliser pour le vibe coding mobile ?

DeepSeek V4 Flash. C'est le seul avec un quota d'images illimité,
ce qui permet d'envoyer des captures d'écran sans saturer les tokens.

## Q : Comment éviter les bugs lors du déploiement ?

Utilise `safe_edit.sh`. Il automatise backup, validation syntaxique,
redémarrage et rollback si échec.

## Q : Comment lire les logs sur mobile ?

Via la PWA (onglet Logs). Le terminal mobile est illisible pour les logs.
Les logs sont structurés avec des tags : [TOOL], [SKILL], [API], [VOICE].

## Q : Comment sauvegarder mon travail ?

- Snapshot manuel après chaque modification réussie
- Git push quotidien automatique (5h00 UTC)
- Backup Telegram quotidien (4h00 UTC)

## Q : Que faire en cas de panne ?

1. `bash ~/hermes/HEAL.sh` — diagnostic complet
2. `sudo systemctl restart hermes` — redémarrer le service
3. Restaurer le snapshot stable si nécessaire

## Q : Comment externaliser la personnalité de mon agent ?

Crée un dossier `soul/` avec `SOUL.md`, `USER.md`, `RULES.md`.
Le moteur Python les lit au démarrage. Modifier la personnalité,
c'est éditer un fichier Markdown. Aucun risque de bug.
