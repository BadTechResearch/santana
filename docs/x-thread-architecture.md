# X Thread Draft — Santana Architecture

> *Thread technique pour X — 7 tweets. À poster depuis le compte @BadTechResearch ou personnel.*

---

**Tweet 1/7 🧵**
J'ai passé les 3 derniers mois à construire un agent AI autonome qui tourne pour < 10€/mois d'inférence sur une VM à 7€/mois.

Pas de Docker. Pas de Redis. Pas de Postgres. Juste Python + SQLite.

Voici comment ça marche et pourquoi j'ai fait ces choix.

→ https://github.com/BadTechResearch/santana

**Tweet 2/7 — Architecture 3 agents**
La plupart des frameworks d'agents (LangChain, AutoGPT) sont des boîtes à outils — tu passes 2 semaines à assembler les pièces.

Santana est un agent qui *tourne*. Architecture simplifiée :

🧠 Réacteur → décide quoi faire
🔧 Exécuteur → exécute les outils
💾 Mémoriseur → gère la mémoire persistante

Une boucle, un processus, zéro microservice.

**Tweet 3/7 — Pourquoi pas de Docker ?**
Un agent personnel n'a pas besoin d'une stack enterprise. Docker + Redis + Postgres, c'est 2-4GB de RAM avant même d'avoir lancé l'agent.

Mon design : SQLite en WAL mode, un seul processus Python 3.11+ avec aiohttp. 2GB RAM suffisent.

Résultat : je tourne sur une GCP e2-micro à ~7$/mois.

**Tweet 4/7 — Le vrai coût LLM**
DeepSeek V4 Flash coûte $0.028/1M tokens en cache. Avec un cache hit rate de 94-96%, un million de tokens par jour coûte ~8-10$/mois.

Comparaison :
- Claude Sonnet 4 : ~80$/mois
- GPT-4o : ~150$/mois
- DeepSeek (mon usage réel) : **8-10$/mois**

Et j'ai un fallback OpenRouter + Nous Portal au cas où DeepSeek est down.

**Tweet 5/7 — Mémoire 3 couches**
Problème classique des agents : ils oublient tout entre les sessions.

Ma solution :
1. Buffer de session (contexte complet glissant)
2. Résumés compressés de l'historique
3. Embeddings vectoriels SQLite (all-MiniLM-L6-v2, 80MB, CPU)

L'agent se souvient de ce que tu lui as dit il y a 3 jours, sur Telegram, même après redémarrage.

**Tweet 6/7 — Outils et autonomie**
15+ outils intégrés :
🌐 Recherche web (Google + réseaux sociaux)
🐙 GitHub (lecture/écriture de repos, fichiers)
⚡ Exécution Python sandboxée
🔒 Terminal whitelisté
📺 YouTube, Twitter, MCP

Et un Cost Governor qui ALERTE/ralentit/STOPPE l'agent si ça dépense trop. Oui, un agent qui se contrôle tout seul.

**Tweet 7/7 — Pourquoi je partage**
Le marché des agents est saturé de frameworks enterprise chers. Je pense qu'il y a une vraie place pour des agents *frugaux* qui tournent sur du hardware modeste et coûtent le prix d'un abonnement Netflix.

Open-source, AGPL-3.0, prêt à l'emploi en 15 minutes.

⭐ https://github.com/BadTechResearch/santana
