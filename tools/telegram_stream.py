"""tools/telegram_stream.py — Affichage en streaming des réponses Santana sur Telegram.

Pont entre core/react_loop.py (qui pousse du texte token par token via
stream_callback) et l'API Telegram (qui n'autorise qu'un nombre limité
d'éditions de message par seconde). Reconstruit le 04/07/2026 après une
suppression accidentelle (jamais commité en git avant sa perte) — voir
[[santana-known-bugs]].

Convention de préfixes utilisée par react_loop.py :
  - "__MSGTYPE__<TYPE>"  : envoyé une fois avant le premier appel LLM,
    indique le type de message (SOCIAL/FACTUEL/SYNTHESE/DEEP/PERSONNEL).
  - tout le reste : un chunk de texte réel, à accumuler et afficher.
"""

import asyncio
import logging
import re
import time

logger = logging.getLogger(__name__)

_MAX_MSG_LEN = 4096          # limite Telegram par message
_EDIT_MIN_INTERVAL = 0.8     # secondes entre deux editMessageText (flood control)

_MSGTYPE_LABEL = {
    "SOCIAL": "",
    "FACTUEL": "🔎 ",
    "SYNTHESE": "🧩 ",
    "DEEP": "🧠 ",
    "PERSONNEL": "",
}


def _markdown_to_telegram_html(text: str) -> str:
    """Convertit le Markdown que produit Santana (le prompt système lui
    demande **gras**, ## titres, listes, `code`) en HTML Telegram.

    Pourquoi HTML plutôt que MarkdownV2 : Telegram n'exige d'échapper que
    3 caractères (&, <, >) contre une dizaine en MarkdownV2 (_ * [ ] ( ) ~
    ` > # + - = | { } . !) — un seul caractère non échappé dans du texte
    généré par LLM fait échouer l'envoi ENTIER du message en MarkdownV2.
    En HTML, échapper d'abord puis n'introduire que des balises qu'on
    contrôle nous-mêmes élimine ce risque par construction.
    """
    # 1. Échapper les caractères spéciaux HTML AVANT d'introduire nos propres balises
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 2. Titres Markdown (## / ###) en début de ligne -> gras (Telegram HTML n'a pas de <h1>)
    escaped = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", escaped, flags=re.MULTILINE)

    # 3. Gras **texte** -> <b>texte</b> (non-greedy, avant l'italique simple
    #    pour ne pas confondre les deux étoiles d'un ** avec deux * simples)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)

    # 4. Code `texte` -> <code>texte</code>
    escaped = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", escaped)

    # 5. Italique *texte* ou _texte_ restant -> <i>texte</i>
    escaped = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"(?<!_)_([^_\n]+?)_(?!_)", r"<i>\1</i>", escaped)

    return escaped


def _strip_html_tags(text: str) -> str:
    """Repli texte brut : retire les balises et dé-échappe les entités."""
    plain = re.sub(r"</?(?:b|i|code|pre|u|s)>", "", text)
    return plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


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

    def __init__(self, bot, chat_id: int, existing_message=None):
        self.bot = bot
        self.chat_id = chat_id
        self.buffer = ""
        self.msg_type = ""
        self.message_id: int | None = existing_message.message_id if existing_message else None
        self._last_edit_ts = 0.0
        self._edit_lock = asyncio.Lock()
        self._loop = asyncio.get_event_loop()
        self._pending_edit = False
        self._progress_msg = ""
        self._on_first_content = None
        self._has_sent_content = False

    def set_on_first_content(self, callback):
        """Enregistre une coroutine à exécuter dès le premier contenu réel
        (permet à l'appelant d'annuler le typing indicator au bon moment)."""
        self._on_first_content = callback

    # ── Appelé par react_loop(), depuis un thread — jamais de await ici ──
    def callback(self, chunk: str):
        if not chunk:
            return
        if chunk.startswith("__MSGTYPE__"):
            self.msg_type = chunk[len("__MSGTYPE__"):]
            label = _MSGTYPE_LABEL.get(self.msg_type, "")
            if label and not self._has_sent_content:
                self._schedule_edit(label + "…")
            return
        if chunk.startswith("__PROGRESS__"):
            self._progress_msg = chunk[len("__PROGRESS__"):]
            self._schedule_edit(self.buffer)
            return

        # Premier contenu réel → annuler le typing (planifié sur la boucle
        # asyncio de l'appelant, ce callback tourne dans un thread).
        if not self._has_sent_content:
            self._has_sent_content = True
            if self._on_first_content:
                try:
                    asyncio.run_coroutine_threadsafe(self._on_first_content(), self._loop)
                except Exception:
                    pass

        if self._progress_msg:
            self._progress_msg = ""

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
            shown = display_text
            if self._progress_msg:
                shown += "\n\n⏳ " + self._progress_msg
            if len(shown) > _MAX_MSG_LEN:
                # Afficher le DÉBUT (pas la fin) : sur une réponse longue,
                # l'utilisateur doit voir le texte qui s'écrit dans l'ordre.
                remaining = len(shown) - (_MAX_MSG_LEN - 40)
                shown = shown[:_MAX_MSG_LEN - 40] + f"\n\n… *(+{remaining} caractères)*"
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

    async def _send_or_edit(self, index: int, text: str):
        """Envoie/édite UNE partie avec mise en forme HTML, et se replie en
        texte brut (sans balises) si Telegram rejette le HTML (tags mal
        formés que la conversion n'aurait pas dû produire, mais mieux vaut
        livrer un message lisible que ne rien livrer)."""
        html = _markdown_to_telegram_html(text)
        is_first_edit = index == 0 and self.message_id is not None
        try:
            if is_first_edit:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id, message_id=self.message_id,
                    text=html, parse_mode="HTML",
                )
            else:
                msg = await self.bot.send_message(
                    chat_id=self.chat_id, text=html, parse_mode="HTML",
                )
                if index == 0:
                    self.message_id = msg.message_id
            return
        except Exception as e:
            logger.warning("[TG_STREAM] HTML rejeté, repli texte brut (%s)", e)

        plain = _strip_html_tags(html)
        try:
            if is_first_edit:
                await self.bot.edit_message_text(
                    chat_id=self.chat_id, message_id=self.message_id, text=plain,
                )
            else:
                await self.bot.send_message(chat_id=self.chat_id, text=plain)
        except Exception as e2:
            logger.error("[TG_STREAM] Échec envoi (HTML et texte brut): %s", e2)



    async def finalize(self, response: str):
        """Envoie la réponse finale, propre (sans curseur), en la découpant
        si elle dépasse la limite Telegram et en appliquant le formatage
        HTML (jamais pendant le streaming — le texte partiel a des balises
        Markdown non fermées, ce qui casserait le parsing à chaque édition).
        Remplace le brouillon en cours d'édition par le texte définitif."""
        response = response or "…"
        label = _MSGTYPE_LABEL.get(self.msg_type, "")
        if label and not response.startswith(label):
            response = label + response
        # Découper le texte BRUT (pas le HTML) pour que chaque partie garde
        # ses propres balises **/`` équilibrées — pas de <b> ouvert dans une
        # partie et fermé dans la suivante.
        parts = _split_for_telegram(response)
        for i, part in enumerate(parts):
            await self._send_or_edit(i, part)
