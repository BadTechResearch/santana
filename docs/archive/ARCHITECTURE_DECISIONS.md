# Décisions Architecturales — Santana

> *Un système agentique à mémoire persistante, conçu pour la continuité relationnelle*

**Auteur :** Serge  
**Version :** 1.0  
**Date :** Mai 2026  
**License :** MIT  

---

## Résumé Exécutif

Santana est un assistant IA personnel qui vit dans Telegram, doté d'une mémoire persistante structurée en "livres" (fichiers Markdown), d'un moteur conversationnel réactif, et d'une capacité d'action autonome via cron et outils.

Ce document ne décrit pas *ce que* Santana fait, mais *pourquoi* son architecture est structurée ainsi. Chaque décision est présentée avec son contexte, les alternatives envisagées, la solution retenue, et ses conséquences.

---

## 1. Brique Fondamentale : Moteur Conversationnel sur Mesure

### Contexte

Un assistant IA reçoit des messages, les interprète, décide d'actions, consulte de la mémoire, et répond. Le choix du squelette logiciel détermine tout le reste.

### Décision

**Construire une react loop personnalisée** plutôt qu'utiliser un framework agentique existant.

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **LangChain / LangGraph** | Abstraction opaque. Quand le système dévie du chemin attendu, le débogage nécessite de comprendre 4 couches d'abstraction. Le coût en tokens du framework dépasse souvent le bénéfice. |
| **AutoGPT** | Preuve de concept, pas un système fiable. Boucles infinites, coût token explosif, zéro garantie de terminaison. |
| **CrewAI** | Orienté équipes d'agents, pas single-agent profond. Overhead inutile. |
| **Bot Framework (Microsoft)** | Verrouillage plateforme. Pas de contrôle sur la boucle d'inférence. |

### Solution retenue

Une react loop qui suit un cycle strict : réception → analyse → détermination du type de message → injection de contexte mémoire → appel LLM → dispatch d'outils (si nécessaire) → réponse → écriture mémoire post-hoc.

Le point clé : la boucle expose chaque étape dans les logs. Rien n'est caché. On peut tracer le chemin exact de n'importe quelle décision.

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| Contrôle total sur l'inférence et le tool calling | Maintenance manuelle, pas de mises à jour framework automatiques |
| Debug traçable ligne par ligne | Pas d'écosystème de plugins prêts à l'emploi |
| Zéro dépendance inutile (poids mort) | Plus de code à écrire pour chaque nouvelle fonctionnalité |

---

## 2. Mémoire : Livres .md Plutôt que Base de Données

### Contexte

Un agent qui ne se souvient de rien est inutile. La mémoire est la caractéristique déterminante de Santana. Le choix du support de mémoire conditionne la fiabilité, l'évolutivité et la confiance.

### Décision

**Utiliser des fichiers Markande (livres) comme support de mémoire primaire**, complétés par un index vectoriel léger pour la recherche sémantique.

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **Base vectorielle pure (Pinecone, Weaviate, Qdrant)** | Boîte noire. Impossible de lire ce que l'agent "sait" sans outil spécialisé. Corrompre l'index = perdre la mémoire. Coût récurrent. |
| **Base SQL (PostgreSQL + pgvector)** | Plus lourd à maintenir pour un single-user. La modélisation des conversations, décisions, personnes, dates en schéma relationnel est rigide et ne capture pas la richesse du langage naturel. |
| **Fichiers JSON** | Lisibles mais pas éditables naturellement. Pas de formatage, pas de structure visuelle. |
| **Ne pas persister** (stateless pur) | Impossible. L'utilisateur répète tout à chaque conversation. |

### Solution retenue

Cinq livres thématiques (psychologie, famille, projets, vision_BTR, quête), trois registres structurés (décisions, personnes, dates), et un flux hebdomadaire. Chaque fichier est en Markdown — lisible, éditable, versionnable (`git`).

