# HISTORIQUE DES AUDITS — Santana

> **Archive consolidée le :** 20 juin 2026
> **Source :** 6 fichiers racine originaux conservés pour référence
> **Auteur :** Claude Code (audits 1-6), consolidé par Hermès

---

## Table des matières

| # | Fichier source | Date | Score | Périmètre |
|---|---|---|---|---|
| 1 | `CLAUDE-AUDIT-RAPPORT.md` | 19 juin 2026 | 62/100 | Audit complet initial (mémoire, autonomie, sécurité, qualité, perf, frugalité) |
| 2 | `CLAUDE-AUDIT-3.md` | 19 juin 2026 | 60/100 | Creusement `react_loop.py`, `deepseek_client.py`, `routes/` |
| 3 | `CLAUDE-NOTE-FINALE.md` (passe 5-6) | 19 juin 2026 | 62/100 | Correction 4 bugs + corruption `memory.db` |
| 4 | `CLAUDE-AUDIT-4-FINAL.md` (passe 7) | 19 juin 2026 | 59/100 | Sécurité approfondie (execution directe, 3 bypass vm_exec) |
| 5 | `CLAUDE-AUDIT-FINAL.md` | 19 juin 2026 | 86/100 | Post-fermeture 100% (316 tests) |
| 6 | `CLAUDE-CLOSURE.md` | 19 juin 2026 | — | Certification fermeture définitive |

---

---

# AUDIT 1 — Rapport complet initial

**Fichier source :** `CLAUDE-AUDIT-RAPPORT.md` (19 juin 2026, 139 lignes)

## NOTE GLOBALE : 62/100

| Axe | Note /10 | Verdict |
|---|---|---|
| Mémoire | **8** | Atlas V2/V3 solide, anciens bugs déjà corrigés, une redondance réelle restante |
| Autonomie | **4** | Forte en intra-tour, quasi nulle en initiative spontanée |
| Sécurité | **4** | Hygiène secrets/permissions bonne, `vm_exec` trou sérieux |
| Qualité du code | **7** | 161/161 tests verts, nouvelle dette apparue |
| Performances | **6** | Optimisations récentes réelles, deux redondances mesurées |
| Frugalité BTR | **8** | Contraintes respectées à la lettre, disque sous tension |

## Bugs réels

| # | Sévérité | Description |
|---|---|---|
| A | Sérieux (dormant) | `tg_handlers/state.py:36` — accès ouvert si GROUP_BLACK_INTELLIGENCE absent |
| B | Sérieux | `tools/tools.py:497-502` — `_vm_validate()` contournable |
| C | Moyen | `.gitignore` — `*.db-shm/wal` trackés malgré gitignore |
| D | Moyen | `.gitignore` — `*.bak` ne matche pas `*.bak.<timestamp>` |
| E | Mineur | `agent/orchestrator.py:74` — patterns dupliqués inatteignables |

**Voir fichier source `CLAUDE-AUDIT-RAPPORT.md` pour le détail complet.**

---

# AUDIT 2-3 — Creusement react_loop, deepseek_client, routes/

**Fichier source :** `CLAUDE-AUDIT-3.md` (19 juin 2026, 130 lignes)

## NOTE GLOBALE : 60/100

| Axe | Note | Évolution vs audit 1 |
|---|---|---|
| Mémoire | **8** | = |
| Autonomie | **4** | = |
| Sécurité | **4** | = (nouveau cluster routes/) |
| Qualité du code | **6** | ↓ (était 7) |
| Performances | **6** | = |
| Frugalité BTR | **8** | = |

## Bugs réels (nouveaux)

| # | Sévérité | Description |
|---|---|---|
| 1 | Sérieux (dormant) | 4 routes Flask sans authentification |
| 2 | Sérieux | Path traversal dans `routes/system.py` et `routes/memory.py` |
| 3 | Sérieux | Comparaison token non constante (`==` au lieu de `hmac.compare_digest`) |
| 4 | Moyen | Filtre anti-fuite secrets contournable via `%s`-style logging |
| 5 | Mineur | `DEEPSEEK_MODEL` vs `DISPLAY_MODEL` — deux défauts différents |
| 6 | Mineur | Fuite mémoire lente dans rate-limiter IP |

