"""Tests mémoire Santana — 10 scénarios pour cartographier le comportement réel.

Utilise une DB isolée + autouse fixture pour garantir l'indépendance.
Exécution :
    cd ~/santana && source venv_new/bin/activate && python -m pytest tests/test_memory_10_scenarios.py -v
"""

import os, sys, tempfile, sqlite3, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_DIR = tempfile.mkdtemp(suffix="_santana_mem_10")
TEST_DB = os.path.join(TEST_DIR, "test_memory_10.db")

import core.db
_ORIG_DB_PATH = core.db.DB_PATH

from memory import memory as mem_mod


def setup_module():
    global _ORIG_BASE_DIR
    _ORIG_BASE_DIR = mem_mod.BASE_DIR
    mem_mod.BASE_DIR = TEST_DIR
    """DB isolée, tables fraîches, UNE SEULE FOIS."""
    os.makedirs(TEST_DIR, exist_ok=True)
    core.db.DB_PATH = TEST_DB
    core.db.close_db()
    conn = core.db.get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT,
        content TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()


def teardown_module():
    import shutil
    try:
        core.db.close_db()
    except Exception:
        pass
    shutil.rmtree(TEST_DIR, ignore_errors=True)
    core.db.DB_PATH = _ORIG_DB_PATH
    mem_mod.BASE_DIR = _ORIG_BASE_DIR


@pytest.fixture(autouse=True)
def clean_memory():
    """Vider la table memory AVANT CHAQUE test — garantit l'indépendance."""
    conn = core.db.get_db()
    conn.execute("DELETE FROM memory")
    conn.commit()
    yield


# ─────────────────────────────────────────────────────────────────────
def test_1_save_and_recall():
    """Un message sauvegardé est récupérable."""
    mem_mod.save_message("user", "Bonjour Santana")
    msgs = mem_mod.get_recent_memory(50)
    assert len(msgs) >= 1
    found = any(m["role"] == "user" and "Bonjour" in m["content"] for m in msgs)
    assert found
    print("    ✅ 1 — Sauvegarde et rappel basique OK")


# ─────────────────────────────────────────────────────────────────────
def test_2_multiple_exchanges():
    """5 échanges sont tous retrouvables, pas de fuite inter-tests."""
    exchanges = [
        ("user", "Quel temps fait-il ?"),
        ("assistant", "Je vais vérifier"),
        ("user", "Merci Santana"),
        ("assistant", "De rien Serge"),
        ("user", "Quelle est la capitale de la RDC ?"),
    ]
    for role, content in exchanges:
        mem_mod.save_message(role, content)

    msgs = mem_mod.get_recent_memory(20)
    assert len(msgs) == 5, f"5 messages attendus, trouvé {len(msgs)}"
    assert msgs[0]["role"] == "user"
    assert "RDC" in msgs[-1]["content"]
    # Vérification anti-fuite : aucun message d'autres tests
    assert not any("Bonjour" in m["content"] for m in msgs), "Fuites inter-tests !"
    print("    ✅ 2 — 5 échanges persistés et isolés OK")


# ─────────────────────────────────────────────────────────────────────
def test_3_survives_reset():
    """Les messages survivent à reset_session()."""
    from agent.context import reset_session

    mem_mod.save_message("user", "Message AVANT reset")
    mem_mod.save_message("assistant", "Réponse AVANT reset")

    reset_session()

    msgs = mem_mod.get_recent_memory(20)
    assert len(msgs) >= 2, f"Messages perdus après reset: {len(msgs)}"
    assert any("AVANT reset" in m["content"] for m in msgs)
    print("    ✅ 3 — Messages survivent au reset_session() OK")


# ─────────────────────────────────────────────────────────────────────
def test_4_rotation_500_limit():
    """510 messages → rotation → ≤500."""
    for i in range(510):
        mem_mod.save_message("user", f"Message test numéro {i}")
    mem_mod.rotate_memory(max_souvenirs=500)
    count = mem_mod.count_memory()
    assert count <= 500, f"Rotation inefficace: {count} > 500"
    print(f"    ✅ 4 — Rotation à 500 : {count} conservés OK")


# ─────────────────────────────────────────────────────────────────────
def test_5_long_content():
    """Contenu de 5000 chars — save_message() stocke sans erreur."""
    long_text = "X" * 5000
    mem_mod.save_message("user", long_text)
    msgs = mem_mod.get_recent_memory(5)
    found = [m for m in msgs if m["role"] == "user"]
    assert len(found) >= 1
    saved = found[0]["content"]
    # save_message() stocke intégralement (c'est react_loop qui tronque à 1000 à l'appel)
    assert len(saved) == 5000, f"Longueur inattendue: {len(saved)}"
    print(f"    ✅ 5 — Contenu 5000 chars stocké intact ({len(saved)}) OK")


