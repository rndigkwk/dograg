"""scripts/check_regression.py: limits on saved experiment results."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import check_regression


class CheckRegressionTests(unittest.TestCase):
    def run_check(self, crag_scores):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        results = Path(directory.name)
        (results / "crag_ci.json").write_text(json.dumps({"run_scores": crag_scores}), encoding="utf-8")
        (results / "routing_ci.json").write_text(
            json.dumps({"run_scores": {"route_accuracy": 1.0, "kind_accuracy": 1.0}}), encoding="utf-8")
        summary = results / "summary.md"
        with patch.object(check_regression, "RESULTS_DIR", results), patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}):
            code = check_regression.main(["crag", "ci", "routing", "ci"])
        return code, summary.read_text(encoding="utf-8")

    def test_scores_within_limits_pass_and_write_the_job_summary(self):
        code, summary = self.run_check({"accuracy": 0.917, "over_abstain": 0.026, "missed_abstain": 0.18, "latency_p90_s": 12.3})
        self.assertEqual(code, 0)
        self.assertIn("| crag | accuracy | 0.917 |", summary)
        self.assertNotIn("❌", summary)

    def test_a_drop_or_a_missing_score_fails(self):
        code, summary = self.run_check({"accuracy": 0.80, "over_abstain": 0.026, "missed_abstain": 0.18})
        self.assertEqual(code, 1)
        self.assertIn("| crag | accuracy | 0.800 |", summary)
        self.assertIn("| crag | latency_p90_s | 없음 |", summary)


if __name__ == "__main__":
    unittest.main()
