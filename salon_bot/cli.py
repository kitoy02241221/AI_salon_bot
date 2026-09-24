"""CLI and composition root."""
import argparse
import logging
import os
import re
from pathlib import Path

from .ai import GroqAnswerer
from .service import SalonService
from .store import SQLiteStore


def main():
    from dotenv import load_dotenv
    root = Path(__file__).resolve().parent.parent
    load_dotenv(dotenv_path=root / ".env")
    parser = argparse.ArgumentParser(description="AI-администратор сети салонов")
    parser.add_argument("--data", type=Path, default=root / "data")
    commands = parser.add_subparsers(dest="command")
    add = commands.add_parser("add-salon")
    add.add_argument("--name", required=True)
    add.add_argument("--city", required=True)
    add.add_argument("--knowledge", type=Path, required=True)
    commands.add_parser("run")
    commands.add_parser("list-salons")
    args = parser.parse_args()
    store = SQLiteStore(args.data)
    if args.command == "add-salon":
        content = args.knowledge.read_text(encoding="utf-8")
        facts = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
        salon = store.add_salon(args.name, args.city, facts)
        print(f"Создан салон «{salon.name}» ({salon.city}). ID: {salon.id}")
        username = os.getenv("BOT_USERNAME", "").lstrip("@")
        print(f"Ссылка / QR: https://t.me/{username}?start={salon.code}" if username
              else f"Параметр /start: {salon.code} (укажите BOT_USERNAME для ссылки)")
        return
    if args.command == "list-salons":
        for salon in store.list_active():
            print(f"{salon.id} | {salon.name} | {salon.city} | {salon.code}")
        return
    token, key = os.getenv("TELEGRAM_TOKEN"), os.getenv("GROQ_API_KEY")
    if not token or not key:
        parser.error("Нужны TELEGRAM_TOKEN и GROQ_API_KEY в .env")
    from .telegram import TelegramBot
    logging.basicConfig(level=logging.INFO)
    service = SalonService(store, store, store, GroqAnswerer(key, os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")))
    TelegramBot(token, service).run()


if __name__ == "__main__":
    main()
