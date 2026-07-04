#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Santana — Telegram bot personnel de Serge (Bad Technology Research)."""

import os, json, logging, asyncio, fcntl, signal, sys, time, subprocess
from datetime import datetime
import pytz; _TZ = pytz.timezone("Europe/Brussels")

BASE_DIR = os.path.expanduser('~/santana')
ENV_PATH = os.path.join(BASE_DIR, '.env')

# ── PID LOCK : empêche les doubles processus (Correctif 1) ──
_LOCK_FILE = os.path.join(BASE_DIR, '.santana.lock')
try:
    _lock_fd = open(_LOCK_FILE, 'w')
    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except (IOError, OSError):
    logging.error("[PID LOCK] Un autre processus Santana est déjà en cours. Arrêt.")
    print("[PID LOCK] Conflit de processus détecté. Quitte.", flush=True)
    exit(1)

# ── Rate limiter simple (Correctif 15) ──
_RATE_LIMIT: dict[int, float] = {}
_RATE_WINDOW = 2.0

from core.utils import load_env, TokenFilter
load_env(ENV_PATH)
print(f"[SANTANA BOOT] DEEPSEEK_MODEL='{os.getenv('DEEPSEEK_MODEL', 'NOT_LOADED')}'", flush=True)

DB_PATH = os.path.join(BASE_DIR, 'memory.db')
LOG_PATH = os.path.join(BASE_DIR, 'santana.log')
SOUL_DIR = os.path.join(BASE_DIR, 'soul')

# ── Logging : DÉFINIR AVANT tout import (force=True pour écraser les handlers auto-créés) ──
# NOTE : les imports python-telegram-bot et autres créent parfois des handlers sur le
# root logger AVANT que basicConfig ne soit appelé. force=True résout ce problème
# en remplaçant tous les handlers existants (Python 3.8+).
from logging.handlers import RotatingFileHandler
_log_handler = RotatingFileHandler(LOG_PATH, maxBytes=5*1024*1024, backupCount=5)
_log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
# Ajouter aussi un handler stderr pour que les logs apparaissent dans systemd/journalctl
_log_stderr = logging.StreamHandler()
_log_stderr.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
logging.basicConfig(
    level=logging.INFO,
    handlers=[_log_handler, _log_stderr],
    force=True
)
from core.utils import TokenFilter
logging.getLogger().addFilter(TokenFilter())
logging.getLogger('telegram').setLevel(logging.WARNING)  # Réduire le bruit Telegram
logging.getLogger('httpx').setLevel(logging.WARNING)

# Modules externes
from memory.memory import init_db, rotate_memory, seed_initial_skills
from metrics import init_metrics_db

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

# WhisperModel importé LAZY (dans handle_voice) pour éviter 4s de boot inutiles

# Atlas — mémoire intelligente
_ATLAS_LEARN = None
_ATLAS_ENABLED = True

# ── Handlers Telegram (inline) ───────────────────────────────────────
# Reconstruits le 04/07/2026 : une tentative de split vers un module
# `tg_handlers` (jamais créé, ni jamais committé — voir
# ~/.claude/projects/.../santana_known_bugs.md) avait laissé des imports
# cassés ici, faisant planter santana.py au démarrage (NameError sur
# start_command/handle_message/etc. dès le premier add_handler()). Ces
# fonctions restent inline tant qu'un vrai module tg_handlers n'existe pas.
from telegram import Update
from core.react_loop import react_loop
from tools.cost_governor import get_status as _cost_status, reset as _cost_reset
from agent.context import reset_session as _reset_context_session
from tools.telegram_stream import TelegramStream


async def start_command(update: Update, context):
    await update.message.reply_text(
        "🎸 <b>Santana</b> — Agent personnel de Serge\n\n"
        "✨ Je suis ton assistant IA. Envoie-moi un message, je réponds.\n\n"
        "📋 <b>Commandes disponibles :</b>\n"
        "🔄 /start — Démarrer / menu\n"
        "🧹 /reset — Nettoyer la session\n"
        "📊 /status — Statut système\n"
        "🤝 /help — Aide",
        parse_mode="HTML",
    )


