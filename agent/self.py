"""self.py — Auto-connaissance dynamique de Santana.

Construit une carte d'identité précise de Santana à l'instant T,
en scannant son propre code, ses outils, ses tests, et son état.
Remplacer la description statique qui devient obsolète à chaque mise à jour.
"""

import os
import logging
import subprocess
import glob
from datetime import datetime

BASE_DIR = os.path.expanduser("~/santana")

logger = logging.getLogger(__name__)


# ─── 1. Scan des fichiers soul/ ───────────────────────────────────────

def scan_soul() -> dict:
    """Lit les fichiers de personnalité (SOUL, RULES, STYLE, USER)."""
    soul_dir = os.path.join(BASE_DIR, "soul")
    result = {}
    for fname in ["SOUL.md", "RULES.md", "STYLE.md", "USER.md"]:
        fpath = os.path.join(soul_dir, fname)
        if os.path.exists(fpath):
            with open(fpath) as f:
                content = f.read().strip()
            result[fname] = {
                "taille": len(content),
                "lignes": content.count("\n") + 1,
                "preview": content[:200],
            }
        else:
            result[fname] = None
    return result


# ─── 2. Scan du registre d'outils ─────────────────────────────────────

def scan_registry() -> dict:
    """Liste tous les outils disponibles via le registre live (tools/registry.py).

    Ne lit plus tools/tools.json (fichier statique qui se désynchronisait du
    registre réel — Santana se décrivait alors avec des outils inexacts).
    """
    try:
        # Forcer le chargement complet du registry avant la lecture
        try:
            import tools.tools as _tt  # noqa: F401
        except Exception:
            pass
        from tools.registry import get_tool_names, _TOOL_REGISTRY
        # Forcer aussi le chargement via les outils enregistrés dans tools.py
        if not _TOOL_REGISTRY:
            try:
                from tools.tools import TOOLS as _TOOLS  # noqa: F401
            except Exception:
                pass
        outils = get_tool_names()
        return {
            "total": len(outils),
            "outils": sorted(outils),
        }
    except Exception as e:
        logger.error(f"[SELF] scan_registry: {e}")
        return {"total": 0, "outils": [], "erreur": str(e)}


# ─── 3. Scan des modules agent/ ───────────────────────────────────────

def scan_agent() -> dict:
    """Liste les modules Python dans agent/ et leurs fonctions principales."""
    agent_dir = os.path.join(BASE_DIR, "agent")
    modules = {}
    for fpath in sorted(glob.glob(os.path.join(agent_dir, "*.py"))):
        fname = os.path.basename(fpath)
        if fname == "__init__.py":
            continue
        with open(fpath) as f:
            content = f.read()
        lignes = content.count("\n") + 1
        # Extraire les noms de fonctions
        fonctions = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("def "):
                fn_name = line.split("(")[0].replace("def ", "").strip()
                if not fn_name.startswith("_"):
                    fonctions.append(fn_name)
        modules[fname.replace(".py", "")] = {
            "taille": len(content),
            "lignes": lignes,
            "fonctions_publiques": fonctions,
        }
    return modules


# ─── 3b. Scan mémoire et atlas ──────────────────────────────────────────

def scan_memory() -> dict:
    """Liste les modules dans memory/ et atlas_engine/ pour auto-description."""
    dirs_to_scan = ["memory", "atlas_engine"]
    modules = {}
    for dirname in dirs_to_scan:
        dpath = os.path.join(BASE_DIR, dirname)
        if not os.path.exists(dpath):
            continue
        for fpath in sorted(glob.glob(os.path.join(dpath, "*.py"))):
            fname = os.path.basename(fpath)
            if fname == "__init__.py":
                continue
            with open(fpath) as f:
                content = f.read()
            lignes = content.count("\n") + 1
            fonctions = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("def ") and not line.startswith("def _"):
                    fn_name = line.split("(")[0].replace("def ", "").strip()
                    fonctions.append(fn_name)
            modules[f"{dirname}/{fname.replace('.py', '')}"] = {
                "taille": len(content),
                "lignes": lignes,
                "fonctions_publiques": fonctions,
            }
    return modules


# ─── 4. Scan des tests ────────────────────────────────────────────────

def scan_tests() -> dict:
    """Compte les tests disponibles sans les exécuter."""
    test_dir = os.path.join(BASE_DIR, "tests")
    if not os.path.exists(test_dir):
        return {"total": 0, "fichiers": [], "erreur": "dossier tests/ introuvable"}
    fichiers = sorted(glob.glob(os.path.join(test_dir, "test_*.py")))
    total_tests = 0
    details = []
    for fpath in fichiers:
        with open(fpath) as f:
            content = f.read()
        # Compter les fonctions qui commencent par test_
        n = 0
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("def test_") and stripped.endswith(":"):
                n += 1
            elif stripped.startswith("def test_") and "):" in stripped:
                n += 1
        total_tests += n
        details.append({
            "fichier": os.path.basename(fpath),
            "tests": n,
            "lignes": content.count("\n") + 1,
        })
    return {"total": total_tests, "fichiers": details}


# ─── 5. Scan git ──────────────────────────────────────────────────────

