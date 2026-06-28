#!/usr/bin/env python3
"""
Rotation mensuelle automatique pour la mémoire Santana.
- Flux : fichier par mois flux-YYYY-MM.md
- Registres : registre-YYYY-MM.md
- Livres : pas de rotation (connaissances permanentes)
- Archive les anciens fichiers flux quotidiens dans memory/archive/
"""
import os, re, logging, shutil
from datetime import datetime

BASE_DIR = os.path.expanduser("~/santana/memory")

logger = logging.getLogger(__name__)


def month_file(category: str, year: int = None, month: int = None) -> str:
    """Retourne le nom de fichier pour un mois donné.
    category: 'flux' ou 'registre'
    """
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    return f"{category}-{y}-{m:02d}.md"


def month_path(category: str, year: int = None, month: int = None) -> str:
    """Retourne le chemin complet du fichier mensuel."""
    return os.path.join(BASE_DIR, category, month_file(category, year, month))


def ensure_month_file(category: str, year: int = None, month: int = None) -> str:
    """Crée le fichier du mois s'il n'existe pas, retourne le chemin."""
    path = month_path(category, year, month)
    if not os.path.exists(path):
        now = datetime.now()
        y = year or now.year
        m = month or now.month
        label = {"flux": "Flux Santana", "registre": "Registre"}.get(category, category.capitalize())
        header = f"# {label} — {y}-{m:02d}\n\n"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(header)
            logger.info(f"[ROTATE] Nouveau fichier créé: {path}")
        except Exception as e:
            logger.error(f"[ROTATE] Erreur création {path}: {e}")
    return path


def archive_old_flux_files(year: int = None, month: int = None) -> int:
    """Déplace les fichiers flux quotidiens (YYYY-MM-DD_semaine.md) du mois dans l'archive.
    Retourne le nombre de fichiers archivés.
    """
    now = datetime.now()
    y = year or now.year
    m = month or now.month
    prefix = f"{y}-{m:02d}"
    flux_dir = os.path.join(BASE_DIR, "flux")
    archive_dir = os.path.join(BASE_DIR, "archive")

    if not os.path.exists(flux_dir):
        return 0
    os.makedirs(archive_dir, exist_ok=True)

    count = 0
    for fname in os.listdir(flux_dir):
        if fname.startswith(prefix) and fname.endswith("_semaine.md"):
            src = os.path.join(flux_dir, fname)
            dst = os.path.join(archive_dir, fname.replace("_semaine.md", f"_semaine_{y}{m:02d}.md"))
            # Éviter d'écraser si déjà archivé
            if not os.path.exists(dst):
                shutil.move(src, dst)
                logger.info(f"[ROTATE] Archivé: {fname} → archive/")
                count += 1
    return count


def rotate_all():
    """Vérifie et exécute la rotation pour toutes les catégories.
    À appeler au démarrage de Santana.
    """
    now = datetime.now()
    y, m = now.year, now.month

    # 1. S'assurer que les fichiers du mois existent
    for cat in ["flux", "registre"]:
        ensure_month_file(cat, y, m)

    # 2. Archiver les vieux fichiers flux quotidiens
    archived = archive_old_flux_files(y, m)
    if archived:
        logger.info(f"[ROTATE] {archived} fichiers flux archivés pour {y}-{m:02d}")

    return archived


def get_current_flux_path() -> str:
    """Retourne le chemin du fichier flux du mois en cours."""
    return ensure_month_file("flux")