## Correctifs A-E du 2ᵉ audit

| Bug | Fix appliqué | Vérification |
|---|---|---|
| A | `is_allowed()` fail-closed | Test direct : chat_id inconnu refusé |
| B | `_vm_validate()` durci | 5 bypasses originaux re-testés → bloqués |
| C | `git rm --cached` sur 4 fichiers | Retirés de l'index git |
| D | `*.bak` → `*.bak*` | `git check-ignore` confirme |
| E | 3 patterns morts retirés | Code prouvé inatteignable |

**161/161 tests pytest verts.** Voir `CLAUDE-AUDIT-3.md` pour le détail.

---

# AUDIT 3-4 — Notes finales (passes 5 et 6)

**Fichier source :** `CLAUDE-NOTE-FINALE.md` (19 juin 2026, 133 lignes)

## Passe 5 : 4 bugs connus + corruption `memory.db`

**Score : 62/100**

### Bugs corrigés

| # | Bug | Fix |
|---|---|---|
| a | `tools/tools.json` désynchronisé (33 vs 34 outils) | Ajout `multi_agent_route` + `orchestration_repair` |
| b | `scan_registry()` lisait fichier statique | Lit `tools.registry.get_tool_names()` |
| c | `log_evaluation()` jamais appelée | Branchée aux 2 points d'appel |
| d | `detect_conflicts()` rechargeait le modèle | Réutilise singleton embeddings |

### ⚠️ Découverte : corruption `memory.db`

- B-tree avec rowids hors-ordre, pages référencées deux fois
- Tables affectées : `memory`, `identity`, `session_buffer`, `session_summaries`, `workspace_state`
- Backup propre disponible : `_backups/memory_2026-06-19T030009.db`

## Passe 6 : Corrections post-investigation

### Résolu
- **`memory.db`** : restauré depuis backup, `integrity_check` = `ok`
- **`disambiguate.py`** : branché dans `core/react_loop.py` (signature réelle : 1 arg)
- **`record_interaction()`** : branchée dans `_finalize()` (point de sortie unique)
- **~30 imports morts** supprimés, chacun vérifié par grep

**254/254 tests verts.** Voir `CLAUDE-NOTE-FINALE.md`.

---

# AUDIT 4 — Audit final approfonndi (7ᵉ passe)

**Fichier source :** `CLAUDE-AUDIT-4-FINAL.md` (19 juin 2026, 150 lignes)

## NOTE GLOBALE : 59/100

| Axe | Note /100 | vs précédent |
|---|---|---|
| Mémoire | 78 | ↓ (était 80) |
| Sécurité | 35 | ↓ (était 40) |
| Autonomie | 30 | ↓ (était 40) |
| Performances | 65 | ↑ (était 60) |
| Optimisation/Frugalité | 70 | ↓ (était 80) |
| Qualité du code | 75 | ↑ (était 70) |

## Bugs réels (vérifiés par exécution)

| # | Bug | Sévérité |
|---|---|---|
| 1 | `_vm_validate` contournable via `bash -c "..."` / `sh -c "..."` | CRITIQUE |
| 2 | `_vm_validate` ne détecte pas `os.system()`/`subprocess` inline | CRITIQUE |
| 3 | `_vm_validate` ne bloque pas `curl|bash` / `wget|bash` | CRITIQUE |
| 4 | Filtre regex `"wget.*bash"` non fonctionnel (in littéral) | HAUTE |
| 5 | `vm_exec` ne protège pas la lecture de secrets (.env, clés SSH) | HAUTE |
| 6 | `tools/guardian.py` absent, watchdog no-op silencieux | MOYENNE |
| 7 | `backup_db.sh` détecte corruption mais n'alerte personne | MOYENNE |
| 8 | Budget doc $0,50 vs config $2,00 | FAIBLE |
| 9 | Règles frozen citent numéros de ligne décalés | FAIBLE |

**Avis personnel :** vm_exec n'est pas un trou — c'est un jeu du chat et de la souris tant que ça reste un denylist.

**254/254 tests verts.** Voir `CLAUDE-AUDIT-4-FINAL.md`.

---

# AUDIT 5 — Post-fermeture 100%

