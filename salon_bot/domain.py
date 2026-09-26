from dataclasses import dataclass
from typing import Protocol


DISTRICTS: dict[str, str] = {
    "central": "Центральный",
    "leningrad": "Ленинградский",
    "moscow": "Московский",
}


@dataclass(frozen=True)
class Salon:
    id: str
    code: str
    name: str
    city: str
    district: str
    address: str


@dataclass(frozen=True)
class ServiceItem:
    name: str
    price: str


@dataclass(frozen=True)
class SessionState:
    salon_id: str | None = None
    district: str | None = None
    mode: str = "districts"


class Catalog(Protocol):
    def by_code(self, code: str) -> Salon | None: ...
    def by_id(self, salon_id: str) -> Salon | None: ...
    def list_by_district(self, district: str) -> list[Salon]: ...
    def search(self, query: str, district: str | None = None, limit: int = 8) -> list[Salon]: ...


class Sessions(Protocol):
    def get(self, user_id: int, chat_id: int) -> SessionState: ...
    def set(self, user_id: int, chat_id: int, state: SessionState) -> None: ...


class Knowledge(Protocol):
    def relevant(self, salon_id: str, question: str, limit: int = 16) -> list[str]: ...


class ServiceCatalog(Protocol):
    def list_services(self, salon_id: str) -> list[ServiceItem]: ...


class Answerer(Protocol):
    async def answer(self, name: str, question: str, facts: list[str]) -> str: ...