Un index vectoriel léger (`sentence-transformers`, modèle `all-MiniLM-L6-v2`) tourne en local pour la recherche par similarité. L'index est persistant dans `memory.db` avec un cache LRU de 20 entrées pour économiser les tokens.

Le Memory Steward (cf. décision 4) assure l'écriture, la déduplication et la santé des fichiers.

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| L'utilisateur peut OUVRIRE un fichier et lire ce que l'agent sait de lui | Recherche moins performante qu'une base dédiée sur de très gros volumes |
| `git` permet de voyager dans le temps — revenir à une mémoire antérieure | Pas de requêtage SQL complexe (compensé par la recherche vectorielle) |
| Zéro lock-in : les données sont des .md transportables | Le Steward doit gérer la fragmentation (rotation, archive, compression) |
| La mémoire est curatée (classifieur 2 niveaux) plutôt qu'un dump passif | — |

---

## 3. Injection de Contexte : Classifieur à Deux Niveaux

### Contexte

Injecter toute la mémoire à chaque tour de conversation est impossible (explosion du contexte LLM). Il faut sélectionner ce qui est pertinent pour la conversation en cours.

### Décision

**Un classifieur à deux niveaux** qui détermine (1) la catégorie du message (fait, décision, intention, émotion) et (2) le livre mémoire à consulter, avec fallback LLM pour les cas ambigus.

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **Injection brute de tout le flux récent** | Fonctionne en phase précoce mais dégrade vite. Au-delà de 2-3 conversations, le contexte est pollué par des informations non pertinentes et le coût token explose. |
| **Recherche vectorielle seule** | Trop large. Sans classification préalable, des chunks sémantiquement proches mais contextuellement inutiles sont injectés. |
| **RAG classique (retrieve + generate)** | Pas de curation. Tout ce qui ressemble au sujet est injecté, y compris des données obsolètes ou contradictoires. |

### Solution retenue

Niveau 1 : un classifieur regex + heuristique qui extrait rapidement les faits, décisions, intentions et émotions d'un message.

Niveau 2 : un appel LLM (fallback) pour les cas où le classifieur heuristique n'est pas assez confiant — typiquement les messages ambigus ou les sous-entendus.

L'injection combine :
- Le flux de la semaine en cours (contexte chronologique brut)
- Les registres (décisions, personnes, dates — contexte structuré)
- Les top-5 chunks vectoriels les plus pertinents (contexte sémantique)

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| Contexte injecté = pertinent, pas volumineux | Complexité supplémentaire dans la chaîne mémoire |
| Économie de tokens significative (vs injection brute) | Fallback LLM = coût marginal sur les cas ambigus |
| La classification permet un routage fin vers le bon livre | — |

---

## 4. Écriture Mémoire : Le Memory Steward en Tâche de Fond

### Contexte

Un agent qui écrit en mémoire pendant qu'il réfléchit se trompe : il enregistre ses propres hallucinations. L'écriture doit être fiable, dédupliquée, et ne pas interférer avec la conversation.

### Décision

**Un module autonome post-conversation** — le Memory Steward — qui analyse chaque échange terminé et décide, calme et hors du flux, ce qui mérite d'être retenu.

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **Écriture synchrone dans la boucle de réponse** | L'agent écrit en mémoire pendant qu'il réfléchit. Risque d'enregistrer des inférences pas des faits. Ralentit la réponse. |
| **Écriture par l'utilisateur (commande manuelle)** | Incomplet. L'utilisateur oublie, ne catégorise pas, ne voit pas les patterns. |
| **Écriture par cron basse fréquence** | Trop lent. Une conversation peut contenir plusieurs décisions importantes qui doivent être enregistrées rapidement. |

### Solution retenue

Le Steward est invoqué après chaque réponse utilisateur, en arrière-plan (asyncio). Il :

