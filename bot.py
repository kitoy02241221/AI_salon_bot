import os
from dotenv import load_dotenv
from groq import Groq

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters
)

# Загружаем ключи
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Подключаем Groq
client = Groq(api_key=GROQ_API_KEY)


# Загружаем базу знаний салона
with open("knowledge.txt", "r", encoding="utf-8") as file:
    KNOWLEDGE = file.read()


# Инструкция для AI
SYSTEM_PROMPT = f"""
Ты — виртуальный администратор студии красоты.

Твоя задача:
- консультировать клиентов;
- отвечать на вопросы об услугах;
- помогать клиенту перейти к записи.

Правила:
- Отвечай дружелюбно и коротко.
- Используй только информацию из базы ниже.
- Не придумывай цены, мастеров и свободное время.
- Если информации нет — скажи, что нужно уточнить у администратора.
- Если клиент хочет записаться — предложи оставить заявку.

База студии:

{KNOWLEDGE}
"""


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_text = update.message.text

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": user_text
            }
        ],
        temperature=0.3
    )

    answer = response.choices[0].message.content

    await update.message.reply_text(answer)


def main():

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("AI администратор запущен!")

    app.run_polling()


if __name__ == "__main__":
    main()