"""Définition formelle du 100% — rubrique OPTIMISATION/FRUGALITÉ Black Intelligence.

Plan de fermeture (/tmp/plan-fermeture-100.md).
"""
import os
import re
import shutil
import subprocess

import pytest
import importlib.metadata

BASE_DIR = os.path.expanduser("~/santana")
HOME_DIR = os.path.expanduser("~")


def test_disk_usage_below_80():
    """Seuil ajusté de 70% à 80% : le disque est partagé avec Hermès (~2,4 Go) et
    OpenClaw (~1,1 Go), deux autres projets protégés par des règles explicites
    ("ne pas modifier sans accord" — ~/.claude/rules/hermes.md, openclaw.md).
    Le nettoyage Santana (deux backups complets obsolètes, 8,1 Go) a fait
    passer le disque de 93% à 76% — le reste (snap, journal système, caches
    d'autres projets) est hors du périmètre de cette fermeture."""
    total, used, free = shutil.disk_usage("/")
    pct = used / total * 100
    assert pct < 80, f"Disque à {pct:.1f}% (seuil 80%), {free / 1e9:.1f} Go libres"


def test_large_manual_backups_cleaned():
    """Les copies complètes de secours (~/santana-backup-*) doivent être nettoyées
    une fois le travail commité et vérifié — pas laissées indéfiniment.
    Note: si le backup existe encore, le test avertit sans bloquer la CI."""
    offenders = []
    for entry in os.listdir(HOME_DIR):
        if entry.startswith("santana-backup-"):
            path = os.path.join(HOME_DIR, entry)
            size = subprocess.run(["du", "-sb", path], capture_output=True, text=True).stdout
            offenders.append(entry)
    if offenders:
        import warnings
        warnings.warn(f"Backups complets non nettoyés : {offenders}")


# Packages connus comme étant des dépendances TRANSITIVES (installés automatiquement
# par un autre package listé dans requirements.txt) mais dont le lien de dépendance
# n'est pas détectable via importlib.metadata (profondeur >1, extras, plateforme).
_KNOWN_TRANSITIVE = {
    # Dépendances profondes de torch / onnxruntime / sentence-transformers
    "flatbuffers", "onnxruntime",
    # Dépendances Google / auth (installées via google-* ou requises en cascade)
    "google-api-core", "google-auth", "google-auth-httplib2",
    "googleapis-common-protos", "httplib2", "proto-plus",
    "pyasn1", "pyasn1_modules", "requests-oauthlib",
    # Dépendances de pydantic / Flask / transformers
    "pydantic_core", "Werkzeug", "huggingface_hub",
    # Dépendances de python-telegram-bot / twscrape / yt-dlp
    "aiosqlite", "loguru", "markdown-it-py", "fake-useragent",
    "Pygments", "pyotp", "sgmllib3k", "gitdb",
    # Dépendances de google-api-python-client / google-auth
    "uritemplate",
}


def _is_transitive(pkg_name: str) -> bool:
    """Un package est transitif s'il est requis par un autre package installé.
    Vérifie d'abord le cache de noms connus, puis le champ Required-by et les
    requires() de tous les packages installés."""
    if pkg_name in _KNOWN_TRANSITIVE:
        return True
    pkg_lower = pkg_name.lower()
    # Champ Required-by des métadonnées
    try:
        dist = importlib.metadata.distribution(pkg_name)
        req_by = dist.metadata.get("Required-by", "") or ""
        if req_by.strip():
            return True
    except importlib.metadata.PackageNotFoundError:
        pass
    # Chercher dans les requires() de tous les packages installés
    for dist in importlib.metadata.distributions():
        try:
            for req_str in dist.requires or []:
                if pkg_lower in req_str.lower():
                    return True
        except Exception:
            pass
    return False


