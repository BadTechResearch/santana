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

_MSGTYPE_FOOTER = {
    "SYNTHESE": "\n━━━━━━━━━━━━━━━━━━\n📌 *Synthèse BTR*",
    "DEEP": "\n━━━━━━━━━━━━━━━━━━\n🎸 *Santana — Analyse*",
}


def _markdown_to_telegram_html(text: str) -> str:
    """Convertit le Markdown que produit Santana en HTML Telegram.

    Support complet : titres, **gras**, *italique*, `code`, ```code blocks```,
    [liens](url), listes - et 1., blockquotes >, ~~barré~~, ||spoiler||,
    séparateurs ---.

    Pourquoi HTML plutôt que MarkdownV2 : Telegram n'exige d'échapper que
    3 caractères (&, <, >) contre une dizaine en MarkdownV2 (_ * [ ] ( ) ~
    ` > # + - = | { } . !) — un seul caractère non échappé dans du texte
    généré par LLM fait échouer l'envoi ENTIER du message en MarkdownV2.
    En HTML, échapper d'abord puis n'introduire que des balises qu'on
    contrôle nous-mêmes élimine ce risque par construction.
    """
    # 0. Sauvegarder les blocs de code fencés AVANT tout échappement
    code_blocks = []

    def _save_code(m):
        code_blocks.append(m.group(2))
        return f"\x00CODEBLOCK_{len(code_blocks) - 1}\x00"

    text = re.sub(
        r'```(\w*)\n(.*?)```(?!`)',
        _save_code, text, flags=re.DOTALL,
    )

    # 1. Échapper & (toujours dangereux) MAIS PAS < ni > pour l'instant
    #    (< et > sont échappés APRÈS les regex qui en ont besoin, comme > pour blockquotes)
    escaped = text.replace("&", "&amp;")

    # 2. Blockquotes (doivent être AVANT l'échappement de < et >)
    #    On utilise des placeholders pour protéger les tags <i> qu'on génère.
    escaped = re.sub(r"^>\s+(.+)$", lambda m: f"\x00BQ\x00▎ {m.group(1)}\x00/BQ\x00", escaped, flags=re.MULTILINE)

    # 3. Échapper < et > restants (ceux qui n'ont pas été consommés par les regex ci-dessus)
    escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")

    # Restaurer les tags blockquote
    escaped = escaped.replace("\x00BQ\x00", "<i>").replace("\x00/BQ\x00", "</i>")

    # 4. Titres Markdown (## / ###) en début de ligne -> gras
    escaped = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", escaped, flags=re.MULTILINE)

    # 5. Gras **texte** -> <b>texte</b>
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)

    # 6. Code inline `texte` -> <code>texte</code>
    escaped = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", escaped)

    # 7. Italique *texte* ou _texte_ -> <i>texte</i>
    escaped = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", escaped)
    escaped = re.sub(r"(?<!_)_([^_\n]+?)_(?!_)", r"<i>\1</i>", escaped)

    # 8. Liens [texte](url) -> <a href="url">texte</a>
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)

    # 9. Listes non ordonnées en début de ligne -> bullet unicode
    escaped = re.sub(r"^[\-\*\+]\s+(.+)$", lambda m: f"• {m.group(1)}", escaped, flags=re.MULTILINE)

    # 10. Barré ~~texte~~ -> <s>texte</s>
    escaped = re.sub(r"~~(.+?)~~", r"<s>\1</s>", escaped)

    # 11. Spoiler ||texte|| -> <tg-spoiler>texte</tg-spoiler>
    escaped = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", escaped)

    # 12. Séparateurs --- / *** / ___ -> ligne décorative
    escaped = re.sub(r"^[-_*]{3,}\s*$", "\n━━━━━━━━━━━━━━━━━━\n", escaped, flags=re.MULTILINE)

    # 13. Restaurer les blocs de code fencés
    for i, code in enumerate(code_blocks):
        placeholder = f"\x00CODEBLOCK_{i}\x00"
        # Échapper le HTML dans le code pour affichage littéral
        safe = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        escaped = escaped.replace(placeholder, f"<pre>{safe}</pre>")

    return escaped


