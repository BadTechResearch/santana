"""Outil YouTube — métadonnées, transcription sous-titres ET audio→Whisper.
Permet à Santana de lire, transcrire et analyser des vidéos YouTube.
Double pipeline : sous-titres YouTube natifs (rapide) + audio→Whisper (fallback complet).
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import glob as _glob
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Détection des URLs YouTube ─────────────────────────────────────────
_YOUTUBE_RE = re.compile(
    r'(https?://)?(www\.)?'
    r'(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)'
    r'([a-zA-Z0-9_-]{11})'
)

# Chemin vers yt-dlp dans le venv Santana
_VENV_BIN = Path(__file__).resolve().parent.parent / "venv_new" / "bin"
_YTDLP = str(_VENV_BIN / "yt-dlp")

# Cache Whisper
_WHISPER_CACHE = os.path.expanduser("~/.cache/whisper")
_WHISPER_MODEL = "base"
_WHISPER_MAX_CHARS = 15000

# ── Helpers ────────────────────────────────────────────────────────────

def is_youtube_url(text: str) -> bool:
    return bool(_YOUTUBE_RE.search(text))

def extract_video_id(text: str) -> str | None:
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
    """Nettoie un fichier SRT : enlève numéros, timestamps, lignes vides.
    Dédoublonne les segments consécutifs identiques (auto-captions YouTube)."""
    if not os.path.exists(srt_path):
        return ""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
    lines = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.isdigit() or "-->" in stripped or not stripped:
            continue
        lines.append(stripped)
    text = " ".join(lines).replace("\r", "")
    segments = re.split(r'(?<=[.?!])\s+', text)
    unique = []
    for seg in segments:
        if seg and seg != (unique[-1] if unique else None):
            unique.append(seg)
    return " ".join(unique)


# ── Pipeline 1 : Sous-titres YouTube natifs ──────────────────────────

def _get_subtitles(url: str) -> str | None:
    """Télécharge les sous-titres automatiques YouTube (fr-orig → fr → en)."""
    langs = ["fr-orig", "fr", "en"]
    base = ""
    for lang in langs:
        try:
            fd, base = tempfile.mkstemp(suffix=".srt", prefix="yt_sub_")
            os.close(fd)
            os.unlink(base)
            base = base.replace(".srt", "")

            result = subprocess.run(
                [_YTDLP, "--write-auto-subs", "--sub-langs", lang,
                 "--skip-download", "--convert-subs", "srt",
                 "-o", base, url],
                capture_output=True, text=True, timeout=60
            )
            actual_path = f"{base}.{lang}.srt"
            if result.returncode == 0 and os.path.exists(actual_path):
                transcript = _clean_srt(actual_path)
                os.unlink(actual_path)
                if transcript.strip():
                    logger.info(f"[YOUTUBE] Sous-titres trouvés: {lang}")
                    return transcript
        except Exception as e:
            logger.debug(f"[YOUTUBE] Sous-titres {lang} indisponible: {e}")
        finally:
            for f in _glob.glob(f"{base}.*.srt") if base else []:
                try:
                    if os.path.exists(f):
                        os.unlink(f)
                except OSError:
                    pass
    return None


# ── Pipeline 2 : Audio → Whisper ──────────────────────────────────────

def _get_whisper_transcript(url: str) -> str | None:
    """Télécharge l'audio et le transcrit via faster-whisper.
    Modèle 'base' (138 Mo) — bon équilibre vitesse/précision sur CPU."""
    audio_path = None
    audio_base = None
    try:
        # Télécharger l'audio en MP3
        fd, audio_path = tempfile.mkstemp(suffix=".mp3", prefix="yt_audio_")
        os.close(fd)
        if os.path.exists(audio_path):
            os.unlink(audio_path)
        # yt-dlp ajoute l'extension .mp3
        audio_base = audio_path.replace(".mp3", "")

        logger.info("[YOUTUBE] Téléchargement audio pour Whisper...")
        result = subprocess.run(
            [_YTDLP, "--extract-audio", "--audio-format", "mp3",
             "--audio-quality", "5",  # 0=meilleur, 9=pire, 5=bon équilibre
             "-o", audio_base, url],
            capture_output=True, text=True, timeout=300
        )

        actual_audio = f"{audio_base}.mp3"
        if result.returncode != 0 or not os.path.exists(actual_audio):
            logger.warning(f"[YOUTUBE] Échec téléchargement audio: {result.stderr[:300]}")
            return None

        audio_size = os.path.getsize(actual_audio)
        logger.info(f"[YOUTUBE] Audio téléchargé ({audio_size // 1024} Ko), transcription Whisper...")

        # Transcription via faster-whisper
        from faster_whisper import WhisperModel

        model = WhisperModel(
            _WHISPER_MODEL, device="cpu", compute_type="int8",
            download_root=_WHISPER_CACHE
        )

        start = time.time()
        segments, info = model.transcribe(actual_audio, beam_size=5)
        segments_list = list(segments)  # matérialiser
        elapsed = time.time() - start

        language = info.language
        duration = info.duration
        logger.info(f"[YOUTUBE] Whisper: {len(segments_list)} segments, "
                     f"langue={language}, durée={duration:.0f}s, temps={elapsed:.1f}s")

        # Assembler le texte
        text_parts = []
        for seg in segments_list:
            text_parts.append(seg.text.strip())
        transcript = " ".join(text_parts)

        if transcript.strip():
            # Préfixer avec la mention du moteur
            header = f"[Transcription Whisper — {language}, ~{duration:.0f}s traités en {elapsed:.0f}s]"
            return f"{header}\n\n{transcript}"

        return None

    except ImportError:
        logger.error("[YOUTUBE] faster-whisper non installé")
        return None
    except Exception as e:
        logger.error(f"[YOUTUBE] Erreur Whisper: {e}")
        return None
    finally:
        # Nettoyage des fichiers audio temporaires
        base_for_cleanup = audio_base if audio_path else None
        if base_for_cleanup:
            for f in _glob.glob(f"{base_for_cleanup}.*"):
                try:
                    if os.path.exists(f):
                        os.unlink(f)
                except OSError:
                    pass


def _truncate(text: str, max_chars: int) -> str:
    """Tronque un texte avec indication."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... transcription tronquée]"


