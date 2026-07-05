# Architecture de Santana

## Autonomie

Santana dispose de deux niveaux d'autonomie :

1. **Guardian Watchdog** (start_watchdog) — boucle de santé interne toutes les 60s.
   Vérifie DB, outils en échec. Alerte Telegram si 3 échecs consécutifs.
   Automatique, sans sollicitation de Serge.

2. **À la demande** — tout le reste (analyse, recherche, exécution).
   Déclenché uniquement par message de Serge ou outil LLM.
