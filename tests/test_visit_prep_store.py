"""src/visit_prep_store.py MemoryStore: the same rules as the Postgres store (scripts/check_visit_prep_store.py
checks those against Supabase in a throwaway schema)."""

import unittest
from unittest.mock import patch

from src import visit_prep_store as vps


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store, self.now = vps.MemoryStore(), 1_800_000_000.0

    def test_reports_a_day_per_person_with_a_refund(self):
        self.assertTrue(self.store.take_report("a", 2, self.now))
        self.assertTrue(self.store.take_report("a", 2, self.now))
        self.assertFalse(self.store.take_report("a", 2, self.now))
        self.assertTrue(self.store.take_report("b", 2, self.now))
        self.store.refund_report("a")
        self.assertTrue(self.store.take_report("a", 2, self.now))
        self.assertTrue(self.store.take_report("a", 2, self.now + vps.DAY_SECONDS + 1))  # a day later

    def test_a_pause_is_taken_by_its_owner_once_within_the_time(self):
        pending = {"thread_id": "t", "consultation": "c"}
        self.store.save_paused("t", "a", pending, self.now)
        self.assertIsNone(self.store.take_paused("t", "b", self.now))
        taken = self.store.take_paused("t", "a", self.now)
        self.assertEqual((taken["consultation"], taken["paused_at"]), ("c", self.now))
        self.assertIsNone(self.store.take_paused("t", "a", self.now))
        self.store.put_back("t", "a", taken, taken["paused_at"])
        self.assertIsNotNone(self.store.take_paused("t", "a", self.now))
        self.store.save_paused("old", "a", pending, self.now)
        later = self.now + vps.PAUSED_RUN_TTL_SECONDS + 1
        self.assertIsNone(self.store.take_paused("old", "a", later))
        self.assertEqual(self.store.expire(later), ["old"])

    def test_people_are_kept_as_hashes(self):
        self.store.take_report("0123456789abcdef0123456789abcdef", 2, self.now)
        self.assertNotIn("0123456789abcdef0123456789abcdef", self.store._reports)


class StoreChoiceTests(unittest.TestCase):
    def tearDown(self):
        vps._reset_for_tests(None)

    def test_local_runs_use_memory_even_with_a_database_url(self):
        vps._reset_for_tests(None)
        with patch.object(vps.settings, "deployed", return_value=False), \
                patch.object(vps.settings, "get_setting", return_value="postgresql://x"):
            self.assertIsInstance(vps.store(), vps.MemoryStore)

    def test_a_broken_database_falls_back_to_memory(self):
        vps._reset_for_tests(None)
        with patch.object(vps.settings, "deployed", return_value=True), \
                patch.object(vps.settings, "get_setting", return_value="postgresql://x"), \
                patch.object(vps, "PostgresStore", side_effect=OSError("down")), \
                self.assertLogs("src.visit_prep_store", level="WARNING"):
            self.assertIsInstance(vps.store(), vps.MemoryStore)


if __name__ == "__main__":
    unittest.main()
