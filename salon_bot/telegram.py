"""Telegram transport: only this module depends on python-telegram-bot."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from .service import SalonService

log = logging.getLogger(__name__)


class TelegramBot:
    MENU_MESSAGE_ID = "menu_message_id"
    INPUT_MODE = "input_mode"

    def __init__(self, token: str, service: SalonService):
        self.service = service
        self.app = Application.builder().token(token).build()
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("salon", self.change_salon))
        self.app.add_handler(CallbackQueryHandler(
            self.callback,
            pattern=r"^(district|search|pick|menu):",
        ))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))

    @staticmethod
    def _keyboard(reply):
        if reply.buttons:
            return InlineKeyboardMarkup([
                [InlineKeyboardButton(label, callback_data=code)]
                for label, code in reply.buttons
            ])
        return None

    @staticmethod
    async def _safe_delete(bot, chat_id: int, message_id: int | None):
        if message_id is None:
            return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramError:
            # Сообщение могло быть уже удалено или оказаться старше лимита Telegram.
            log.debug("Не удалось удалить сообщение %s", message_id, exc_info=True)

    async def _send_new(self, context, chat_id: int, reply):
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=reply.text[:4000],
            reply_markup=self._keyboard(reply),
        )
        context.user_data[self.MENU_MESSAGE_ID] = sent.message_id

    async def _delete_current_menu(self, context, chat_id: int):
        message_id = context.user_data.pop(self.MENU_MESSAGE_ID, None)
        await self._safe_delete(context.bot, chat_id, message_id)

    async def _replace_menu(self, context, chat_id: int, reply, source_message=None):
        """Edit the current menu card and only send a new one as a fallback."""
        message_id = source_message.message_id if source_message else context.user_data.get(
            self.MENU_MESSAGE_ID
        )
        if message_id is not None:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=reply.text[:4000],
                    reply_markup=self._keyboard(reply),
                )
                context.user_data[self.MENU_MESSAGE_ID] = message_id
                return
            except BadRequest as error:
                if "message is not modified" in str(error).lower():
                    context.user_data[self.MENU_MESSAGE_ID] = message_id
                    return
                log.debug("Не удалось обновить меню %s", message_id, exc_info=True)
            except TelegramError:
                log.debug("Не удалось обновить меню %s", message_id, exc_info=True)
        await self._send_new(context, chat_id, reply)

    async def start(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        chat_id = update.effective_chat.id
        code = context.args[0] if context.args else ""
        reply = self.service.start(update.effective_user.id, chat_id, code)
        context.user_data.pop(self.INPUT_MODE, None)
        await self._delete_current_menu(context, chat_id)
        await self._safe_delete(context.bot, chat_id, update.effective_message.message_id)
        await self._send_new(context, chat_id, reply)

    async def change_salon(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        chat_id = update.effective_chat.id
        reply = self.service.start(update.effective_user.id, chat_id)
        context.user_data.pop(self.INPUT_MODE, None)
        await self._delete_current_menu(context, chat_id)
        await self._safe_delete(context.bot, chat_id, update.effective_message.message_id)
        await self._send_new(context, chat_id, reply)

    async def callback(self, update, context):
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        if not query.message or query.message.chat.type != "private" or not query.from_user:
            return
        user_id, chat_id = query.from_user.id, query.message.chat.id
        data = query.data or ""
        if data.startswith("district:"):
            reply = self.service.choose_district(user_id, chat_id, data.split(":", 1)[1])
        elif data.startswith("search:"):
            reply = self.service.begin_search(user_id, chat_id, data.split(":", 1)[1])
        elif data.startswith("pick:"):
            reply = self.service.select(user_id, chat_id, data.split(":", 1)[1])
        elif data == "menu:catalog":
            reply = self.service.show_catalog(user_id, chat_id)
        elif data == "menu:booking":
            reply = self.service.booking(user_id, chat_id)
        elif data == "menu:question":
            reply = self.service.begin_question(user_id, chat_id)
        elif data == "menu:back":
            reply = self.service.show_menu(user_id, chat_id)
        elif data == "menu:districts":
            reply = self.service.start(user_id, chat_id)
        else:
            reply = self.service.start(user_id, chat_id)

        if data.startswith("search:"):
            context.user_data[self.INPUT_MODE] = "search"
        elif data == "menu:question":
            context.user_data[self.INPUT_MODE] = "question"
        else:
            context.user_data.pop(self.INPUT_MODE, None)
        await self._replace_menu(context, chat_id, reply, query.message)

    async def message(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        text = update.effective_message.text
        if not text:
            return
        try:
            chat_id = update.effective_chat.id
            input_mode = context.user_data.get(self.INPUT_MODE)
            reply = await self.service.message(update.effective_user.id, chat_id, text)
            if input_mode == "search":
                # Поисковый запрос — часть навигации, поэтому не оставляем его в чате.
                await self._safe_delete(context.bot, chat_id, update.effective_message.message_id)
                await self._replace_menu(context, chat_id, reply)
            else:
                # Вопрос пользователя сохраняем, а старую карточку-подсказку убираем.
                await self._delete_current_menu(context, chat_id)
                await self._send_new(context, chat_id, reply)
                context.user_data.pop(self.INPUT_MODE, None)
        except Exception:
            log.exception("Ошибка обработки сообщения")
            await update.effective_message.reply_text("Сейчас не получилось ответить. Попробуйте позже.")

    def run(self):
        self.app.run_polling()