async def status_command(update: Update, context):
    await update.message.reply_text("📊 Statut Santana : ✅ opérationnel")


async def help_command(update: Update, context):
    await update.message.reply_text(
        "🤝 <b>Aide Santana</b>\n\n"
        "💬 Envoie-moi un message texte, je te réponds avec ma boucle ReAct.\n"
        "🔍 Je peux chercher sur le web, exécuter du code, consulter ma mémoire.\n\n"
        "📋 <b>Commandes :</b>\n"
        "🔄 /start — Démarrer\n"
        "🧹 /reset — Nettoyer la session (reset budget + buffer)\n"
        "📊 /status — Voir le statut\n"
        "🤝 /help — Cette aide",
        parse_mode="HTML",
    )


async def reset_command(update: Update, context):
    """Réinitialise le compteur de coût ET le buffer de session."""
    try:
        avant = _cost_status()
        _cost_reset()
        _reset_context_session()
        apres = _cost_status()
        await update.message.reply_text(
            f"🧹 <b>Session nettoyée</b> ✅\n\n"
            f"💰 Budget : <code>${apres['budget']:.4f}</code>\n"
            f"📉 Utilisé : <code>${apres['cout_cumule']:.4f}</code>\n"
            f"🚦 Niveau : <code>{apres['niveau']}</code>\n"
            f"⚡ Appels LLM : <code>{apres['appels']}</code>\n\n"
            f"✅ Tu peux maintenant reparler, le compteur est reparti à zéro.",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"[RESET] Erreur: {e}")
        await update.message.reply_text(f"❌ Erreur reset : {str(e)[:200]}")


async def handle_message(update: Update, context):
    user_msg = update.message.text
    chat_id = update.effective_chat.id
    if chat_id != CHAT_ID:
        await update.message.reply_text("❌ Non autorisé")
        return
    try:
        stream = TelegramStream(context.bot, chat_id)
        response = await react_loop(user_msg, stream_callback=stream.callback)
        await stream.finalize(response)
    except Exception as e:
        logging.error(f"[HANDLER] handle_message error: {e}")
        try:
            await update.message.reply_text(f"❌ Erreur: {str(e)[:200]}")
        except Exception:
            pass


async def handle_voice(update: Update, context):
    await update.message.reply_text("🎤 Fichier audio non supporté pour le moment")


async def handle_photo(update: Update, context):
    await update.message.reply_text("🖼️ Photo non supportée pour le moment")


async def handle_video(update: Update, context):
    await update.message.reply_text("🎬 Vidéo non supportée pour le moment")


async def handle_document(update: Update, context):
    await update.message.reply_text("📄 Document non supporté pour le moment")


async def handle_webapp_data(update: Update, context):
    logging.info("[WEBAPP] Données webapp reçues (non traitées)")


async def handle_callback_query(update: Update, context):
    await update.callback_query.answer("Fonction non disponible")


os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(SOUL_DIR, exist_ok=True)


TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
DISPLAY_MODEL = os.getenv('DEEPSEEK_MODEL', 'deepseek-v4-flash').strip()
CHAT_ID = int(os.getenv('CHAT_ID', '0').strip())


# ─── STARTUP ────────────────────────────────────────────────────────────

