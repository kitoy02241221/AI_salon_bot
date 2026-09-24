from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Salon:
    id: str
    code: str
    name: str
    city: str


class Catalog(Protocol):
    def by_code(self, code: str) -> Salon | None: ...
    def by_id(self, salon_id: str) -> Salon | None: ...
    def search(self, query: str, limit: int = 8) -> list[Salon]: ...


class Sessions(Protocol):
    def get(self, user_id: int, chat_id: int) -> tuple[str | None, bool]: ...
    def set(self, user_id: int, chat_id: int, salon_id: str | None, searching: bool) -> None: ...


class Knowledge(Protocol):
    def relevant(self, salon_id: str, question: str, limit: int = 16) -> list[str]: ...


class Answerer(Protocol):
    async def answer(self, name: str, question: str, facts: list[str]) -> str: ...
