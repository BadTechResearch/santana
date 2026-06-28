"""Outil YouTube — métadonnées + transcription via yt-dlp pour Santana.
Permet à Santana de lire les informations complètes d'une vidéo YouTube
(titre, chaîne, durée, description, vues ET transcription des sous-titres).

Utilise yt-dlp sans télécharger la vidéo.
"""

import json
import logging
import os
import re
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Detection des URLs YouTube
_YOUTUBE_RE = re.compile(
    r'(https?://)?(www\.)?'
    r'(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)'
    r'([a-zA-Z0-9_-]{11})'
)

def is_youtube_url(text: str) -> bool:
    """Vérifie si un texte contient une URL YouTube."""
    return bool(_YOUTUBE_RE.search(text))

def extract_video_id(text: str) -> str | None:
    """Extrait l'ID d'une vidéo YouTube depuis n'importe quel format d'URL."""
    m = _YOUTUBE_RE.search(text)
    return m.group(4) if m else None


def _format_duration(seconds: int) -> str:
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m{sec:02d}s"
    return f"{minutes}m{sec:02d}s"


def _format_date(upload_date: str) -> str:
    if len(upload_date) == 8:
        return f"{upload_date[6:8]}/{upload_date[4:6]}/{upload_date[:4]}"
    return upload_date or "Date inconnue"


def _format_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _clean_srt(srt_path: str) -> str:
    """Nettoie un fichier SRT : enlève les numéros, timestamps, lignes vides
    et dédoublonne les lignes consécutives identiques (auto-captions)."""
    if not os.path.exists(srt_path):
        return ""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    # Supprimer les lignes numérotées, timestamps et vides
    lines = []
    for line in content.split("\n"):
        stripped = line.strip()
        if (stripped.isdigit() or
                "-->" in stripped or
                not stripped):
            continue
        lines.append(stripped)
    # Nettoyer les retours chariot
    text = " ".join(lines).replace("\r", "")
    # Dédoublonnage des segments consécutifs identiques
    segments = re.split(r'(?<=[.?!])\s+', text)
    unique = []
    for seg in segments:
        if seg and seg != (unique[-1] if unique else None):
            unique.append(seg)
    return " ".join(unique)


def _get_transcript(url: str) -> str | None:
    """Télécharge les sous-titres automatiques et retourne le texte nettoyé.
    Essaie fr-orig (Français Original), puis fr, puis en (Anglais)."""
    langs = ["fr-orig", "fr", "en"]
    base = ""
    for lang in langs:
        try:
            # yt-dlp -o attend un chemin SANS extension.
            # Il crée le fichier {base}.{lang}.srt (ex: base.fr-orig.srt)
            fd, base = tempfile.mkstemp(suffix=".srt", prefix="yt_transcript_")
            os.close(fd)
            os.unlink(base)  # On garde le chemin mais on supprime le fichier vide
            base = base.replace(".srt", "")

            result = subprocess.run(
                ["yt-dlp", "--write-auto-subs", "--sub-langs", lang,
                 "--skip-download", "--convert-subs", "srt",
                 "-o", base, url],
                capture_output=True, text=True, timeout=30
            )
            actual_path = f"{base}.{lang}.srt"
            if result.returncode == 0 and os.path.exists(actual_path):
                transcript = _clean_srt(actual_path)
                os.unlink(actual_path)
                if transcript.strip():
                    return transcript
        except Exception as e:
            logger.debug(f"[YOUTUBE] Transcript {lang} indisponible: {e}")
        finally:
            # Nettoyage : glob tous les fichiers créés par cette tentative
            import glob as _glob
            for f in _glob.glob(f"{base}.*.srt") if base else []:
                try:
                    if os.path.exists(f):
                        os.unlink(f)
                except OSError:
                    pass
    return None


def tool_youtube_info(url: str, include_transcript: str = "false") -> str:
    """Extrait les métadonnées complètes d'une vidéo YouTube (titre, chaîne,
    durée, description, date, vues) et optionnellement la transcription.

    Utilise yt-dlp sans télécharger la vidéo. La transcription provient des
    sous-titres automatiques YouTube (fr-orig, fr ou en).

    Args:
        url: URL YouTube complète ou ID de vidéo
        include_transcript: "true" pour inclure la transcription, "false" sinon

    Returns:
        Métadonnées formatées + transcription si demandée
    """
    # Normaliser : si c'est juste un ID, construire l'URL
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"

    want_transcript = include_transcript.lower().strip() in ("true", "yes", "1", "oui")

    logger.info(f"[YOUTUBE] Extraction{' + transcript' if want_transcript else ''}: {url}")

    try:
        # yt-dlp --dump-json (ne télécharge rien, juste les métadonnées)
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", url],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()[:500] or "code de retour inconnu"
            logger.warning(f"[YOUTUBE] Échec yt-dlp: {error_msg}")
            return json.dumps({
                "error": f"Impossible de lire la vidéo: {error_msg}"
            })

        data = json.loads(result.stdout.strip())

        # Extraire les champs utiles
        title = data.get("title", "Titre inconnu")
        uploader = data.get("uploader", data.get("channel", "Chaîne inconnue"))
        upload_date = data.get("upload_date", "")
        duration_sec = data.get("duration", 0)
        view_count = data.get("view_count", 0)
        like_count = data.get("like_count", None)
        description = data.get("description", "") or ""

        # Construire la réponse
        parts = []

        # ── Bloc métadonnées ──
        meta = [
            f"🎬 **{title}**",
            f"📺 {uploader}",
            f"⏱️ {_format_duration(duration_sec)} · 👁️ {_format_count(view_count)} vues",
            f"📅 Publiée le {_format_date(upload_date)}",
        ]
        if like_count is not None:
            meta[2] += f" · 👍 {_format_count(like_count)}"
        meta.append("")
        meta.append("📄 **Description :**")
        meta.append(description[:2000] if description else "(aucune description)")
        if description and len(description) > 2000:
            meta[-1] += "\n\n[... description tronquée, suite disponible sur YouTube]"

        parts.append("\n".join(meta))

        # ── Bloc transcription (optionnel) ──
        if want_transcript:
            transcript = _get_transcript(url)
            if transcript:
                # Limiter la transcription à 10 000 caractères max
                transcript_clean = transcript[:10000]
                if len(transcript) > 10000:
                    transcript_clean += "\n\n[... transcription tronquée]"
                parts.append("")
                parts.append("📝 **Transcription :**")
                parts.append(transcript_clean)
            else:
                parts.append("")
                parts.append("📝 *(Transcription non disponible pour cette vidéo)*")

        return "\n".join(parts)

    except subprocess.TimeoutExpired:
        logger.warning(f"[YOUTUBE] Timeout pour {url}")
        return json.dumps({"error": "Timeout lors de la récupération des métadonnées YouTube"})
    except json.JSONDecodeError:
        logger.warning(f"[YOUTUBE] JSON invalide depuis yt-dlp")
        return json.dumps({"error": "Format de réponse invalide de YouTube"})
    except FileNotFoundError:
        logger.error("[YOUTUBE] yt-dlp non trouvé dans le PATH")
        return json.dumps({"error": "yt-dlp n'est pas installé sur le système"})
    except Exception as e:
        logger.error(f"[YOUTUBE] Erreur inattendue: {e}")
        return json.dumps({"error": f"Erreur: {str(e)}"})