1. **Analyse** l'échange (classifieur + LLM)
2. **Décide** quel livre/registre enrichir
3. **Écrit** le contenu pertinent
4. **Déduplique** (SequenceMatcher > 75%)
5. **Signale** les anomalies (contradictions, saturation)

Un Guardian séparé tourne périodiquement pour la maintenance lourde : compression des livres saturés, archivage des données anciennes, détection de corruption.

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| L'agent ne s'écoute pas halluciner | Latence différée : l'écriture n'est pas instantanée |
| La mémoire est propre (dédupliquée, curatée) | Deux modules à maintenir (Steward + Guardian) |
| L'utilisateur ne subit pas le temps d'écriture | — |
| Les décisions sont tracées dans le temps | — |

---

## 5. Séparation Identité / Logique : SOUL.md comme Constitution

### Contexte

Le comportement de l'agent est défini par son system prompt. Traditionnellement, tout est mélangé dans un seul bloc : personnalité, règles, contexte technique.

### Décision

**Trois fichiers séparés, injectés dans le system prompt à chaque tour :**

- **SOUL.md** — la constitution. Personnalité, valeurs, ton, voix. Ce que l'agent "est".
- **USER.md** — le portrait de l'utilisateur. Ses besoins, son style, ses irritants. Ce que l'agent sait de la personne.
- **RULES.md** — les lois absolues. Sécurité, confidentialité, priorisation. Ce que l'agent ne transgresse jamais.

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **System prompt unique** | Rigide. Tout changement nécessite de modifier le prompt dans le code. Pas de séparation des préoccupations. |
| **Personnalité codée en dur dans Santana.py** | Inchangeable sans redéploiement. Catastrophique pour un agent qui doit évoluer avec son utilisateur. |
| **Personnalité stockée en mémoire vectorielle** | La personnalité ne devrait pas être "retrouvée" — elle est absolue et doit être injectée à chaque tour. |

### Solution retenue

Les trois fichiers sont lus depuis le disque et injectés directement dans le system prompt à chaque appel LLM. L'utilisateur peut modifier SOUL.md avec un éditeur de texte et redémarrer Santana pour un changement d'identité complet.

USER.md est mis à jour par le Steward. RULES.md est verrouillé en écriture (modification manuelle uniquement).

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| L'agent ne dérive jamais de son identité | 3 fichiers = 3 fois plus d'injection de contexte (mais taille négligeable : ~5 KB total) |
| L'utilisateur contrôle la personnalité sans toucher au code | — |
| USER.md évolue avec la relation | — |
| Pattern exportable à d'autres projets agentiques | — |

---

## 6. Choix du Canal : Telegram Exclusif

### Contexte

Un agent conversationnel doit habiter quelque part. Une interface web ? Un client lourd ? Multi-plateforme ?

### Décision

**Telegram comme interface unique et exclusive**, avec une API REST complémentaire pour l'intégration programmatique.

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **Application web (PWA)** | Coût de développement d'interface, maintenance CSS/JS, gestion des sessions, responsive design. Pour un single-user, le rapport effort/bénéfice est nul. |
| **Discord / Slack** | Pensés pour le multi-utilisateur. Le threading, les channels, les permissions ajoutent une complexité inutile pour un agent personnel. |
| **Application mobile native** | Déploiement sur stores, mises à jour, fragmentation Android/iOS. Trop lourd. |
| **CLI (terminal)** | Excellent pour le développement, terrible pour un usage quotidien et mobile. |

### Solution retenue

Telegram offre : API mature, notifications push, support multimédia (audio, images, fichiers), groupes, threads, zero coût, client mobile + desktop. Une API REST Flask est maintenue pour les intégrations techniques (dashboard /status, health checks, scripts externes).

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| L'utilisateur parle à son agent depuis son téléphone, sans rien ouvrir | Pas d'interface web pour les utilisateurs qui n'aiment pas Telegram |
| Zero frais d'hébergement de frontend | Dépendance à un service tiers (mais API publique mature) |
| Notifications push natives | — |

---

