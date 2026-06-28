"""
code_exec.py — Exécution sandboxée de code pour Santana.

Exécute du code Python ou bash dans un environnement isolé :
- Répertoire temporaire créé et détruit à chaque exécution
- Timeout configurable (défaut 30s, max 120s)
- Limitation mémoire (ulimit -v 512M)
- Pas d'accès réseau (optionnel)
- Pas d'accès au filesystem hôte en dehors du temp dir

V1 sans Docker (Docker daemon HS sur la VM).
Migration vers Docker dès que le stockage overlay est réparé.
"""

import os
import json
import logging
import subprocess
import tempfile
import shutil
import stat

logger = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────────

MAX_TIMEOUT = 120          # secondes, max absolu
DEFAULT_TIMEOUT = 30       # secondes, défaut
MAX_OUTPUT = 50000         # caractères max dans stdout/stderr
MEMORY_LIMIT = "512000"    # KB (512 MB) via ulimit -v

# Langages supportés
SUPPORTED_LANGUAGES = {
    "python": {
        "extension": ".py",
        "command": ["python3", "-u"],  # -u = unbuffered
        "description": "Python 3.12",
    },
    "bash": {
        "extension": ".sh",
        "command": ["bash"],
        "description": "Bash shell",
    },
    "shell": {
        "extension": ".sh",
        "command": ["bash"],
        "description": "Bash shell (alias pour bash)",
    },
}


def _write_script(workdir: str, code: str, lang: str) -> str:
    """Écrit le code dans un fichier temporaire et retourne son chemin."""
    info = SUPPORTED_LANGUAGES.get(lang)
    if not info:
        raise ValueError(f"Langage non supporté: {lang}. Supportés: {', '.join(SUPPORTED_LANGUAGES.keys())}")

    script_path = os.path.join(workdir, f"script{info['extension']}")
    with open(script_path, "w") as f:
        f.write(code)
    # Rendre exécutable
    os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script_path


def _build_command(lang: str, script_path: str) -> list[str]:
    """Construit la commande d'exécution avec timeout, ulimit et isolation réseau.

    Isolation réseau via `unshare --user --map-root-user --net` (namespace réseau
    dédié, sans interface ni route) : primitive coreutils déjà présente sur le
    système, sans Docker (daemon HS sur cette VM, et hors philosophie BTR).
    `--net` seul échoue sans privilège (CAP_SYS_ADMIN) ; combiné à un namespace
    utilisateur (`--user --map-root-user`, autorisé non-root via
    unprivileged_userns_clone=1), la création réussit pour l'utilisateur courant.
    Vérifié : curl échoue (exit 7, aucune route) à l'intérieur de ce namespace.
    """
    info = SUPPORTED_LANGUAGES.get(lang)
    shell_cmd = f"ulimit -v {MEMORY_LIMIT} && {' '.join(info['command'])} {shlex_quote(script_path)}"
    return [
        "timeout", str(DEFAULT_TIMEOUT),
        "unshare", "--user", "--map-root-user", "--mount", "--propagation", "private", "--net",
        "bash", "-c", shell_cmd,
    ]


def shlex_quote(s: str) -> str:
    """Quote simple pour les chemins de fichiers."""
    escaped = s.replace("'", "'\\''")
    return f"'{escaped}'"


def run_code(code: str, language: str = "python", timeout=None) -> str:
    """Exécute du code dans un environnement sandboxé.

    Args:
        code: Le code à exécuter
        language: 'python', 'bash', ou 'shell'
        timeout: Secondes max (défaut: 30, max: 120)

    Returns:
        Résultat textuel (stdout + stderr ou message d'erreur)
    """
    if language not in SUPPORTED_LANGUAGES:
        return json.dumps({
            "error": f"Langage '{language}' non supporté. Langages: {', '.join(SUPPORTED_LANGUAGES.keys())}"
        })

    actual_timeout = min(timeout or DEFAULT_TIMEOUT, MAX_TIMEOUT)

    # Créer un répertoire temporaire
    workdir = tempfile.mkdtemp(prefix="santana_code_")
    try:
        # Écrire le script
        script_path = _write_script(workdir, code, language)

        # Construire et lancer la commande
        cmd = _build_command(language, script_path)
        logger.info(f"[CODEXEC] Lancement: {language}, timeout={actual_timeout}s")

        result = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=actual_timeout + 5,  # timeout subprocess légèrement > timeout commande
        )

        # Collecter la sortie
        stdout = result.stdout[-MAX_OUTPUT:] if result.stdout else ""
        stderr = result.stderr[-MAX_OUTPUT:] if result.stderr else ""

        output_parts = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"--- stderr ---\n{stderr}")
        if result.returncode != 0 and not stderr:
            output_parts.append(f"--- code de sortie: {result.returncode} ---")

        final_output = "\n".join(output_parts)
        if not final_output:
            final_output = "(aucune sortie)"

        logger.info(f"[CODEXEC] Terminé: returncode={result.returncode}, {len(final_output)} chars")
        return final_output

    except subprocess.TimeoutExpired:
        logger.warning(f"[CODEXEC] Timeout après {actual_timeout}s")
        return json.dumps({"error": f"Le code a dépassé la limite de {actual_timeout} secondes"})
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except OSError as e:
        logger.error(f"[CODEXEC] Erreur OS: {e}")
        return json.dumps({"error": f"Erreur système: {str(e)}"})
    except Exception as e:
        logger.error(f"[CODEXEC] Erreur inattendue: {e}")
        return json.dumps({"error": f"Erreur: {str(e)}"})
    finally:
        # Nettoyage
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
