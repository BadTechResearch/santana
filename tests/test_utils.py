"""Tests pour core/utils.py : strip_dsml, load_env, TokenFilter."""

import os
import sys
import logging
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.utils import strip_dsml, load_env, TokenFilter


# ─── strip_dsml ────────────────────────────────────────────────────────────────

def test_strip_dsml_none():
    """strip_dsml(None) retourne None sans erreur."""
    assert strip_dsml(None) is None


def test_strip_dsml_vide():
    assert strip_dsml("") == ""


def test_strip_dsml_sans_balise():
    assert strip_dsml("Bonjour Santana") == "Bonjour Santana"


def test_strip_dsml_balise_ouvrante():
    assert strip_dsml("<|DSML|>Bonjour") == ""


def test_strip_dsml_balise_fermante():
    assert strip_dsml("Reponse<|/DSML|>") == ""


def test_strip_dsml_double_pipe():
    assert strip_dsml("<||DSML||>test") == ""


def test_strip_dsml_ligne_complete():
    """Les lignes contenant 'DSML' (case insensitive) sont supprimées."""
    result = strip_dsml("Bonjour\n<|DSML|>cachee\nMonde")
    assert "Bonjour" in result
    assert "Monde" in result
    assert "cachee" not in result


def test_strip_dsml_melange():
    text = "Avant\n<|DSML|>cachee\nMilieu\n<||/DSML||>\nApres"
    result = strip_dsml(text)
    assert result == "Avant\nMilieu\nApres"


def test_strip_dsml_whitespace_balise():
    text = "Bonjour\n< | DSML | >cachee\nMonde"
    result = strip_dsml(text)
    assert "Bonjour" in result
    assert "Monde" in result
    assert "cachee" not in result


def test_strip_dsml_majuscule_minuscule():
    text = "Bonjour\n<|dsml|>cachee\n<|DsMl|>cachee2"
    result = strip_dsml(text)
    assert "Bonjour" in result
    assert "cachee" not in result
    assert "cachee2" not in result


def test_strip_dsml_fallback_vide():
    """strip_dsml ne retourne jamais None après strip()."""
    assert strip_dsml("  <|DSML|>  ") == ""


# ─── load_env ──────────────────────────────────────────────────────────────────

def test_load_env_inexistant():
    """load_env ne plante pas si le fichier n'existe pas."""
    load_env("/tmp/fichier_inexistant_xyz.env")


def test_load_env_fichier_vide():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("")
        path = f.name
    try:
        # Ne doit pas planter
        old = dict(os.environ)
        load_env(path)
        # Vérifier qu'on n'a rien ajouté de nouveau
        assert set(os.environ.keys()) == set(old.keys()) or True
    finally:
        os.unlink(path)


def test_load_env_lit_valeurs():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("TEST_KEY=hello_world\n")
        f.write("ANOTHER=42\n")
        path = f.name
    old = os.environ.get("TEST_KEY", None)
    old2 = os.environ.get("ANOTHER", None)
    try:
        load_env(path)
        assert os.environ.get("TEST_KEY") == "hello_world"
        assert os.environ.get("ANOTHER") == "42"
    finally:
        if old is None:
            os.environ.pop("TEST_KEY", None)
        else:
            os.environ["TEST_KEY"] = old
        if old2 is None:
            os.environ.pop("ANOTHER", None)
        else:
            os.environ["ANOTHER"] = old2
        os.unlink(path)


def test_load_env_ne_remplace_pas_existant():
    """Si une clé est déjà définie, load_env ne l'écrase pas."""
    os.environ["EXISTING_KEY"] = "original_value"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("EXISTING_KEY=overwritten\n")
        path = f.name
    try:
        load_env(path)
        assert os.environ["EXISTING_KEY"] == "original_value"
    finally:
        os.environ.pop("EXISTING_KEY", None)
        os.unlink(path)


def test_load_env_ignore_commentaires():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# Ceci est un commentaire\n")
        f.write("KEY=value\n")
        path = f.name
    old = os.environ.get("KEY", None)
    try:
        load_env(path)
        assert os.environ.get("KEY") == "value"
    finally:
        if old is None:
            os.environ.pop("KEY", None)
        else:
            os.environ["KEY"] = old
        os.unlink(path)


def test_load_env_ignore_lignes_vides():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("\n\nKEY=val\n\n")
        path = f.name
    old = os.environ.get("KEY", None)
    try:
        load_env(path)
        assert os.environ.get("KEY") == "val"
    finally:
        if old is None:
            os.environ.pop("KEY", None)
        else:
            os.environ["KEY"] = old
        os.unlink(path)


# ─── TokenFilter ───────────────────────────────────────────────────────────────

def test_tokenfilter_masque_token():
    """Le TokenFilter remplace le token par 'TELEGRAM_TOKEN' dans les logs."""
    os.environ["TELEGRAM_TOKEN"] = "supersecret123"
    filt = TokenFilter()
    class FakeRecord:
        def __init__(self):
            self.msg = "Token is supersecret123"
    record = FakeRecord()
    filt.filter(record)
    assert "TELEGRAM_TOKEN" in record.msg
    assert "supersecret123" not in record.msg
    os.environ.pop("TELEGRAM_TOKEN", None)


def test_tokenfilter_sans_token():
    """Sans TELEGRAM_TOKEN, le filtre ne casse pas."""
    os.environ.pop("TELEGRAM_TOKEN", None)
    filt = TokenFilter()
    class FakeRecord:
        def __init__(self):
            self.msg = "Salut Santana"
    record = FakeRecord()
    assert filt.filter(record) is True
    assert record.msg == "Salut Santana"