def scan_git() -> dict:
    """Dernier commit, branche, fichiers modifiés."""
    try:
        branch = subprocess.run(
            ["git", "-C", BASE_DIR, "branch", "--show-current"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        last_commit = subprocess.run(
            ["git", "-C", BASE_DIR, "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        modified = subprocess.run(
            ["git", "-C", BASE_DIR, "status", "--porcelain"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        modified_list = [l.strip() for l in modified.split("\n") if l.strip()] if modified else []
        return {
            "branche": branch or "inconnue",
            "dernier_commit": last_commit or "inconnu",
            "fichiers_modifies": len(modified_list),
            "fichiers_modifies_liste": modified_list[:10],
        }
    except Exception as e:
        return {"erreur": str(e)}


# ─── 6. Scan système ──────────────────────────────────────────────────

def scan_system() -> dict:
    """Uptime, RAM, disque."""
    info = {}
    try:
        # Uptime
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            info["uptime"] = f"{days}j {hours}h"
    except Exception:
        info["uptime"] = "inconnu"
    try:
        # RAM
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    info["ram_total_gb"] = round(kb / 1024 / 1024, 1)
                elif line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    info["ram_disponible_gb"] = round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    try:
        # Disque
        st = os.statvfs(BASE_DIR)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bavail
        info["disque_total_gb"] = round(total / 1024**3, 1)
        info["disque_libre_gb"] = round(free / 1024**3, 1)
    except Exception:
        pass
    return info


# ─── Build complet : assemble tout ────────────────────────────────────

def build_identity() -> dict:
    """Construit la carte d'identité complète de Santana."""
    return {
        "horodatage": datetime.now().isoformat(),
        "soul": scan_soul(),
        "outils": scan_registry(),
        "agent_modules": scan_agent(),
        "memory_modules": scan_memory(),
        "tests": scan_tests(),
        "git": scan_git(),
        "systeme": scan_system(),
    }


def build_context() -> str:
    """Retourne un résumé court injectable dans le prompt système.
    Utilisé par build_system_prompt() pour que Santana se connaisse.
    """
    identity = build_identity()
    parts = []

    # Outils
    tools = identity.get("outils", {})
    parts.append(f"OUTILS: {tools.get('total', 0)} disponibles.")
    if tools.get("outils"):
        parts.append("Liste: " + ", ".join(tools["outils"]))

    # Modules agent
    modules = identity.get("agent_modules", {})
    mod_names = list(modules.keys())
    if mod_names:
        parts.append(f"MODULES AGENT: {', '.join(mod_names)}")
        for name, info in modules.items():
            parts.append(f"  - {name}: {info.get('lignes', '?')} lignes, {len(info.get('fonctions_publiques', []))} fonctions")

    # Tests
    tests = identity.get("tests", {})
    t_total = tests.get("total", 0)
    t_files = len(tests.get("fichiers", []))
    parts.append(f"TESTS: {t_total} tests dans {t_files} fichiers.")

    # Git
    git = identity.get("git", {})
    if "dernier_commit" in git:
        parts.append(f"GIT: {git.get('dernier_commit')} sur {git.get('branche', '?')}")
        if git.get("fichiers_modifies", 0) > 0:
            parts.append(f"MODIFICATIONS: {git.get('fichiers_modifies')} fichiers non commit")

    # Système
    sys_info = identity.get("systeme", {})
    parts.append(f"SYSTEME: uptime {sys_info.get('uptime', '?')}, "
                 f"RAM {sys_info.get('ram_disponible_gb', '?')}Go libre / {sys_info.get('ram_total_gb', '?')}Go total, "
                 f"disque {sys_info.get('disque_libre_gb', '?')}Go libre")

    return "\n".join(parts)


def build_report() -> str:
    """Retourne un rapport markdown complet pour self_inspect()."""
    identity = build_identity()
    now = identity.get("horodatage", "?")

    lines = [f"# Auto-description Santana — {now}", ""]

    # Personnalité
    lines.append("## Personnalité")
    for fname, info in identity.get("soul", {}).items():
        if info:
            lines.append(f"- {fname}: {info.get('lignes', '?')} lignes")
        else:
            lines.append(f"- {fname}: absent")
    lines.append("")

    # Outils
    tools = identity.get("outils", {})
    lines.append(f"## Outils ({tools.get('total', 0)})")
    for t in tools.get("outils", []):
        lines.append(f"- {t}")
    lines.append("")

    # Modules
    modules = identity.get("agent_modules", {})
    lines.append(f"## Modules agent ({len(modules)})")
    for name, info in modules.items():
        fns = ", ".join(info.get("fonctions_publiques", []))
        lines.append(f"- {name}: {info.get('lignes', '?')} lignes — {fns}")
    lines.append("")

    # Tests
    tests = identity.get("tests", {})
    lines.append(f"## Tests ({tests.get('total', 0)})")
    for f in tests.get("fichiers", []):
        lines.append(f"- {f['fichier']}: {f['tests']} tests")
    lines.append("")

    # Git
    git = identity.get("git", {})
    lines.append("## Git")
    lines.append(f"- Dernier commit: {git.get('dernier_commit', '?')}")
    lines.append(f"- Branche: {git.get('branche', '?')}")
    lines.append(f"- Modifications: {git.get('fichiers_modifies', 0)}")
    lines.append("")

    # Système
    sys_info = identity.get("systeme", {})
    lines.append("## Système")
    lines.append(f"- Uptime: {sys_info.get('uptime', '?')}")
    lines.append(f"- RAM: {sys_info.get('ram_disponible_gb', '?')}Go libre / {sys_info.get('ram_total_gb', '?')}Go total")
    lines.append(f"- Disque: {sys_info.get('disque_libre_gb', '?')}Go libre")
    lines.append("")

    return "\n".join(lines)
