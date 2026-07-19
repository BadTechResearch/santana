# Optimisation ×3 du pipeline Santana — Résumé exécutif

## Contexte
Analyse comparative Hermes Agent / Santana / OpenClaw pour accélérer ×3 le pipeline de réponse.
Rapport complet : `skills/references/conseil-discipline-optimisation-full.md`

## Consensus (3/3 agents)

| Optimisation | Consensus |
|---|---|
| Cache prompt TTL 60s→300s | FORT |
| SQLite → RAM / lazy writes | FORT |
| Tool caching (web, social, LRU) | FORT |
| Évaluation async différée | MOYEN |

## Rejeté par le Conseil
- Quick Check qualité (hors scope vitesse)
- Pré-compilation 5 prompts (sur-ingénierie)

## Blocs noyau (intervention Serge)
- HTTP connection pool DeepSeek (`core/provider.py`)
- Flood control Telegram 1.2s→0.8s (`tools/telegram_stream.py`)

## Plan d'exécution

### Phase 1 — Quick wins (Santana, ~2h)
1. Cache prompt TTL 300s → `orchestrator.py`
2. Évaluation unique factorisée → `react_loop.py`
3. Imports top-level → `react_loop.py`
4. `classify_message()` 1× → paramètre → `react_loop.py` + `orchestrator.py`
5. Skip contexte pour SOCIAL → `orchestrator.py`
6. Buffer session RAM + lazy SQLite → `context.py`
7. Tool caching web_search + social_search → `react_loop.py`

### Phase 2 — Infrastructure (Serge, ~32 min)
1. HTTP connection pool DeepSeek → `core/provider.py`
2. Flood control 0.8s → `tools/telegram_stream.py`

### Phase 3 — Affinage (~55 min)
1. Mémoire 20×500 → 12×400
2. Évaluation async (skip SOCIAL)
3. Monitoring cache/TTL

## Gains projetés
| Type | Avant | Après | Gain |
|---|---|---|---|
| SOCIAL | ~1.5s | ~0.4s | ×3.7 |
| FACTUEL | ~3.5s | ~2.0s | ×1.75 |
| DEEP | ~6-10s | ~3-5s | ×2.0 |
| PERSONNEL | ~4-8s | ~2.5-4s | ×1.8 |

**Moyenne pondérée : ×2.3 — Investissement : ~2h — Risque : nul**
