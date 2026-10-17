"""scripts/log_regression_mlflow.py: what a weekly run sends to MLflow (no server, no mlflow import)."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_regression  # noqa: E402
import log_regression_mlflow  # noqa: E402


class LogRegressionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        patcher = patch.object(check_regression, "RESULTS_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, set_name, scores, **extra):
        (self.dir / f"{set_name}_ci-test.json").write_text(json.dumps({"run_scores": scores, "items": [1, 2], **extra}),
                                                           encoding="utf-8")

    def test_scores_and_the_verdict_against_the_same_limits(self):
        good = {name: (limit + 1 if direction == "min" else limit - 0.01)
                for name, direction, limit, _ in check_regression.LIMITS["routing"]}
        self.write("routing", {**good, "note": "text is not a metric"})
        metrics, params = log_regression_mlflow.set_metrics("routing", "ci-test")
        self.assertEqual(metrics["passed"], 1.0)
        self.assertNotIn("note", metrics)
        self.assertEqual((params["set"], params["items"]), ("routing", 2))
        bad = {name: (limit - 1 if direction == "min" else limit + 100)
               for name, direction, limit, _ in check_regression.LIMITS["routing"]}
        self.write("routing", bad)
        self.assertEqual(log_regression_mlflow.set_metrics("routing", "ci-test")[0]["passed"], 0.0)

    def test_a_missing_set_is_left_out(self):
        self.assertIsNone(log_regression_mlflow.set_metrics("crag", "ci-test"))

    def test_without_a_token_nothing_is_sent(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DAGSHUB_TOKEN", None)
            os.environ.pop("MLFLOW_TRACKING_PASSWORD", None)
            with patch.object(log_regression_mlflow, "set_metrics", side_effect=AssertionError("not read")):
                self.assertEqual(log_regression_mlflow.main(["ci-test", "crag"]), 0)


if __name__ == "__main__":
    unittest.main()
