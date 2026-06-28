# Brief Claude Code — EXÉCUTION : Correction complète Atlas Mémoire Vivante

## Contexte

Tu travailles sur l'agent **Santana** dans `~/santana/`. Tu as déjà fait un diagnostic complet du système Atlas il y a quelques minutes. Ce brief est pour **EXÉCUTER** les correctifs que tu as toi-même proposés.

Tu as accès :
- Environnement : `~/santana/venv_new/bin/python3`
- Git : `cd ~/santana && git add ... && git commit -m "..."` (auto-push activé)
- Service Santana : `systemctl --user restart santana.service` (redémarrage à la fin)

## RÈGLE ABSOLUE

**1. Ne JAMAIS arrêter Santana en cours de route.** Santana tourne et des utilisateurs (Serge) sont en train de lui parler. On corrige les fichiers, on commit, et on redémarre UNE SEULE FOIS à la fin.

**2. Backuper AVANT chaque modification** : `cp fichier.py fichier.py.bak.$(date +%s)`

**3. Tester APRÈS chaque modification** : `python3 -m py_compile fichier.py`

## Objectif : 10/10 sur TOUS les composants

Les composants à corriger (notes actuelles → 10/10) :
| Composant | Note | Cible |
|---|---|---|
| Moteur vectoriel (embeddings.py) | 2/10 | 10/10 |
| Memory injector (6 KB cap) | 2/10 | 10/10 |
| _extract_persons | 3/10 | 10/10 |
| Décisions registre | 2/10 | 10/10 |
| vision_btr.md | 4/10 | 10/10 |
| famille.md | 5/10 | 10/10 |
| projets.md | 6/10 | 10/10 |
| psychologie.md | 7/10 | 10/10 |
| Flux mensuel | 6/10 | 10/10 |
| Mémoire causale | 1/10 | 10/10 |
| detect_conflicts | 1/10 | 10/10 |

---

## PHASE 0 — STABILISER (P0, 2 fichiers)

### Correctif 1 : `atlas_engine/embeddings.py` — `rebuild_if_needed()` par mtime

**Lignes 241-262.** Actuellement compare les NOMS de fichiers seulement → index figé depuis le 27 mai. 476/775 chunks invisibles.

**Remplacer la fonction entière** `rebuild_if_needed()` par :

```python
def rebuild_if_needed() -> bool:
    """Rebuild si l'index est plus vieux qu'un fichier source ou si les fichiers changent."""
    if not os.path.exists(LIVRES_DIR):
        return False
    current_files = sorted(f for f in os.listdir(LIVRES_DIR) if f.endswith(".md"))
    if not os.path.exists(INDEX_PATH) or not os.path.exists(EMBED_PATH):
        build_index()
        return True
    try:
        index_mtime = os.path.getmtime(INDEX_PATH)
        for fname in current_files:
            fpath = os.path.join(LIVRES_DIR, fname)
            if os.path.getmtime(fpath) > index_mtime:
                logging.info(f"[EMBED] {fname} modifié depuis dernier index → rebuild")
                build_index()
                return True
        with open(INDEX_PATH, "r") as f:
            index_data = json.load(f)
        if current_files != index_data.get(_CHUNK_FILES_KEY, []):
            build_index()
            return True
        return False
    except Exception as e:
        logging.error("[EMBED] Rebuild check failure: %s", e)
        build_index()
        return True
```

### Correctif 2 : `atlas_engine/memory_injector.py` — `MAX_VIVANTE_BYTES`

**Ligne 23 :** Passer de `MAX_VIVANTE_BYTES = 6_000` à `MAX_VIVANTE_BYTES = 16_000`

**Fonction `build_memoire_vivante()` :** Inverser l'ordre des parties :
- AVANT : Flux → Registres → Livres (flux écrase tout)
- APRÈS : **Registres → Livres → Flux** (flux en dernier, tronqué si nécessaire)

---

## PHASE 1 — NETTOYER (P1, 2 fichiers)

### Correctif 3 : `atlas_engine/atlas.py` — `_extract_persons`

**Lignes 229-256.** Deux problèmes :
1. Le pattern `contact` (ligne 234) capture des mots ordinaires : `(r'\b(avec|appelle|parlé|discuté|vu)\s+(\w+(?:\s+\w+)?)\b', 'contact')` → **SUPPRIMER cette ligne**
2. Les regex opèrent sur `text.lower()` (ligne 243) au lieu du texte original → passer à `text` original pour respecter la casse

**Modifications :**
- Ligne 234 : supprimer la ligne du pattern `contact`
- Ligne 243 : `t = text.lower()` → `t = text` (ou mieux, utiliser `text` directement dans les regex sans le lowercaster)
- Ajouter à `_PERSON_STOPLIST` : `{'les', 'des', 'une', 'sur', 'dans', 'pour', 'avec', 'est', 'fait', 'note'}`

### Correctif 4 : `core/react_loop.py` — Passer le vrai message à `learn()`

**Ligne 537-539 :** Actuellement :
```python
_atlas_learn(context_enriched, response)
```
`context_enriched` contient 20 messages d'historique + le message actuel → les regex d'extraction analysent tout l'historique au lieu de l'échange actuel.

**Remplacer par :**
```python
_atlas_learn(user_message, response)
```

(Ajouter un logging debug pour vérifier : `logging.debug(f"[FINALIZE] Atlas learn(user_message={user_message[:100]})")`)

---

## PHASE 2 — ÉQUILIBRER (P1, 1 fichier)

### Correctif 5 : `atlas_engine/embeddings.py` — Plafond de chunks par livre

