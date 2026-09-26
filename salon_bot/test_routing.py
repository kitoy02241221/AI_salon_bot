import asyncio
import tempfile
import unittest
from pathlib import Path

from salon_bot.service import SalonService
from salon_bot.store import SQLiteStore


class TenantRoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SQLiteStore(Path(self.tmp.name))
        self.a = self.store.add_salon(
            "Студия Оксаны Ким",
            "Ленинградский",
            "Калининград, ул. Флотская, 9",
            ["Маникюр классический — 1500 рублей.", "Факт только салона А"],
        )
        self.b = self.store.add_salon(
            "Лотос Центр",
            "Центральный",
            "Калининград, проспект Мира, 10",
            ["Маникюр классический — 4900 рублей.", "Факт только салона Б"],
        )
        self.c = self.store.add_salon(
            "Оксана Beauty",
            "Центральный",
            "Калининград, ул. Театральная, 5",
            ["Педикюр — 3200 рублей."],
        )

        class CapturingAnswerer:
            async def answer(inner_self, name, question, facts):
                return name + ": " + " | ".join(facts)

        self.service = SalonService(
            self.store, self.store, self.store, self.store, CapturingAnswerer()
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_has_three_districts_and_global_search(self):
        reply = self.service.start(1, 1)
        labels = [label for label, _ in reply.buttons]
        self.assertEqual(
            ["Центральный", "Ленинградский", "Московский", "Поиск по названию"],
            labels,
        )
        self.assertNotIn("Область", labels)

    def test_district_list_contains_only_its_salons_and_addresses(self):
        reply = self.service.choose_district(1, 1, "central")
        labels = [label for label, _ in reply.buttons]
        self.assertTrue(any("Лотос Центр" in label and "проспект Мира, 10" in label for label in labels))
        self.assertTrue(any("Оксана Beauty" in label and "Театральная, 5" in label for label in labels))
        self.assertFalse(any("Студия Оксаны Ким" in label for label in labels))
        self.assertEqual("Поиск по названию", labels[-2])

    def test_global_and_scoped_search_have_different_boundaries(self):
        self.service.start(1, 1)
        self.service.begin_search(1, 1, "all")
        global_reply = asyncio.run(self.service.message(1, 1, "окс"))
        self.assertEqual(2, len(global_reply.buttons))

        self.service.choose_district(1, 1, "central")
        self.service.begin_search(1, 1, "district")
        scoped_reply = asyncio.run(self.service.message(1, 1, "окс"))
        self.assertEqual(1, len(scoped_reply.buttons))
        self.assertIn("Оксана Beauty", scoped_reply.buttons[0][0])

    def test_selected_salon_menu_has_address_and_actions(self):
        reply = self.service.select(1, 1, self.a.id)
        self.assertIn("Ленинградский", reply.text)
        self.assertIn("Флотская, 9", reply.text)
        labels = [label for label, _ in reply.buttons]
        self.assertEqual(
            ["Каталог услуг", "Записаться к мастеру", "Задать вопрос", "Сменить район или салон"],
            labels,
        )

    def test_catalog_and_answers_are_isolated(self):
        self.service.select(1, 1, self.a.id)
        catalog_a = self.service.show_catalog(1, 1).text
        self.assertIn("1500", catalog_a)
        self.assertNotIn("4900", catalog_a)

        self.service.select(2, 2, self.b.id)
        catalog_b = self.service.show_catalog(2, 2).text
        self.assertIn("4900", catalog_b)
        self.assertNotIn("1500", catalog_b)

        self.service.begin_question(1, 1)
        answer_a = asyncio.run(self.service.message(1, 1, "Что известно?")).text
        self.service.begin_question(2, 2)
        answer_b = asyncio.run(self.service.message(2, 2, "Что известно?")).text
        self.assertIn("Факт только салона А", answer_a)
        self.assertNotIn("Факт только салона Б", answer_a)
        self.assertIn("Факт только салона Б", answer_b)
        self.assertNotIn("Факт только салона А", answer_b)

    def test_booking_does_not_create_an_application(self):
        self.service.select(1, 1, self.a.id)
        reply = self.service.booking(1, 1)
        self.assertIn("пока не подключена", reply.text)
        self.assertEqual([("Вернуться в меню салона", "menu:back")], reply.buttons)

    def test_invalid_tenant_path_is_rejected(self):
        self.assertEqual([], self.store.relevant("../catalog", "вопрос"))


if __name__ == "__main__":
    unittest.main()
