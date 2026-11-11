"""api/metrics.py: Prometheus counters for the kind cluster, off unless RAGDOG_METRICS=1."""

import os
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import main, metrics


class MetricsTests(unittest.TestCase):
    def test_counts_by_route_template_and_status(self):
        app = FastAPI()

        @app.get("/items/{name}")
        def item(name: str) -> dict:
            return {"name": name}

        metrics.install(app)
        client = TestClient(app)
        client.get("/items/a")
        client.get("/items/b")
        client.get("/random-scanner-path")
        text = client.get("/metrics").text
        self.assertIn('ragdog_requests_total{method="GET",route="/items/{name}",status="200"} 2.0', text)
        self.assertIn('ragdog_requests_total{method="GET",route="unmatched",status="404"} 1.0', text)
        self.assertIn('ragdog_request_seconds_count{route="/items/{name}"} 2.0', text)
        self.assertNotIn('route="/metrics"', text)  # scrapes are not counted

    def test_off_unless_turned_on(self):
        with mock.patch.dict(os.environ, {"RAGDOG_METRICS": ""}):
            self.assertEqual(TestClient(main.create_app()).get("/metrics").status_code, 404)
        with mock.patch.dict(os.environ, {"RAGDOG_METRICS": "1"}):
            client = TestClient(main.create_app())
            client.get("/health")
            self.assertIn('route="/health"', client.get("/metrics").text)


if __name__ == "__main__":
    unittest.main()