# ── Mode dégradé : vérifier le fichier crash flag (Correctif 2) ──
_CRASH_FLAG = os.path.join(BASE_DIR, '.crash_flag')
_DEGRADED_MODE = False
if os.path.exists(_CRASH_FLAG):
    try:
        with open(_CRASH_FLAG) as f:
            _cf = json.load(f)
        _DEGRADED_MODE = True
        _crash_count = _cf.get('count', 1)
        _crash_time = _cf.get('time', 'inconnu')
        logging.warning(f"[SANTANA] Mode DÉGRADÉ activé ({_crash_count} crashs)")

        # Envoyer une alerte Telegram (N4 — Alerte crash)
        try:
            _alert_text = f"⚠️ *Santana — Alerte Crash*\n\nSantana a redémarré après {_crash_count} crash(s).\nDernier crash : {_crash_time}\nMode dégradé activé.\n\nVérifie les logs : `tail -50 santana.log`"
            import urllib.request
            _data = json.dumps({
                "chat_id": CHAT_ID,
                "text": _alert_text,
                "parse_mode": "Markdown"
            }).encode()
            _req = urllib.request.Request(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                data=_data,
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(_req, timeout=10)
            logging.info("[SANTANA] Alerte crash envoyée par Telegram")
        except Exception as _ae:
            logging.warning(f"[SANTANA] Échec alerte crash Telegram: {_ae}")

        _ATLAS_ENABLED = False
    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"[HERMES] Crash flag read error: {e}")

if _DEGRADED_MODE:
    logging.warning("[SANTANA] Mode dégradé : mémoire vivante désactivée, Atlas désactivé, outils limités")

