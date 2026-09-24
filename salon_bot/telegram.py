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
        self.app.add_handler(CallbackQueryHandler(self.select, pattern=r"^pick:[a-f0-9]{32}$"))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.message))

    async def start(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        code = context.args[0] if context.args else ""
        reply = self.service.start(update.effective_user.id, update.effective_chat.id, code)
        await update.effective_message.reply_text(reply.text)

    async def change_salon(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        reply = self.service.start(update.effective_user.id, update.effective_chat.id)
        await update.effective_message.reply_text(reply.text)

    async def select(self, update, context):
        query = update.callback_query
        if query is None:
            return
        await query.answer()
        if not query.message or query.message.chat.type != "private" or not query.from_user:
            return
        reply = self.service.select(query.from_user.id, query.message.chat.id, query.data[5:])
        await query.message.reply_text(reply.text)

    async def message(self, update, context):
        if update.effective_chat.type != "private" or not update.effective_user:
            return
        text = update.effective_message.text
        if not text:
            return
        try:
            reply = await self.service.message(update.effective_user.id, update.effective_chat.id, text)
            if reply.buttons:
                keyboard = [[InlineKeyboardButton(label, callback_data=code)]
                            for label, code in reply.buttons]
                await update.effective_message.reply_text(reply.text, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.effective_message.reply_text(reply.text[:4000])
        except Exception:
            log.exception("Ошибка обработки сообщения")
            await update.effective_message.reply_text("Сейчас не получилось ответить. Попробуйте позже.")

    def run(self):
        self.app.run_polling()