def _strip_html_tags(text: str) -> str:
    """Repli texte brut : retire les balises et dé-échappe les entités."""
    plain = re.sub(r"</?(?:b|i|code|pre|u|s)>", "", text)
    return plain.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _find_safe_cut(text: str, limit: int) -> int:
    """Trouve une coupure qui ne brise pas la structure HTML."""
    # Ne pas couper dans <pre>...</pre> ou <code>...</code>
    for tag, end_tag in [('<pre>', '</pre>'), ('<code>', '</code>')]:
        last_open = text.rfind(tag, 0, limit)
        if last_open > 0:
            last_close = text.rfind(end_tag, last_open, limit)
            if last_close < last_open:
                # On est dans un bloc ouvert → couper APRÈS la fermeture
                next_close = text.find(end_tag, limit)
                if next_close > 0:
                    return next_close + len(end_tag)
    # Priorité: saut de paragraphe → saut de ligne → ponctuation → caractère
    for sep in ['\n\n', '\n', '. ', ' ']:
        cut = text.rfind(sep, 0, limit)
        if cut > 0:
            return cut
    return limit


def _split_for_telegram(text: str, limit: int = _MAX_MSG_LEN) -> list[str]:
    """Découpe un texte trop long en plusieurs messages, en protégeant
    la structure HTML (ne pas couper dans <pre>, <code>)."""
    if len(text) <= limit:
        return [text]
    parts = []
    remaining = text
    while len(remaining) > limit:
        safe_cut = _find_safe_cut(remaining, limit)
        parts.append(remaining[:safe_cut].rstrip())
        remaining = remaining[safe_cut:].lstrip()
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
        self._show_cursor = True

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
        self._show_cursor = True  # nouveau contenu → réafficher le curseur
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
            # Curseur clignotant : présent pendant le streaming, retiré
            # pendant l'attente d'un outil (buffer stable).
            if self._show_cursor:
                cursor = shown + " ▌"
                self._show_cursor = False  # une fois affiché, attente prochain chunk
            else:
                cursor = shown
            # Conversion en HTML pendant le stream : les tag non-fermés sont
            # ignorés par les regex non-greedy, Telegram tolère le HTML partiel.
            html = _markdown_to_telegram_html(cursor)
            try:
                if self.message_id is None:
                    msg = await self.bot.send_message(
                        chat_id=self.chat_id, text=html, parse_mode="HTML",
                    )
                    self.message_id = msg.message_id
                else:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id, message_id=self.message_id,
                        text=html, parse_mode="HTML",
                    )
                self._last_edit_ts = time.time()
            except Exception as e:
                # "Message is not modified" et les 429 ponctuels ne sont pas fatals —
                # le prochain chunk ou finalize() rattrapera l'affichage.
                # Si le HTML a échoué (tags mal formés), retenter en texte brut.
                if "can't parse entities" in str(e).lower() or "bad request" in str(e).lower():
                    try:
                        plain = _strip_html_tags(html)
                        if self.message_id is None:
                            msg = await self.bot.send_message(
                                chat_id=self.chat_id, text=plain,
                            )
                            self.message_id = msg.message_id
                        else:
                            await self.bot.edit_message_text(
                                chat_id=self.chat_id, message_id=self.message_id, text=plain,
                            )
                    except Exception:
                        logger.debug("[TG_STREAM] Repli texte brut échoué aussi")
                else:
                    logger.debug("[TG_STREAM] Édition ignorée: %s", e)

    async def _send_or_edit(self, index: int, text: str, is_last: bool = False):
        """Envoie/édite UNE partie avec mise en forme HTML, et se replie en
        texte brut (sans balises) si Telegram rejette le HTML. Ajoute un
        footer de type pour la dernière partie."""
        # Ajouter le footer pour la dernière partie
        if is_last:
            footer = _MSGTYPE_FOOTER.get(self.msg_type, "")
            if footer:
                text += footer
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
        HTML. Ajoute pagination et connecteurs pour les réponses longues.
        Remplace le brouillon en cours d'édition par le texte définitif."""
        response = response or "…"
        label = _MSGTYPE_LABEL.get(self.msg_type, "")
        if label and not response.startswith(label):
            response = label + response
        # Découper le texte BRUT (pas le HTML) pour que chaque partie garde
        # ses propres balises **/`` équilibrées — pas de <b> ouvert dans une
        # partie et fermé dans la suivante.
        parts = _split_for_telegram(response)
        total = len(parts)
        for i, part in enumerate(parts):
            if total > 1 and i > 0:
                part = f"📎 *Suite (partie {i + 1}/{total})*\n\n{part}"
            is_last = (i == total - 1)
            await self._send_or_edit(i, part, is_last=is_last)
