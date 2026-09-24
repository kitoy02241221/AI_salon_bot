import asyncio
import tempfile
import unittest
from pathlib import Path

from salon_bot.service import SalonService
from salon_bot.store import SQLiteStore


class TenantRoutingTest(unittest.TestCase):
    def test_selection_and_knowledge_are_isolated(self):
        class CapturingAnswerer:
            async def answer(self, name, question, facts):
                return name + ": " + " | ".join(facts)

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp))
            a = store.add_salon("Студия Лотос", "Калининград", ["А: маникюр 1500 рублей"])
            b = store.add_salon("Лотос Центр", "Москва", ["Б: массаж 2200 рублей"])
            service = SalonService(store, store, store, CapturingAnswerer())

            self.assertEqual([a], store.search("студ"))
            self.assertEqual({a, b}, set(store.search("лотос")))
            service.start(42, 42, a.code)
            service.start(43, 43, b.code)
            answer_a = asyncio.run(service.message(42, 42, "Сколько стоит маникюр?")).text
            answer_b = asyncio.run(service.message(43, 43, "Сколько стоит массаж?")).text
            self.assertIn("А: маникюр", answer_a)
            self.assertNotIn("Б: массаж", answer_a)
            self.assertIn("Б: массаж", answer_b)
            self.assertNotIn("А: маникюр", answer_b)
            self.assertEqual("", "".join(store.relevant("../catalog", "вопрос")))
            service.start(42, 42)
            self.assertEqual(2, len(asyncio.run(service.message(42, 42, "лотос")).buttons))
            service.select(42, 42, b.id)
            self.assertIn("Б: массаж", asyncio.run(service.message(42, 42, "массаж")).text)


if __name__ == "__main__":
    unittest.main()
