"""api/main.py (ADR-0008, P1): the HTTP layer over src/."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import main


class HealthTests(unittest.TestCase):
    def test_health_says_ok_and_the_commit(self):
        with patch.object(main.tracing, "release", return_value="abc1234"):
            response = TestClient(main.create_app()).get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "commit": "abc1234"})


class CorsTests(unittest.TestCase):
    def client(self, settings):
        with patch.object(main.settings, "get_setting", side_effect=lambda name: settings.get(name)):
            return TestClient(main.create_app())

    def preflight(self, client, origin):
        return client.options("/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})

    def test_only_the_frontend_may_call_from_a_browser(self):
        client = self.client({"RAGDOG_WEB_ORIGINS": "https://ragdog.vercel.app, https://ragdog.example/"})
        self.assertEqual(self.preflight(client, "https://ragdog.vercel.app").headers.get("access-control-allow-origin"),
                         "https://ragdog.vercel.app")
        self.assertEqual(self.preflight(client, "https://ragdog.example").status_code, 200)
        self.assertIsNone(self.preflight(client, "https://evil.example").headers.get("access-control-allow-origin"))

    def test_vercel_previews_by_pattern(self):
        client = self.client({"RAGDOG_WEB_ORIGINS": "https://ragdog.vercel.app",
                              "RAGDOG_WEB_ORIGIN_REGEX": r"https://ragdog-[a-z0-9-]+-rndigkwk\.vercel\.app"})
        preview = "https://ragdog-git-feat-chat-rndigkwk.vercel.app"
        self.assertEqual(self.preflight(client, preview).headers.get("access-control-allow-origin"), preview)
        self.assertIsNone(self.preflight(client, "https://ragdog-x-someone.vercel.app").headers.get("access-control-allow-origin"))

    def test_local_dev_server_by_default(self):
        client = self.client({})
        self.assertEqual(self.preflight(client, "http://localhost:3000").headers.get("access-control-allow-origin"),
                         "http://localhost:3000")


if __name__ == "__main__":
    unittest.main()


class WarmUpTests(unittest.TestCase):
    def test_deployed_startup_warms_up_before_requests(self):
        with patch.object(main.settings, "deployed", return_value=True), patch.object(main, "warm_up") as warm, \
                patch.object(main.request_log, "configure"):
            with TestClient(main.create_app()) as client:
                warm.assert_called_once()
                self.assertEqual(client.get("/health").status_code, 200)

    def test_local_startup_does_not(self):
        with patch.object(main, "warm_up") as warm:
            with TestClient(main.create_app()):
                warm.assert_not_called()

    def test_a_failed_warm_up_does_not_stop_the_app(self):
        from src import resources

        with patch.object(resources, "load_vector_db", side_effect=OSError("no database")), \
                self.assertLogs(main.request_log.logger, "INFO") as logs, self.assertLogs("api.main", "WARNING"):
            main.warm_up()
        self.assertIn("warmup failed", logs.output[-1])