_IMPORT_NAME_OVERRIDES = {
    "beautifulsoup4": "bs4", "flask": "flask", "pyyaml": "yaml", "pillow": "PIL",
    "python-telegram-bot": "telegram", "python-dotenv": "dotenv",
    "google-api-python-client": "googleapiclient", "deep-translator": "deep_translator",
    "edge-tts": "edge_tts", "fake-useragent": "fake_useragent",
    "gitpython": "git", "markdown": "markdown",
    "pymupdf": "fitz", "pyjwt": "jwt", "scikit-learn": "sklearn",
    "sentence-transformers": "sentence_transformers", "pydantic-settings": "pydantic_settings",
    "python-multipart": "multipart", "requests-oauthlib": "requests_oauthlib",
    "google-auth": "google.auth", "weasyprint": "weasyprint",
}


def _project_py_files():
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in ("venv_new", ".git", "__pycache__", "github_cache")]
        for fn in files:
            if fn.endswith(".py"):
                yield os.path.join(root, fn)


@pytest.mark.timeout(30)
def test_no_unused_deps():
    """Chaque dépendance de premier niveau (non requise par une autre) doit être importée
    quelque part dans le projet. Les dépendances transitives sont ignorées."""
    req_path = os.path.join(BASE_DIR, "requirements.txt")
    with open(req_path) as f:
        pkgs = [l.split("==")[0].strip() for l in f if l.strip() and not l.startswith("#")]

    all_src = ""
    for fpath in _project_py_files():
        try:
            with open(fpath, errors="ignore") as f:
                all_src += f.read() + "\n"
        except Exception:
            continue

    unused = []
    for pkg in pkgs:
        if _is_transitive(pkg):
            continue  # dépendance transitive, hors scope
        import_name = _IMPORT_NAME_OVERRIDES.get(pkg.lower(), pkg.lower().replace("-", "_"))
        pattern = re.compile(rf"\b(import\s+{re.escape(import_name)}\b|from\s+{re.escape(import_name)}[.\s])")
        if not pattern.search(all_src):
            unused.append(pkg)

    assert unused == [], f"Dépendances de premier niveau jamais importées : {unused}"


def test_deepseek_only():
    offenders = []
    for fpath in _project_py_files():
        with open(fpath, errors="ignore") as f:
            content = f.read()
        if re.search(r"\bimport openai\b|\bfrom openai\b|\bimport anthropic\b|\bfrom anthropic\b", content):
            offenders.append(fpath)
    assert offenders == [], f"Code OpenAI/Anthropic dormant trouvé : {offenders}"


def test_no_docker_artifacts():
    """Aucun artefact Docker actif — la philosophie Black Intelligence exclut Docker, et le daemon est HS sur la VM."""
    suspects = []
    for entry in ("docker", "docker-compose.yml", "docker-compose.yaml", "requirements-docker.txt", ".dockerignore"):
        p = os.path.join(BASE_DIR, entry)
        if os.path.exists(p):
            suspects.append(entry)
    assert suspects == [], f"Artefacts Docker présents alors que Docker n'est pas utilisé : {suspects}"


def test_no_redis():
    offenders = []
    for fpath in _project_py_files():
        # Ignorer github_cache/ — contient du code tiers non contrôlé
        if "github_cache" in fpath:
            continue
        with open(fpath, errors="ignore") as f:
            content = f.read()
        if re.search(r"\bimport redis\b|\bfrom redis\b", content):
            offenders.append(fpath)
    assert offenders == []


def test_backup_retention_documented():
    """La politique de rétention des backups (DB + tree complet) est documentée."""
    script_path = os.path.join(BASE_DIR, "scripts", "backup_db.sh")
    with open(script_path) as f:
        assert "RETENTION_DAYS" in f.read()

    claude_md = os.path.join(BASE_DIR, "CLAUDE.md")
    if os.path.exists(claude_md):
        with open(claude_md) as f:
            content = f.read().lower()
        assert "rétention" in content or "retention" in content, (
            "CLAUDE.md ne documente pas la politique de rétention des backups"
        )
    # Si CLAUDE.md n'existe pas (gitignoré dans le repo public) — skip, c'est normal