## 7. Extension par MCP (Model Context Protocol)

### Contexte

Un agent qui ne peut pas apprendre de nouveaux tours est limité. Les outils natifs sont fixes ; il faut une façon d'ajouter des capacités sans modifier le code de l'agent.

### Décision

**Adopter le Model Context Protocol (MCP) d'Anthropic** comme mécanisme d'extension standard, avec une implémentation client native (zéro dépendance externe).

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **Plugin system propriétaire** | Réinventer la roue. Définir un format, un SDK, une documentation. Aucune interopérabilité. |
| **API REST externes (webhooks)** | Pas de typage, pas de découverte automatique, chaque service a son API différente. |
| **Fonctions LLM (tool calling brut)** | Fonctionne pour les outils simples mais ne scale pas : chaque outil nécessite un schema JSON défini dans le code source. |

### Solution retenue

Un client MCP natif (JSON-RPC) qui découvre automatiquement les outils exposés par chaque serveur MCP, les expose au LLM via le tool calling standard, et gère la connexion/reconnexion. L'ajout d'un nouveau serveur MCP (ex : Notion, Linear, base de données) ne nécessite aucune modification du code de Santana.

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| Extension infinie sans modifier le code de l'agent | Dépendance à l'écosystème MCP (en croissance rapide) |
| Interopérabilité avec les outils existants (MCP est un standard) | Chaque serveur MCP est un processus supplémentaire à gérer |
| Découverte automatique des outils | — |

---

## 8. Posture Autonome : Cron et Exécution Asynchrone

### Contexte

Un agent conversationnel est passif : il répond quand on lui parle. Pour être vraiment utile, il doit pouvoir agir de lui-même.

### Décision

**Un scheduler cron intégré** qui permet à Santana de lancer des tâches autonomes (veille mémoire, rapports, surveillance) et d'en livrer les résultats sur Telegram.

### Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| **Cron système (crontab)** | Santana doit pouvoir créer/supprimer des tâches depuis la conversation. Pas d'interaction avec le système host. |
| **Boucle de polling permanente** | Consomme des tokens et de l'attention LLM en continu. Pas de séparation claire entre conversation et tâche de fond. |
| **Pas d'autonomie** | L'agent n'est qu'un chatbot de plus. La valeur différentielle est perdue. |

### Solution retenue

Un scheduler interne avec sa propre file d'attente. Chaque tâche est une conversation isolée (contexte dédié, scope limité). Livraison automatique du résultat dans le canal Telegram.

### Conséquences

| ✅ Avantages | ⚠️ Coûts |
|---|---|
| L'agent agit sans l'utilisateur | Consommation de tokens en arrière-plan |
| Veille mémoire automatique | Complexité de scheduler à maintenir |
| Rapport programmé (quotidien, hebdomadaire) | — |

---

## Synthèse : Principes Architecturaux

Ces huit décisions s'alignent sur quatre principes qui traversent toute l'architecture de Santana :

**1. Préférer le contrôle à la commodité**
Les frameworks existants (LangChain, AutoGPT) offrent de la vitesse initiale au prix d'une perte de contrôle. Santana choisit des composants plus simples mais entièrement maîtrisés.

**2. Concevoir pour l'auditabilité**
Chaque décision de l'agent est tracée. Chaque écriture mémoire est loggée. La react loop expose ses étapes. Rien n'est une boîte noire.

**3. Externaliser l'identité de l'implémentation**
SOUL.md, USER.md, RULES.md sont des fichiers séparés du code. La personnalité de l'agent peut être modifiée sans changer une ligne de Python.

**4. Privilégier la simplicité opérationnelle**
Single-user, pas de base de données, pas de conteneurisation obligatoire, pas de cloud. Santana peut tourner sur un VPS à 5€/mois.

---

*Document généré le 20 mai 2026. Ceci n'est pas une documentation technique exhaustive — c'est la carte des décisions qui ont construit le système.*