if __name__ == '__main__':
    init_db()
    seed_initial_skills()
    rotate_memory(500)
    init_metrics_db()

    # Backup automatique des bases au démarrage
    try:
        subprocess.run(
            ['bash', 'scripts/backup_db.sh'],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=30
        )
        logging.info('[SANTANA] Backup DB effectué au démarrage')
    except Exception as _be:
        logging.warning(f'[SANTANA] Backup DB au démarrage échoué: {_be}')

    # ── Start-up healthcheck (Phase 1 — P1) ──
    try:
        _hc = subprocess.run(
            ['bash', 'scripts/santana-doctor.sh'],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=15
        )
        _hc_lines = [l for l in _hc.stdout.split('\n') if '❌' in l or '✅' in l]
        for _l in _hc_lines[:5]:
            logging.info(f'[DOCTOR] {_l.strip()}')
        if '❌' in _hc.stdout:
            logging.warning('[DOCTOR] Certains checks ont échoué au démarrage')
            logging.warning(f'[DOCTOR] Dernières lignes: {_hc.stdout.strip()[-300:]}')
        else:
            logging.info('[DOCTOR] Tous les checks OK')
    except Exception as _he:
        logging.warning(f'[DOCTOR] Healthcheck non disponible: {_he}')

    # Rotation mensuelle automatique
    try:
        from atlas_engine.rotate import rotate_all
        rotate_all()
        logging.info('[SANTANA] Rotation mensuelle effectuée')
    except Exception as e:
        logging.warning(f'[SANTANA] Rotation mensuelle: {e}')

    # ── Watchdog + Guardian (autonomie réelle, voir tools/guardian.py) ──
    from tools.guardian import start_guardian, start_watchdog

    _background_tasks = []

    async def _watchdog_ping():
        while True:
            try:
                if _WD_CTX is not None:
                    _WD_CTX(0, b"WATCHDOG=1\n")
            except Exception:
                logging.error("[SANTANA] watchdog ping échec")
            await asyncio.sleep(30)

    async def _warmup_embeddings():
        """Précharge le modèle d'embeddings (sentence-transformers) en tâche de
        fond au démarrage. Sans ça, le PREMIER message PERSONNEL de Serge après
        un redémarrage du service subit le chargement complet du modèle
        (~12s mesurés) avant même l'appel LLM — voir tests/test_100_performances.py."""
        try:
            t0 = time.time()
            from atlas_engine.embeddings import _get_model
            await asyncio.to_thread(_get_model)
            logging.info(f"[SANTANA] Modèle d'embeddings préchargé en {time.time()-t0:.1f}s")
        except Exception as e:
            logging.warning(f"[SANTANA] Préchauffage embeddings échoué (lazy-load au premier usage): {e}")

    async def _post_init(app):
        # Attendre que Telegram libère l'ancienne session (évite Conflict)
        import asyncio as _asyncio
        await _asyncio.sleep(2)
        # Menu de commandes Telegram (≡ hamburger)
        # NOTE : brainstorm/brainstorm_stop/atlas/memo retirés du menu le
        # 04/07/2026 — référencés dans une tentative de split vers un module
        # tg_handlers jamais créé ; aucune implémentation n'existe pour ces
        # commandes. À ajouter au menu quand (et si) elles seront codées.
        await app.bot.set_my_commands([
            ('start', '🔄 Démarrer la session'),
            ('status', '📊 Statut système'),
            ('reset', '🗑️ Réinitialiser la session'),
            ('help', '🤝 Aide'),
        ])
        _background_tasks.append(asyncio.create_task(_watchdog_ping()))
        _background_tasks.append(asyncio.create_task(_warmup_embeddings()))
        _background_tasks.append(asyncio.create_task(start_watchdog(_WD_CTX)))
        _background_tasks.append(asyncio.create_task(start_guardian()))

    async def _post_stop(app):
        for task in _background_tasks:
            task.cancel()
        await asyncio.gather(*_background_tasks, return_exceptions=True)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(_post_init).post_stop(_post_stop).build()
    for cmd, handler in [
        ('start', start_command), ('status', status_command), ('statut', status_command),
        ('reset', reset_command),
        ('help', help_command),
    ]:
        app.add_handler(CommandHandler(cmd, handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # ── Watchdog systemd (sd_notify via ctypes — PID correct garantit) ──
    _WD_CTX = None  # (lib, sd_notify) ou None si pas de systemd
    _WD_PATH = os.environ.get("NOTIFY_SOCKET")
    if _WD_PATH:
        import ctypes, ctypes.util
        _lib = ctypes.util.find_library('systemd')
        if _lib:
            _sd_notify = ctypes.CDLL(_lib).sd_notify
            _sd_notify.restype = ctypes.c_int
            _sd_notify.argtypes = [ctypes.c_int, ctypes.c_char_p]
            _WD_CTX = _sd_notify
            # READY=1 immédiat pour dire à systemd qu'on est vivant
            if _sd_notify(0, b"READY=1\n") > 0:
                logging.info("[SANTANA] sd_notify READY=1 envoyé")
            else:
                logging.warning("[SANTANA] sd_notify READY=1 échec")
        else:
            logging.warning("[SANTANA] libsystemd introuvable, watchdog désactivé")

    # Watchdog + Guardian: extraits dans tools/guardian.py

    # ── Enregistrer le handler de crash flag ──
    _CRASH_COUNT = 0

    def _write_crash_flag():
        """Écrit le fichier .crash_flag avec le nombre de crashs."""
        try:
            _cf = {"count": _CRASH_COUNT + 1, "time": datetime.now(_TZ).isoformat()}
            with open(_CRASH_FLAG, 'w') as f:
                json.dump(_cf, f)
            logging.info(f"[SANTANA] Crash flag written (count={_CRASH_COUNT + 1})")
        except Exception as _cfe:
            logging.error(f"[SANTANA] Échec écriture crash flag: {_cfe}")

    def _signal_handler(signum, frame):
        """Handler pour SIGTERM/SIGINT — exit propre SANS crash flag.
        Le crash flag n'est écrit QUE sur SIGABRT/SIGSEGV (vrai crash).
        """
        if signum in (signal.SIGABRT, signal.SIGSEGV):
            _write_crash_flag()
            logging.warning(f"[SANTANA] Crash signal {signum} reçu — flag écrit")
        else:
            logging.warning(f"[SANTANA] Signal {signum} reçu — arrêt propre, pas de crash flag")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logging.info('Santana Agent démarré')
    try:
        app.run_polling(drop_pending_updates=True, bootstrap_retries=5, close_loop=False)
    except Exception as _run_e:
        logging.error(f"[SANTANA] Crash dans run_polling: {_run_e}")
        _write_crash_flag()
        raise
