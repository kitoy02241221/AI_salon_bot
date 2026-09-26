from dataclasses import dataclass, field

from .domain import (
    DISTRICTS,
    Answerer,
    Catalog,
    Knowledge,
    ServiceCatalog,
    SessionState,
    Sessions,
)


@dataclass
class Reply:
    text: str
    buttons: list[tuple[str, str]] = field(default_factory=list)


class SalonService:
    def __init__(
        self,
        catalog: Catalog,
        sessions: Sessions,
        knowledge: Knowledge,
        services: ServiceCatalog,
        answerer: Answerer,
    ):
        self.catalog = catalog
        self.sessions = sessions
        self.knowledge = knowledge
        self.services = services
        self.answerer = answerer

    @staticmethod
    def _district_buttons() -> list[tuple[str, str]]:
        buttons = [(name, "district:" + code) for code, name in DISTRICTS.items()]
        buttons.append(("Поиск по названию", "search:all"))
        return buttons

    @staticmethod
    def _salon_buttons(salons) -> list[tuple[str, str]]:
        return [
            (f"{salon.name} — {salon.address}", "pick:" + salon.id)
            for salon in salons
        ]

    @staticmethod
    def _menu_buttons() -> list[tuple[str, str]]:
        return [
            ("Каталог услуг", "menu:catalog"),
            ("Записаться к мастеру", "menu:booking"),
            ("Задать вопрос", "menu:question"),
            ("Сменить район или салон", "menu:districts"),
        ]

    def start(self, user_id: int, chat_id: int, code: str = "") -> Reply:
        salon = self.catalog.by_code(code) if code else None
        if salon:
            self.sessions.set(
                user_id,
                chat_id,
                SessionState(salon.id, salon.district, "menu"),
            )
            return self._salon_menu(salon)
        self.sessions.set(user_id, chat_id, SessionState())
        return Reply("Выберите район:", self._district_buttons())

    def choose_district(self, user_id: int, chat_id: int, code: str) -> Reply:
        district = DISTRICTS.get(code)
        if not district:
            return self.start(user_id, chat_id)
        self.sessions.set(
            user_id,
            chat_id,
            SessionState(None, district, "salon_list"),
        )
        salons = self.catalog.list_by_district(district)
        buttons = self._salon_buttons(salons)
        buttons.append(("Поиск по названию", "search:district"))
        buttons.append(("Назад к районам", "menu:districts"))
        text = f"Салоны района «{district}». Выберите салон:"
        if not salons:
            text = f"В районе «{district}» пока нет подключённых салонов. Можно воспользоваться поиском."
        return Reply(text, buttons)

    def begin_search(self, user_id: int, chat_id: int, scope: str) -> Reply:
        state = self.sessions.get(user_id, chat_id)
        if scope == "all":
            self.sessions.set(user_id, chat_id, SessionState(None, None, "search_all"))
            return Reply("Введите название салона. Поиск будет выполнен среди всех районов Калининграда.")
        if scope == "district" and state.district in DISTRICTS.values():
            self.sessions.set(
                user_id,
                chat_id,
                SessionState(None, state.district, "search_district"),
            )
            return Reply(f"Введите название салона. Поиск будет выполнен только в районе «{state.district}».")
        return self.start(user_id, chat_id)

    def select(self, user_id: int, chat_id: int, salon_id: str) -> Reply:
        salon = self.catalog.by_id(salon_id)
        if not salon:
            return Reply("Салон недоступен. Выберите район и другой салон.", self._district_buttons())
        self.sessions.set(
            user_id,
            chat_id,
            SessionState(salon.id, salon.district, "menu"),
        )
        return self._salon_menu(salon)

    def _salon_menu(self, salon) -> Reply:
        return Reply(
            f"Выбран салон «{salon.name}».\n"
            f"Район: {salon.district}.\n"
            f"Адрес: {salon.address}.\n\n"
            "Что вы хотите сделать?",
            self._menu_buttons(),
        )

    def show_menu(self, user_id: int, chat_id: int) -> Reply:
        state = self.sessions.get(user_id, chat_id)
        salon = self.catalog.by_id(state.salon_id) if state.salon_id else None
        if not salon:
            return self.start(user_id, chat_id)
        self.sessions.set(
            user_id,
            chat_id,
            SessionState(salon.id, salon.district, "menu"),
        )
        return self._salon_menu(salon)

    def show_catalog(self, user_id: int, chat_id: int) -> Reply:
        state = self.sessions.get(user_id, chat_id)
        salon = self.catalog.by_id(state.salon_id) if state.salon_id else None
        if not salon:
            return self.start(user_id, chat_id)
        items = self.services.list_services(salon.id)
        if items:
            lines = [f"• {item.name} — {item.price}" for item in items]
            text = f"Каталог услуг салона «{salon.name}»:\n\n" + "\n".join(lines)
        else:
            text = f"В каталоге салона «{salon.name}» пока нет услуг."
        return Reply(text, [("Вернуться в меню салона", "menu:back")])

    def booking(self, user_id: int, chat_id: int) -> Reply:
        state = self.sessions.get(user_id, chat_id)
        salon = self.catalog.by_id(state.salon_id) if state.salon_id else None
        if not salon:
            return self.start(user_id, chat_id)
        return Reply(
            "Функция записи к мастеру пока не подключена. Она будет добавлена позже.",
            [("Вернуться в меню салона", "menu:back")],
        )

    def begin_question(self, user_id: int, chat_id: int) -> Reply:
        state = self.sessions.get(user_id, chat_id)
        salon = self.catalog.by_id(state.salon_id) if state.salon_id else None
        if not salon:
            return self.start(user_id, chat_id)
        self.sessions.set(
            user_id,
            chat_id,
            SessionState(salon.id, salon.district, "question"),
        )
        return Reply("Напишите вопрос о выбранном салоне:")

    async def message(self, user_id: int, chat_id: int, text: str) -> Reply:
        state = self.sessions.get(user_id, chat_id)
        if state.mode in {"search_all", "search_district"}:
            district = state.district if state.mode == "search_district" else None
            matches = self.catalog.search(text, district=district)
            if not matches:
                scope = f" в районе «{district}»" if district else ""
                return Reply(f"Салон{scope} не найден. Введите другое название (минимум 2 символа).")
            scope_text = f" в районе «{district}»" if district else " во всех районах"
            return Reply(
                "Найденные салоны" + scope_text + ":",
                self._salon_buttons(matches),
            )
        if state.mode == "question" and state.salon_id:
            salon = self.catalog.by_id(state.salon_id)
            if not salon:
                return self.start(user_id, chat_id)
            facts = self.knowledge.relevant(salon.id, text)
            answer = await self.answerer.answer(salon.name, text, facts)
            return Reply(answer, [("Вернуться в меню салона", "menu:back")])
        if state.mode == "districts":
            return Reply("Выберите район кнопкой ниже:", self._district_buttons())
        if state.mode == "salon_list" and state.district:
            return self.choose_district(
                user_id,
                chat_id,
                next(code for code, name in DISTRICTS.items() if name == state.district),
            )
        return Reply("Выберите действие кнопкой ниже:", self._menu_buttons())