# ─────────────────────────────────────────────────────────────────────
def test_6_role_distinction():
    """Les rôles user/assistant sont correctement étiquetés."""
    mem_mod.save_message("user", "Question de Serge")
    mem_mod.save_message("assistant", "Réponse de Santana")
    mem_mod.save_message("user", "Deuxième question")
    mem_mod.save_message("assistant", "Deuxième réponse")

    msgs = mem_mod.get_recent_memory(10)
    users = [m for m in msgs if m["role"] == "user"]
    assistants = [m for m in msgs if m["role"] == "assistant"]
    assert len(users) == 2, f"Attendu 2 users, trouvé {len(users)}"
    assert len(assistants) == 2, f"Attendu 2 assistants, trouvé {len(assistants)}"
    # Ordre : du plus ancien au plus récent
    assert msgs[0]["content"] == "Question de Serge"
    assert msgs[1]["content"] == "Réponse de Santana"
    assert msgs[2]["content"] == "Deuxième question"
    assert msgs[3]["content"] == "Deuxième réponse"
    print("    ✅ 6 — Rôles user/assistant corrects et ordonnés OK")


# ─────────────────────────────────────────────────────────────────────
def test_7_chronological_order():
    """get_recent_memory retourne du plus vieux au plus récent."""
    mem_mod.save_message("user", "Premier message")
    mem_mod.save_message("assistant", "Deuxième")
    mem_mod.save_message("user", "Troisième")

    msgs = mem_mod.get_recent_memory(10)
    assert len(msgs) == 3
    assert msgs[0]["content"] == "Premier message"
    assert msgs[1]["content"] == "Deuxième"
    assert msgs[2]["content"] == "Troisième"
    print("    ✅ 7 — Ordre chronologique (ancien → récent) OK")


# ─────────────────────────────────────────────────────────────────────
def test_8_limit_parameter():
    """Le paramètre limit de get_recent_memory fonctionne."""
    for i in range(20):
        role = "user" if i % 2 == 0 else "assistant"
        mem_mod.save_message(role, f"Message {i}")

    msgs_5 = mem_mod.get_recent_memory(5)
    msgs_20 = mem_mod.get_recent_memory(20)

    assert len(msgs_5) == 5, f"Limit=5: {len(msgs_5)}"
    assert len(msgs_20) == 20, f"Limit=20: {len(msgs_20)}"
    # Les 5 limit sont les 5 PLUS RÉCENTS (donc messages 15-19)
    assert msgs_5[-1]["content"] == "Message 19", f"Dernier message: {msgs_5[-1]['content']}"
    assert msgs_5[0]["content"] == "Message 15", f"Premier des 5: {msgs_5[0]['content']}"
    print("    ✅ 8 — Limit (5 / 20) et sélection des plus récents OK")


# ─────────────────────────────────────────────────────────────────────
def test_9_rapid_consecutive():
    """100 messages rapides → tous stockés sans perte."""
    for i in range(100):
        mem_mod.save_message("user", f"Message rapide #{i}")
    count = mem_mod.count_memory()
    assert count == 100, f"Perte de données: {count}/100"
    msgs = mem_mod.get_recent_memory(100)
    assert len(msgs) == 100
    assert "Message rapide #99" in msgs[-1]["content"]
    print(f"    ✅ 9 — 100 rapides: {count}/100 OK")


# ─────────────────────────────────────────────────────────────────────
def test_10_reset_then_new_messages():
    """Après reset + nouveaux messages, les ANCIENS sont encore là."""
    from agent.context import reset_session

    # Phase 1 : ancienne session
    mem_mod.save_message("user", "Serge: projet mémoire")
    mem_mod.save_message("assistant", "Santana: OK je note")
    mem_mod.save_message("user", "Serge: on continue demain")
    mem_mod.save_message("assistant", "Santana: à demain")

    # /reset
    reset_session()

    # Phase 2 : nouvelle session
    mem_mod.save_message("user", "Serge: je reviens")
    mem_mod.save_message("assistant", "Santana: bienvenue")

    # Vérifier que les 6 messages sont là (4 anciens + 2 nouveaux)
    msgs = mem_mod.get_recent_memory(20)
    assert len(msgs) == 6, f"Attendu 6, trouvé {len(msgs)}"
    assert any("projet mémoire" in m["content"] for m in msgs), \
        "Messages d'avant reset absents !"
    assert any("je reviens" in m["content"] for m in msgs), \
        "Nouveaux messages absents !"
    print("    ✅ 10 — Reset → nouveaux messages → anciens préservés OK")