**Fichier source :** `CLAUDE-AUDIT-FINAL.md` (19 juin 2026, 224 lignes)

## NOTE GLOBALE : **86/100** (+27 vs audit précédent)

| Axe | Avant (59) | Après (86) |
|---|---|---|
| Mémoire | 78 | **93** |
| Sécurité | 35 | **85** |
| Autonomie | 30 | **75** |
| Performances | 65 | **88** |
| Optimisation/Frugalité | 70 | **85** |
| Qualité du code | 75 | **88** |

## Changements clés

- **Sécurité :** vm_exec réécrit en allowlist (`tools/vm_security.py`), bash/sh/python/perl/ruby/node exclus structurellement ; protection anti-secret par `realpath` ; environnement minimal `safe_env()` ; isolation réseau `unshare --net`
- **Autonomie :** `tools/guardian.py` réel (watchdog 60s, guardian 30min)
- **Performance :** embeddings préchargé au démarrage (fin du délai ~12s)
- **Frugalité :** disque 93%→76% (8,1 Go de backups nettoyés), `requirements.txt` réduit de 141→100, artefact Docker supprimé
- **Résilience :** `kill -9` → redémarrage systemd en 12s
- **Closure :** 316/316 tests (161 historiques + 93 intégrité + 62 fermeture 100%)

## Bugs restants (ouverts/acceptés)

| Bug | Statut |
|---|---|
| 1-9 (audit précédent) | **Tous corrigés** |
| 10-11 (injection saut de ligne, curl -o) | **Corrigés pendant cet audit** |
| 12 | `pip install` reste vecteur de risque | Accepté |
| 13 | `~/.claude/rules/santana.md` numéros de ligne | Ouvert, hors dépôt |

**316/316 tests verts.** Voir `CLAUDE-AUDIT-FINAL.md`.

---

# AUDIT 6 — CLAUDE-CLOSURE (Fermeture définitive 100%)

**Fichier source :** `CLAUDE-CLOSURE.md` (19 juin 2026, 143 lignes)

## Résumé par rubrique

### MÉMOIRE
- **Avant :** intégrité restaurée, aucune alerte si redégradation
- **Après :** alerte Telegram dans `backup_db.sh` ; résilience `kill -9` vérifiée (12s)

### SÉCURITÉ
- **Avant :** 3 bypass vm_exec démontrés, pas de protection anti-secret
- **Après :** allowlist `vm_security.py`, `safe_env()`, isolation réseau `unshare --net`

### AUTONOMIE
- **Avant :** `guardian.py` no-op, stub `# pas encore implémenté`
- **Après :** watchdog 60s, guardian 30min avec suggestion Telegram autonome

### PERFORMANCES
- **Avant :** budget doc $0,50 vs config ; /reset partiel ; ~12s latence démarrage
- **Après :** doc alignée ; /reset complet ; embeddings préchargé

### OPTIMISATION/FRUGALITÉ
- **Avant :** disque 93% (3,6 Go) ; artefacts Docker ; 41 dépendances fantômes
- **Après :** disque 76% (12 Go) ; Docker supprimé ; requirements.txt réduit

### QUALITÉ DU CODE
- **Avant :** ~18 imports morts ; zones frozen décalées ±1 ligne
- **Après :** imports nettoyés ; contenu frozen vérifié par diff ; tools.json 34/34

**Total : 313 tests (161 + 93 + 59), 0 échec.** Voir `CLAUDE-CLOSURE.md`.

---

## Références

- Rapports originaux conservés à la racine du projet Santana :
  - `CLAUDE-AUDIT-RAPPORT.md` — 139 lignes, 11,7 Ko
  - `CLAUDE-AUDIT-3.md` — 130 lignes, 11,9 Ko
  - `CLAUDE-NOTE-FINALE.md` — 133 lignes, 13,1 Ko
  - `CLAUDE-AUDIT-4-FINAL.md` — 150 lignes, 15,2 Ko
  - `CLAUDE-AUDIT-FINAL.md` — 224 lignes, 11,2 Ko
  - `CLAUDE-CLOSURE.md` — 143 lignes, 8,6 Ko
- Rapport d'optimisation architecturale : `RAPPORT-FINAL-OPTIMISATION-SANTANA.md`