**Dans la fonction `search()` (lignes 201-238), APRÈS le tri par score :** Ajouter une limite de MAX_CHUNKS_PER_BOOK = 2 pour garantir la diversité des résultats.

```python
# Après scores[idx], avant results.append
book_count = {}
for idx in indices:
    if scores[idx] < threshold:
        continue
    chunk = _chunks[idx]
    book = chunk["book"]
    if book_count.get(book, 0) >= 2:
        continue
    book_count[book] = book_count.get(book, 0) + 1
    # ... suite du code original
```

### Correctif 6 : Rebuild de l'index

Après la correction de rebuild_if_needed(), forcer un rebuild :
```bash
cd ~/santana && ./venv_new/bin/python3 -c "
from atlas_engine.embeddings import build_index
build_index()
print('Index rebuild OK')
"
```

---

## PHASE 3 — ACTIVER (P2, 2 fichiers)

### Correctif 7 : `atlas_engine/atlas.py` — Appeler `_resoudre_causalite()` automatiquement

**Après la ligne 557 (scoring), ajouter :**

```python
# Résolution automatique de causalité
_RESULTAT_PATTERNS = [
    r'\b(c\'est fait|ça marche|j\'ai fait|j\'ai terminé|c\'est bon|réussi|déployé|corrigé|fini|terminé)\b'
]
if any(re.search(p, combined.lower()) for p in _RESULTAT_PATTERNS):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, decision_text FROM atlas_causalite WHERE statut='en_cours' ORDER BY id DESC LIMIT 5")
        for dec_id, dec_text in c.fetchall():
            if _cosine_similarity(combined[:200], dec_text[:200]) > 0.65:
                _resoudre_causalite(dec_text[:60], user_message[:200])
                break
    except Exception as _ce:
        logging.debug(f"[ATLAS] Auto-resolve causalite: {_ce}")
```

### Correctif 8 : `atlas_engine/memory_injector.py` — Lire décisions depuis SQLite

**Fonction `_load_decision_texts()` (lignes 202-213) :** Actuellement lit le fichier `decisions.md` figé du 29 mai. Remplacer par lecture SQLite :

```python
def _load_decision_texts() -> list[str]:
    """Charge les décisions depuis SQLite (source vivante)."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT content FROM registres WHERE type='decisions' ORDER BY id DESC LIMIT 30")
        return [r[0] for r in c.fetchall() if "[DÉCISION]" in r[0] or len(r[0]) > 20]
    except Exception as e:
        logging.error("[MEMORY_INJECTOR] _load_decision_texts SQLite echec: %s", e)
    # Fallback fichier
    decisions_path = os.path.join(os.path.expanduser("~/santana"), "memory", "registre", "registre-2026-06.md")
    try:
        with open(decisions_path) as f:
            return [l.strip() for l in f if "[DÉCISION]" in l]
    except Exception:
        return []
```

---

## PHASE 4 — OPTIMISATION FINALE

### Correctif 9 : Déduplication des flux

**`atlas_engine/atlas.py` — `_write_flux_md()` (ligne 340-358) :** Ajouter une vérification des 5 dernières lignes du flux pour éviter les doublons. Si le hash du contenu (texte + minute) est déjà dans les 5 dernières lignes, ignorer.

### Correctif 10 : Rebuild + test final

```bash
cd ~/santana && ./venv_new/bin/python3 -c "
from atlas_engine.embeddings import build_index, search
n = build_index()
print(f'Index rebuilt: {n} chunks')

# Test 5 requêtes
tests = [
    'budget sécurité RDC',
    'mémoire vivante',
    'dates naissance famille',
    'migration Oracle',
    'DeepSeek Flash'
]
for q in tests:
    r = search(q, top_k=3, threshold=0.20)
    print(f'  {q}: {len(r)} results')
    for book, score, section, extrait in r:
        print(f'    [{book}] {score:.3f}')
"
```

---

## COMMANDES DE VÉRIFICATION FINALE

Après tous les correctifs et le rebuild :

```bash
cd ~/santana && ./venv_new/bin/python3 -c "
from atlas_engine.embeddings import search, get_stats
from atlas_engine.atlas import learn
import os

# 1. Vérifier l'index
st = get_stats()
print(f'Index: {st[\"chunks\"]} chunks, {st[\"books\"]} books')
assert st['chunks'] > 700, f'Trop peu de chunks: {st[\"chunks\"]}'

# 2. Vérifier la recherche diversifiée
r = search('mémoire', top_k=6, threshold=0.20)
books = set(book for book,_,_,_ in r)
print(f'Diversité: {len(books)}/{len(r)} livres différents')
assert len(books) >= 3, f'Pas assez diversifié: {books}'

# 3. Vérifier memory_injector
from atlas_engine.memory_injector import build_memoire_vivante
mv = build_memoire_vivante('test')
print(f'Mémoire vivante: {len(mv)} chars')
assert len(mv) > 8000, f'Trop petit: {len(mv)} chars'

print('TOUS LES TESTS PASSENT')
"
```

---

## FINALISATION

1. Après tous les correctifs : `cd ~/santana && git add -A && git commit -m "Atlas V2: 10/10 sur tous les composants"` (auto-push)
2. Redémarrer Santana : `systemctl --user restart santana.service`
3. Vérifier les logs : `journalctl --user -u santana.service --no-pager -n 10`
4. Confirmer que le service est actif : `systemctl --user is-active santana.service`

**Contrainte :** Ne pas interrompre Santana pendant les correctifs. Ne redémarrer qu'à la fin.
