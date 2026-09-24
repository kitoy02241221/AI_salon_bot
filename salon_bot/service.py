from dataclasses import dataclass, field

from .domain import Answerer, Catalog, Knowledge, Sessions


@dataclass
class Reply:
    text: str
    buttons: list[tuple[str, str]] = field(default_factory=list)


class SalonService:
    def __init__(self, catalog: Catalog, sessions: Sessions, knowledge: Knowledge, answerer: Answerer):
        self.catalog, self.sessions, self.knowledge, self.answerer = catalog, sessions, knowledge, answerer

    def start(self, user_id: int, chat_id: int, code: str = "") -> Reply:
        salon = self.catalog.by_code(code) if code else None
        if salon:
            self.sessions.set(user_id, chat_id, salon.id, False)
            return Reply(f"Выбран салон «{salon.name}» ({salon.city}). Задайте вопрос. Для смены: /salon")
        current, _ = self.sessions.get(user_id, chat_id)
        self.sessions.set(user_id, chat_id, current, True)
        return Reply("Напишите название салона или город. Затем выберите салон из найденных.")

    def select(self, user_id: int, chat_id: int, salon_id: str) -> Reply:
        salon = self.catalog.by_id(salon_id)
        if not salon:
            return Reply("Салон недоступен. Напишите /salon и выберите другой.")
        self.sessions.set(user_id, chat_id, salon.id, False)
        return Reply(f"Выбран салон «{salon.name}» ({salon.city}). Задайте вопрос. Для смены: /salon")

    async def message(self, user_id: int, chat_id: int, text: str) -> Reply:
        current, searching = self.sessions.get(user_id, chat_id)
        if searching or not current:
            matches = self.catalog.search(text)
            if not matches:
                return Reply("Салон не найден. Введите другое название или город (минимум 2 символа).")
            return Reply("Найденные салоны. Выберите нужный или уточните запрос:",
                         [(f"{s.name} — {s.city}", "pick:" + s.id) for s in matches])
        salon = self.catalog.by_id(current)
        if not salon:
            self.sessions.set(user_id, chat_id, None, True)
            return Reply("Этот салон недоступен. Напишите название другого салона.")
        facts = self.knowledge.relevant(salon.id, text)
        return Reply(await self.answerer.answer(salon.name, text, facts))
