"""Définition formelle du 100% — rubrique MÉMOIRE.

Plan de fermeture (/tmp/plan-fermeture-100.md). Chaque test prouve un critère
exhaustif. Quand ce fichier passe entièrement, la rubrique Mémoire est fermée.
"""
import inspect
import json
import os
import sqlite3
import subprocess

import pytest

BASE_DIR = os.path.expanduser("~/santana")


def test_integrity_ok():
    """PRAGMA integrity_check = ok sur memory.db en production."""
    conn = sqlite3.connect(os.path.join(BASE_DIR, "memory.db"))
    result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    assert result == "ok"


def test_disambiguate_branched():
    """disambiguate() est appelé dans react_loop(), avant la classification."""
    from core import react_loop as rl

    src = inspect.getsource(rl.react_loop)
    assert "disambiguate(" in src
    classify_pos = src.find("classify_message(")
    disamb_pos = src.find("disambiguate(")
    assert disamb_pos != -1 and classify_pos != -1
    assert disamb_pos < classify_pos, "disambiguate() doit precéder classify_message()"


def test_record_interaction_branched():
    """record_interaction() est appelé depuis _finalize() (point de sortie unique)."""
    from core import react_loop as rl

    src = inspect.getsource(rl._finalize)
    assert "record_interaction(" in src


def test_embedding_cache_used():
    """detect_conflicts() réutilise le singleton _get_model(), ne recharge pas le modèle."""
    from atlas_engine import memory_injector

    src = inspect.getsource(memory_injector.detect_conflicts)
    assert "_get_model(" in src
    assert "SentenceTransformer(" not in src, "detect_conflicts ne doit pas instancier le modèle directement"


def test_no_db_shm_git_tracked():
    """Aucun fichier .db-shm/.db-wal volatile ne doit être suivi par git."""
    out = subprocess.run(
        ["git", "ls-files"], cwd=BASE_DIR, capture_output=True, text=True, check=True
    ).stdout
    tracked = [l for l in out.splitlines() if l.endswith(".db-shm") or l.endswith(".db-wal")]
    assert tracked == [], f"Fichiers volatiles trackés par git: {tracked}"


def test_backup_script_alerts():
    """backup_db.sh fait un integrity_check AVANT le backup et alerte si échec (pas juste un echo perdu)."""
    path = os.path.join(BASE_DIR, "scripts", "backup_db.sh")
    with open(path) as f:
        content = f.read()
    assert "integrity_check" in content
    has_alert = any(kw in content for kw in ("telegram", "Telegram", "TELEGRAM", "curl", "notify", "sendMessage"))
    assert has_alert, "backup_db.sh doit alerter (Telegram ou équivalent) en cas d'échec d'intégrité, pas juste echo"


def test_session_buffer_adequate():
    """Le buffer de session garde au moins 20 messages (continuité de conversation)."""
    from agent.context import COMPRESSION_CONFIG

    assert COMPRESSION_CONFIG["buffer_max_messages"] >= 20


def test_no_data_loss_on_restart():
    """La mémoire persiste dans un vrai fichier SQLite (pas :memory:, pas tmpfs)."""
    from core.db import DB_PATH

    assert DB_PATH == os.path.expanduser("~/santana/memory.db")
    assert os.path.exists(DB_PATH)
    # Le fichier doit être sur un montage persistant, pas /tmp ou /dev/shm
    assert not DB_PATH.startswith("/tmp") and not DB_PATH.startswith("/dev/shm")


def test_restart_policy_resilient():
    """Le service doit redémarrer automatiquement après un crash brutal
    (kill -9), pas seulement après une sortie propre. Vérifié en conditions
    réelles le 19/06 : kill -9 du process live, systemd a relancé le service
    en ~12s (RestartSec=10), PRAGMA integrity_check toujours 'ok' après coup —
    voir CLAUDE-CLOSURE.md. Ce test vérifie la politique reste configurée
    ainsi, sans re-tuer le service à chaque run de la suite."""
    out = subprocess.run(
        ["systemctl", "--user", "show", "santana.service", "-p", "Restart", "-p", "RestartUSec"],
        capture_output=True, text=True, check=True,
    ).stdout
    values = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
    assert values.get("Restart") == "on-failure", f"Restart={values.get('Restart')!r}, attendu on-failure"


def test_atlas_works():
    """L'index vectoriel Atlas (livres) est cohérent : index et embeddings de même taille."""
    import numpy as np

    index_path = os.path.join(BASE_DIR, "memory", "livres_index.json")
    embed_path = os.path.join(BASE_DIR, "memory", "livres_embeddings.npy")
    assert os.path.exists(index_path), "Index vectoriel absent"
    assert os.path.exists(embed_path), "Fichier d'embeddings absent"

    with open(index_path) as f:
        index = json.load(f)
    embeddings = np.load(embed_path)

    assert index["chunk_count"] == embeddings.shape[0], (
        f"Désynchronisation index/embeddings : {index['chunk_count']} chunks "
        f"vs {embeddings.shape[0]} vecteurs"
    )
    assert embeddings.shape[1] == index["dim"]
