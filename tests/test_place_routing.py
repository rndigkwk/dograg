"""Regression guard for tests/data/place_routing_questions.json with the keyword rules alone
(no API key): every place search gets its kind, every question its route.
The same set with the LLM router: scripts/evaluate_place_routing.py --llm."""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import evaluate_place_routing


class PlaceRoutingSetTests(unittest.TestCase):
    def test_keyword_rules_get_every_kind_and_route(self):
        import json

        items = json.loads(evaluate_place_routing.QUESTIONS.read_text(encoding="utf-8"))["items"]
        summary = evaluate_place_routing.evaluate(items, use_llm=False)["summary"]
        self.assertEqual(summary["place_searches"], 26)
        self.assertEqual(summary["errors"], [])
        self.assertEqual((summary["kind_accuracy"], summary["rule_route_accuracy"]), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