# ── Outil principal ──────────────────────────────────────────────────

def tool_youtube_info(url: str, include_transcript: str = "false",
                       mode: str = "auto") -> str:
    """Extrait les métadonnées complètes d'une vidéo YouTube et sa transcription.

    Double pipeline de transcription :
      - mode="subtitles" : sous-titres YouTube natifs (fr-orig → fr → en)
      - mode="whisper"   : audio→Whisper (modèle base, CPU)
      - mode="auto"      : sous-titres d'abord, fallback Whisper

    Args:
        url: URL YouTube complète ou ID de vidéo
        include_transcript: "true" pour inclure la transcription
        mode: "auto" | "subtitles" | "whisper"

    Returns:
        Métadonnées formatées + transcription si demandée
    """
    # Normaliser
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={url}"

    want_transcript = include_transcript.lower().strip() in ("true", "yes", "1", "oui")
    trans_mode = mode.lower().strip()

    logger.info(f"[YOUTUBE] tool_youtube_info mode={mode} transcript={include_transcript}: {url}")

    try:
        # ── Métadonnées ──
        result = subprocess.run(
            [_YTDLP, "--dump-json", "--no-download", url],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()[:500] or "code de retour inconnu"
            logger.warning(f"[YOUTUBE] Échec yt-dlp: {error_msg}")
            return json.dumps({"error": f"Impossible de lire la vidéo: {error_msg}"})

        data = json.loads(result.stdout.strip())

        title = data.get("title", "Titre inconnu")
        uploader = data.get("uploader", data.get("channel", "Chaîne inconnue"))
        upload_date = data.get("upload_date", "")
        duration_sec = data.get("duration", 0)
        view_count = data.get("view_count", 0)
        like_count = data.get("like_count", None)
        description = data.get("description", "") or ""

        # ── Construction réponse ──
        parts = []

        # Métadonnées
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

        # ── Transcription ──
        if want_transcript:
            transcript = None
            source = None

            if trans_mode == "auto":
                # Essai 1 : sous-titres YouTube
                transcript = _get_subtitles(url)
                if transcript:
                    source = "sous-titres YouTube"
                else:
                    # Essai 2 : Whisper
                    logger.info("[YOUTUBE] Pas de sous-titres, fallback Whisper...")
                    transcript = _get_whisper_transcript(url)
                    if transcript:
                        source = "Whisper (audio→texte)"

            elif trans_mode == "subtitles":
                transcript = _get_subtitles(url)
                if transcript:
                    source = "sous-titres YouTube"

            elif trans_mode == "whisper":
                transcript = _get_whisper_transcript(url)
                if transcript:
                    source = "Whisper (audio→texte)"

            if transcript and source:
                parts.append("")
                parts.append(f"📝 **Transcription ({source}) :**")
                parts.append(_truncate(transcript, _WHISPER_MAX_CHARS))
            else:
                parts.append("")
                parts.append("📝 *(Transcription non disponible — la vidéo n'a ni sous-titres ni audio extractible)*")

        return "\n".join(parts)

    except subprocess.TimeoutExpired:
        logger.warning(f"[YOUTUBE] Timeout pour {url}")
        return json.dumps({"error": "Timeout lors de la récupération des métadonnées"})
    except json.JSONDecodeError:
        logger.warning(f"[YOUTUBE] JSON invalide depuis yt-dlp")
        return json.dumps({"error": "Format de réponse invalide de YouTube"})
    except FileNotFoundError:
        logger.error(f"[YOUTUBE] yt-dlp non trouvé: {_YTDLP}")
        return json.dumps({"error": "yt-dlp n'est pas installé dans le venv Santana"})
    except Exception as e:
        logger.error(f"[YOUTUBE] Erreur inattendue: {e}")
        return json.dumps({"error": f"Erreur: {str(e)}"})
