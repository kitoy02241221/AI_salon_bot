"""Telegram transport: only this module depends on python-telegram-bot."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from .service import SalonService

log = logging.getLogger(__name__)


class TelegramBot:
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
    async def _send(message, reply):
        keyboard = None
        if reply.buttons:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(label, callback_data=code)]
                for label, code in reply.buttons
            ])
        await message.reply_text(reply.text[:4000], reply_markup=keyboard)

    async def start(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        code = context.args[0] if context.args else ""
        reply = self.service.start(update.effective_user.id, update.effective_chat.id, code)
        await self._send(update.effective_message, reply)

    async def change_salon(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        reply = self.service.start(update.effective_user.id, update.effective_chat.id)
        await self._send(update.effective_message, reply)

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
        await self._send(query.message, reply)

    async def message(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        text = update.effective_message.text
        if not text:
            return
        try:
            reply = await self.service.message(update.effective_user.id, update.effective_chat.id, text)
            await self._send(update.effective_message, reply)
        except Exception:
            log.exception("Ошибка обработки сообщения")
            await update.effective_message.reply_text("Сейчас не получилось ответить. Попробуйте позже.")

    def run(self):
        self.app.run_polling()
