"""Outil de lecture PDF basé sur pypdf.
Permet à Santana d'extraire le texte de fichiers PDF (uploads, pièces jointes, etc.)."""

import os
import logging
from core.utils import get_base_dir

# ─── Extractions supportées ───────────────────────────────────────────────
SAFE_BASE = get_base_dir()


def read_pdf(path: str, max_chars: int = 10000) -> str:
    """Extrait le texte d'un fichier PDF.

    Args:
        path: Chemin absolu ou relatif depuis ~/santana/ du fichier PDF
        max_chars: Nombre max de caractères à extraire (défaut: 10 000, max: 50 000)

    Returns:
        Texte extrait du PDF (page par page, avec numérotation)
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return "Erreur: pypdf non installé (pip install pypdf)"

    # Résoudre le chemin
    if path.startswith("/"):
        abs_path = os.path.realpath(path)
    else:
        abs_path = os.path.realpath(os.path.join(SAFE_BASE, path))

    # Vérifier que le fichier existe et est un .pdf
    if not os.path.exists(abs_path):
        return f"Erreur: fichier introuvable → {abs_path}"

    if not abs_path.lower().endswith(".pdf"):
        return f"Erreur: {path} n'est pas un fichier PDF"

    # Sécurité : rester dans ~/santana/ sauf pour /tmp/ (uploads Telegram)
    if not abs_path.startswith(SAFE_BASE) and not abs_path.startswith("/tmp/"):
        return "Erreur: accès PDF autorisé uniquement dans ~/santana/ ou /tmp/"

    limit = min(int(max_chars), 50000)

    try:
        reader = PdfReader(abs_path)
        num_pages = len(reader.pages)
        pages_text = []
        total_chars = 0

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                # Nettoyer
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                cleaned = "\n".join(lines)
                page_label = f"\n--- Page {i + 1}/{num_pages} ---\n"
                block = page_label + cleaned

                if total_chars + len(block) > limit:
                    remaining = limit - total_chars
                    pages_text.append(block[:remaining])
                    pages_text.append("\n[... tronqué ...]")
                    total_chars = limit
                    break
                else:
                    pages_text.append(block)
                    total_chars += len(block)

        if not pages_text:
            return f"⚠️ PDF '{os.path.basename(abs_path)}' ({num_pages} pages) : aucune extraction de texte possible (peut-être scanné/image)."

        header = f"📄 {os.path.basename(abs_path)} — {num_pages} page(s), {total_chars} chars extraits"
        result = header + "".join(pages_text)
        logging.info(f"[PDF] Lu: {os.path.basename(abs_path)} ({num_pages}p, {total_chars}c)")
        return result

    except Exception as e:
        err = str(e)
        logging.error(f"[PDF] Erreur lecture {path}: {err[:200]}")
        return f"Erreur lecture PDF {os.path.basename(abs_path)}: {err[:300]}"
