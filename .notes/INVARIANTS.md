# INVARIANTS — Règles absolues de Santana

Avant toute modification du système, vérifier que chaque invariant est respecté.

## 1. Réponse Telegram texte
Santana doit toujours répondre aux messages texte.
- Si DeepSeek est down → "DeepSeek indisponible, réessaie dans un instant."
- Si memory.db est corrompu → répondre sans mémoire.
- Si un outil échoue → répondre avec les outils restants.

## 2. Messages vocaux isolés
Un message vocal qui échoue ne doit jamais bloquer les messages texte.
- Si Whisper n'est pas chargé → le handler vocal échoue silencieusement.
- Les messages texte continuent de répondre.

## 3. PWA Statut accessible
La page Statut de la PWA doit toujours se charger.
- Même si memory.db est vide → afficher "0 souvenirs".
- Même si un service est down → afficher son état réel.

## 4. Isolement des outils
Un outil qui échoue ne doit jamais arrêter Santana.
- Chaque outil est wrappé (Fail-Soft).
- Si un outil est down → Santana continue avec les autres.

## 5. Aucune maintenance ne nécessite d'interface graphique
Tout doit être faisable depuis un smartphone (SSH, Telegram, PWA).

## 6. Le cœur tourne sans Playwright
Santana fonctionne même si le moteur Chromium est arrêté.

## 7. Déploiement sans downtime
Toute modification passe par vérification syntaxique avant redémarrage.
- Rollback automatique si le service ne redémarre pas.

## 8. Données hors VM
Le code et la mémoire sont sauvegardés hors de la VM chaque jour.
- Git push quotidien vers GitHub.
- Backup Telegram quotidien.
- Snapshot STABLE avant chaque modification majeure.

## INVARIANTS TECHNIQUES — Règles pour les développeurs

### 1. Pas de sed sur du Python
Toute modification majeure se fait via :
- fichier temporaire
- validation py_compile
- backup automatique
- rollback possible

### 2. Le moteur principal doit rester petit
- santana.py < 500 lignes
- api.py < 300 lignes

### 3. Toute logique variable doit sortir du moteur
Externaliser vers :
- soul/*.md
- skills/*.md
- tools/tools.json

### 4. Chaque composant doit être fail-soft
Un service down ne doit jamais bloquer l'ensemble.

### 5. SQLite reste la seule base
Pas de Redis, pas de vector DB, pas de Kafka.
Pas de microservices inutiles.

### 6. Mobile-first obligatoire
Toute commande doit être courte, copiable, exécutable depuis Android.

### 7. Une seule source de vérité
Jamais de duplication :
- personnalité → SOUL.md
- règles → RULES.md
- skills → skills/*.md

### 8. Pas de framework lourd
Pas de LangChain, pas d'AutoGen, pas d'usine agentique.
