# MÉMOIRE VIVANTE — VERROU RIGIDE

**Date de gel :** 14 juin 2026
**Ordonné par :** Serge
**Validé par :** Hermès (architecte BTR)

---

## Statut : 🔒 VERROUILLÉ

Le système mémoire de Santana est déclaré **frozen** à compter de cette date.

Aucune modification du système mémoire (memory/, atlas_engine/, injection dans orchestrator.py/react_loop.py/context.py) ne peut être effectuée **sans l'accord explicite et écrit de Serge**.

---

## Ce qui est verrouillé

| Couche | Fichiers | Fonctions |
|--------|----------|-----------|
| Couche Bleue (buffer session) | `agent/context.py` | `push_exchange()`, `get_session_buffer()`, `get_session_summary()` |
| Couche Argent (SQLite) | `memory/memory.py` | `save_message()`, `get_recent_memory()`, `auto_summarize()` |
| Couche Or (Atlas vectoriel) | `atlas_engine/` | `build_memoire_vivante()`, `learn()`, `search()`, `detect_conflicts()` |
| Injection mémoire | `agent/orchestrator.py` (l.255-290) | `build_system_prompt()` — section mémoire |
| Contexte récent | `core/react_loop.py` (l.144-148) | Appel à `get_recent_memory(30)` |

---

## État certifié au moment du gel

- `get_recent_memory()` : limite = **30** messages, troncature = **800** chars, ordre = **ORDER BY id DESC**
- `build_system_prompt()` : injecte **3 couches** (RAM buffer + SQLite filet + Atlas vectoriel)
- `sentence_transformers` (all-MiniLM-L6-v2) : **fonctionnel**, 384 dimensions
- `push_exchange()` : persiste dans **SQLite** (table `session_buffer`), pas que RAM
- Taille typique du prompt avec mémoire : **~25K chars**

---

## Procédure de déverrouillage

1. Demander l'accord de Serge **dans ce channel Telegram**
2. Attendre sa réponse explicite ("oui", "go", "tu peux modifier")
3. Faire un backup complet : `cp -r santana santana-backup-YYYY-MM-DD`
4. Modifier
5. Relancer le benchmark complet (BTR V5)
6. Mettre à jour la date de ce document si déverrouillage partiel

---

*Fichier scellé par Hermès le 14 juin 2026. Toute modification non autorisée de ce fichier sera détectée.*
