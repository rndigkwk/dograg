"""src/rate_limit.py: 10 questions an hour and 30 a day per browser, looser limits per network."""

import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src import rate_limit


class FakeTable:
    """The few statements rate_limit runs, on rows in memory: (at, person, network)."""

    def __init__(self):
        self.rows = []
        self.statements = []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.statements.append(sql)
        result = SimpleNamespace(fetchall=lambda: [])
        if sql.startswith("delete"):
            self.rows = [row for row in self.rows if row[0] >= params[0]]
        elif sql.startswith("insert"):
            self.rows.append((datetime.now(timezone.utc), *params))
        elif sql.startswith("select"):
            columns = re.findall(r"count\(\*\) filter \(where (\w+) =", sql)
            values = []
            for n, column in enumerate(columns):
                key, since = params[4 * n], params[4 * n + 1]
                index = 1 if column == "person" else 2
                found = [row[0] for row in self.rows if row[index] == key and row[0] > since]
                values += [len(found), min(found) if found else None]
            result = SimpleNamespace(fetchone=lambda: tuple(values))
        return result

    def add(self, person, network, ago):
        self.rows.append((datetime.now(timezone.utc) - ago, rate_limit._hash("person", person),
                          rate_limit._hash("network", network)))


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeTable()
        rate_limit._ready = False
        patches = [patch.object(rate_limit.settings, "deployed", return_value=True),
                   patch.object(rate_limit.settings, "get_setting", return_value="postgresql://x"),
                   patch("src.supabase_store.connector", return_value=self.table),
                   patch.object(rate_limit.data_gaps, "from_check", return_value=False)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_ten_an_hour_then_a_wait(self):
        for _ in range(10):
            self.assertTrue(rate_limit.check("browser-a", "1.2.3.4").allowed)
        refused = rate_limit.check("browser-a", "1.2.3.4")
        self.assertFalse(refused.allowed)
        self.assertTrue(refused.per_hour)
        self.assertGreaterEqual(refused.wait_minutes, 59)
        self.assertTrue(rate_limit.check("browser-b", "1.2.3.4").allowed)  # someone else on the same network

    def test_thirty_a_day(self):
        for hour in range(3):
            for _ in range(10):
                self.table.add("browser-a", "1.2.3.4", timedelta(hours=2 + hour * 2))
        refused = rate_limit.check("browser-a", "5.6.7.8")
        self.assertFalse(refused.allowed)
        self.assertFalse(refused.per_hour)
        self.assertIn("시간 뒤", rate_limit.message(refused))

    def test_a_shared_network_has_its_own_looser_limit(self):
        for n in range(60):
            self.table.add(f"browser-{n}", "10.0.0.1", timedelta(minutes=30))
        self.assertFalse(rate_limit.check("browser-new", "10.0.0.1").allowed)  # clearing the browser does not reset it
        self.assertTrue(rate_limit.check("browser-new", "10.0.0.2").allowed)

    def test_only_hashes_are_stored(self):
        rate_limit.check("browser-a", "1.2.3.4")
        self.assertNotIn("browser-a", str(self.table.rows))
        self.assertNotIn("1.2.3.4", str(self.table.rows))
        self.assertTrue(any("enable row level security" in sql for sql in self.table.statements))

    def test_old_rows_are_deleted(self):
        self.table.add("browser-a", "1.2.3.4", timedelta(hours=rate_limit.KEEP_HOURS + 1))
        with patch.object(rate_limit, "CLEAN_EVERY", 1):
            rate_limit.check("browser-b", "1.2.3.4")
        self.assertEqual(len(self.table.rows), 1)

    def test_not_counted_locally_for_the_deployment_check_or_when_the_database_fails(self):
        with patch.object(rate_limit.settings, "deployed", return_value=False):
            self.assertTrue(rate_limit.check("browser-a", "1.2.3.4").allowed)
        with patch.object(rate_limit.data_gaps, "from_check", return_value=True):
            self.assertTrue(rate_limit.check("browser-a", "1.2.3.4").allowed)
        self.assertEqual(self.table.rows, [])
        with patch("src.supabase_store.connector", side_effect=OSError("down")):
            self.assertTrue(rate_limit.check("browser-a", "1.2.3.4").allowed)

    def test_the_first_forwarded_address_is_the_client(self):
        context = SimpleNamespace(headers={"X-Forwarded-For": "203.0.113.5, 35.191.0.1"}, ip_address="35.191.0.1")
        with patch("streamlit.context", context):
            self.assertEqual(rate_limit.client_network(), "203.0.113.5")
        self.assertEqual(rate_limit.client_network(), "")  # outside a Streamlit session


if __name__ == "__main__":
    unittest.main()
