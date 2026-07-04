"""tools/telegram_stream.py — Affichage en streaming des réponses Santana sur Telegram.

Pont entre core/react_loop.py (qui pousse du texte token par token via
stream_callback) et l'API Telegram (qui n'autorise qu'un nombre limité
d'éditions de message par seconde). Reconstruit le 04/07/2026 après une
suppression accidentelle (jamais commité en git avant sa perte) — voir
[[santana-known-bugs]].

Convention de préfixes utilisée par react_loop.py :
  - "__MSGTYPE__<TYPE>"  : envoyé une fois avant le premier appel LLM,
    indique le type de message (SOCIAL/FACTUEL/SYNTHESE/DEEP/PERSONNEL).
  - "__PROGRESS__<texte>" : heartbeat pendant l'exécution d'un outil
    (toutes les ~2s) — à afficher sans l'accumuler dans le texte final.
  - tout le reste : un chunk de texte réel, à accumuler et afficher.
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_MAX_MSG_LEN = 4096          # limite Telegram par message
_EDIT_MIN_INTERVAL = 1.2     # secondes entre deux editMessageText (flood control)

_MSGTYPE_LABEL = {
    "SOCIAL": "",
    "FACTUEL": "🔎 ",
    "SYNTHESE": "🧩 ",
    "DEEP": "🧠 ",
    "PERSONNEL": "",
}


def _split_for_telegram(text: str, limit: int = _MAX_MSG_LEN) -> list[str]:
    """Découpe un texte trop long en plusieurs messages, de préférence sur
    un saut de paragraphe pour ne pas couper une phrase en deux."""
    if len(text) <= limit:
        return [text]
    parts = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


class TelegramStream:
    """Gère l'affichage progressif d'une réponse Santana dans un chat Telegram.

    Usage (voir santana.py::handle_message) :
        stream = TelegramStream(context.bot, chat_id)
        response = await react_loop(user_msg, stream_callback=stream.callback)
        await stream.finalize(response)

    stream.callback() est appelé de façon SYNCHRONE par react_loop() (il tourne
    dans un thread via asyncio.to_thread) — il ne peut donc pas directement
    `await` un appel Telegram. Il planifie l'édition sur la boucle asyncio de
    handle_message via run_coroutine_threadsafe et laisse l'édition suivre
    sans bloquer le thread de streaming.
    """

    def __init__(self, bot, chat_id: int):
        self.bot = bot
        self.chat_id = chat_id
        self.buffer = ""
        self.msg_type = ""
        self.message_id: int | None = None
        self._last_edit_ts = 0.0
        self._edit_lock = asyncio.Lock()
        self._loop = asyncio.get_event_loop()
        self._pending_edit = False

    # ── Appelé par react_loop(), depuis un thread — jamais de await ici ──
    def callback(self, chunk: str):
        if not chunk:
            return
        if chunk.startswith("__MSGTYPE__"):
            self.msg_type = chunk[len("__MSGTYPE__"):]
            return
        if chunk.startswith("__PROGRESS__"):
            progress_text = chunk[len("__PROGRESS__"):]
            self._schedule_edit(self.buffer + "\n\n" + progress_text if self.buffer else progress_text)
            return
        self.buffer += chunk
        self._schedule_edit(self.buffer)

    def _schedule_edit(self, display_text: str):
        """Planifie une édition sans bloquer le thread appelant (fire-and-forget,
        avec un throttle appliqué côté coroutine, pas ici)."""
        try:
            asyncio.run_coroutine_threadsafe(self._maybe_edit(display_text), self._loop)
        except Exception as e:
            logger.debug("[TG_STREAM] Échec planification édition: %s", e)

    async def _maybe_edit(self, display_text: str):
        """Édite le message Telegram, au plus une fois par _EDIT_MIN_INTERVAL —
        Telegram limite le flood d'éditions (erreur 429 sinon)."""
        now = time.time()
        if now - self._last_edit_ts < _EDIT_MIN_INTERVAL:
            return
        if self._edit_lock.locked():
            return  # une édition est déjà en vol, ne pas empiler
        async with self._edit_lock:
            shown = display_text[-_MAX_MSG_LEN:]
            if not shown.strip():
                return
            cursor = shown + " ▌"
            try:
                if self.message_id is None:
                    msg = await self.bot.send_message(chat_id=self.chat_id, text=cursor)
                    self.message_id = msg.message_id
                else:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id, message_id=self.message_id, text=cursor
                    )
                self._last_edit_ts = time.time()
            except Exception as e:
                # "Message is not modified" et les 429 ponctuels ne sont pas fatals —
                # le prochain chunk ou finalize() rattrapera l'affichage.
                logger.debug("[TG_STREAM] Édition ignorée: %s", e)

    async def finalize(self, response: str):
        """Envoie la réponse finale, propre (sans curseur), en la découpant
        si elle dépasse la limite Telegram. Remplace le brouillon en cours
        d'édition par le texte définitif."""
        response = response or "…"
        parts = _split_for_telegram(response)

        try:
            if self.message_id is not None:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id, message_id=self.message_id, text=parts[0]
                )
            else:
                await self.bot.send_message(chat_id=self.chat_id, text=parts[0])
        except Exception as e:
            logger.warning("[TG_STREAM] Échec édition finale, envoi en nouveau message: %s", e)
            try:
                await self.bot.send_message(chat_id=self.chat_id, text=parts[0])
            except Exception as e2:
                logger.error("[TG_STREAM] Échec envoi final: %s", e2)

        for part in parts[1:]:
            try:
                await self.bot.send_message(chat_id=self.chat_id, text=part)
            except Exception as e:
                logger.error("[TG_STREAM] Échec envoi partie supplémentaire: %s", e)
