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
        with patch.object(check_regression, "RESULTS_DIR", results), patch.object(check_regression, "BASELINE_DIR", results), \
                patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}):
            code = check_regression.main(["crag", "ci", "routing", "ci"])
        return code, summary.read_text(encoding="utf-8")

    def test_scores_within_limits_pass_and_write_the_job_summary(self):
        code, summary = self.run_check({"accuracy": 0.917, "over_abstain": 0.026, "missed_abstain": 0.18, "latency_p90_s": 12.3})
        self.assertEqual(code, 0)
        self.assertIn("| crag | 절대 | accuracy | 0.917 |", summary)
        self.assertNotIn("❌", summary)

    def test_a_drop_or_a_missing_score_fails(self):
        code, summary = self.run_check({"accuracy": 0.80, "over_abstain": 0.026, "missed_abstain": 0.18})
        self.assertEqual(code, 1)
        self.assertIn("| crag | 절대 | accuracy | 0.800 |", summary)
        self.assertIn("| crag | 경보 | latency_p90_s | 없음 |", summary)


    def test_the_visit_team_set_fails_when_workers_repeat(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        results = Path(directory.name)
        scores = {"dog_pass_rate": 1.0, "scope_handled_rate": 1.0, "urgent_accuracy": 1.0,
                  "hospitals_listed_rate": 1.0, "repeat_suspect_rate": 0.0, "latency_p90_s": 80.0,
                  "reask_rate": 0.0, "no_answer_rate": 0.0}
        (results / "visit_ok.json").write_text(json.dumps({"run_scores": scores}), encoding="utf-8")
        (results / "visit_loop.json").write_text(
            json.dumps({"run_scores": {**scores, "repeat_suspect_rate": 0.5}}), encoding="utf-8")
        with patch.object(check_regression, "RESULTS_DIR", results), patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            self.assertEqual(check_regression.main(["visit", "ok"]), 0)
            self.assertEqual(check_regression.main(["visit", "loop"]), 1)  # 6 of 12 runs repeated a worker

    def test_the_visit_team_set_fails_when_researchers_stop_without_answers(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        results = Path(directory.name)
        scores = {"dog_pass_rate": 1.0, "scope_handled_rate": 1.0, "urgent_accuracy": 1.0,
                  "hospitals_listed_rate": 1.0, "repeat_suspect_rate": 0.0, "latency_p90_s": 80.0,
                  "reask_rate": 2 / 12, "no_answer_rate": 1 / 12}
        runs = {"ok": scores, "reasks": {**scores, "reask_rate": 4 / 12}, "lost": {**scores, "no_answer_rate": 2 / 12},
                "old": {key: value for key, value in scores.items() if key not in ("reask_rate", "no_answer_rate")}}
        for name, run_scores in runs.items():
            (results / f"visit_{name}.json").write_text(json.dumps({"run_scores": run_scores}), encoding="utf-8")
        with patch.object(check_regression, "RESULTS_DIR", results), patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            self.assertEqual(check_regression.main(["visit", "ok"]), 0)  # 2 asked again, 1 lost: within the limits
            self.assertEqual(check_regression.main(["visit", "reasks"]), 1)
            self.assertEqual(check_regression.main(["visit", "lost"]), 1)
            self.assertEqual(check_regression.main(["visit", "old"]), 1)  # a run without the scores is not a pass

    def test_health_answer_correctness_has_a_floor(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        results = Path(directory.name)
        judge = check_regression.JUDGES["answer"]
        runs = {"ok": {"judge_model": judge, "run_scores": {"answer_correctness": 0.28}},
                "bad": {"judge_model": judge, "run_scores": {"answer_correctness": 0.20}},
                # another judge scores on another scale: the limit no longer applies (Day 60)
                "other_judge": {"judge_model": "gpt-4.1", "run_scores": {"answer_correctness": 0.40}},
                "unrecorded": {"run_scores": {"answer_correctness": 0.28}}}
        for name, result in runs.items():
            (results / f"answer_{name}.json").write_text(json.dumps(result), encoding="utf-8")
        with patch.object(check_regression, "RESULTS_DIR", results), patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}):
            self.assertEqual(check_regression.main(["answer", "ok"]), 0)
            self.assertEqual(check_regression.main(["answer", "bad"]), 1)
            self.assertEqual(check_regression.main(["answer", "other_judge"]), 1)
            self.assertEqual(check_regression.main(["answer", "unrecorded"]), 1)

    def test_each_set_keeps_at_most_five_quality_scores(self):
        for set_name, limits in check_regression.LIMITS.items():
            quality = [name for name, *_ in limits if name not in check_regression.ALARMS]
            self.assertLessEqual(len(quality), 5, set_name)



def routing_run(passed: dict[str, bool], route_accuracy: float, broken=()):
    items = [{"id": i, "output": None if i in broken else {"route": "sql"},
              "scores": {} if i in broken else {"route_correct": 1.0 if ok else 0.0, "kind_correct": 1.0}}
             for i, ok in passed.items()]
    return {"run_scores": {"route_accuracy": route_accuracy, "kind_accuracy": 1.0}, "items": items}


class MergeGateTests(unittest.TestCase):
    """The four checks against a baseline (2026-10-19): completeness, absolute, relative, regression."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        patches = [patch.object(check_regression, "RESULTS_DIR", self.dir),
                   patch.object(check_regression, "BASELINE_DIR", self.dir / "baselines"),
                   patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""})]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        # a and b passed three times (stable), c once: c may fail later without a regression.
        for n, c_ok in enumerate((True, False, False), 1):
            self.save(f"base-{n}", routing_run({"a": True, "b": True, "c": c_ok}, 1.0 if c_ok else 0.97))
        check_regression.make_baseline("routing", ["base-1", "base-2", "base-3"])

    def save(self, run, result):
        (self.dir / f"routing_{run}.json").write_text(json.dumps(result), encoding="utf-8")

    def gate(self, result):
        self.save("pr", result)
        rows, ok, _ = check_regression.check("routing", "pr")
        return ok, "\n".join(rows)

    def test_the_baseline_keeps_ids_means_and_the_stable_questions(self):
        baseline = check_regression.load_baseline("routing")
        self.assertEqual(baseline["ids"], ["a", "b", "c"])
        self.assertEqual(baseline["stable"], ["a", "b"])
        self.assertAlmostEqual(baseline["means"]["route_accuracy"], 0.98)

    def test_a_run_like_the_baseline_passes_all_four(self):
        ok, rows = self.gate(routing_run({"a": True, "b": True, "c": False}, 0.97))
        self.assertTrue(ok, rows)
        for check in ("완전성", "절대", "상대", "회귀"):
            self.assertIn(f"| routing | {check} |", rows)

    def test_a_missing_or_failed_question_fails_completeness(self):
        ok, rows = self.gate(routing_run({"a": True, "b": True}, 1.0))
        self.assertFalse(ok)
        self.assertIn("빠짐 1", rows)
        ok, rows = self.gate(routing_run({"a": True, "b": True, "c": True}, 1.0, broken=("c",)))
        self.assertFalse(ok)
        self.assertIn("오류 1", rows)

    def test_a_drop_beyond_the_allowed_fails_even_above_the_absolute_floor(self):
        # 0.945 is above the absolute 0.94 but more than 0.03 below the baseline's 0.98.
        ok, rows = self.gate(routing_run({"a": True, "b": True, "c": False}, 0.945))
        self.assertFalse(ok)
        self.assertIn("| routing | 상대 | route_accuracy | 0.945 | ≥ 0.95", rows)

    def test_a_stable_question_that_fails_is_a_regression(self):
        ok, rows = self.gate(routing_run({"a": True, "b": False, "c": True}, 0.97))
        self.assertFalse(ok)
        self.assertIn("실패 1 (b)", rows)

    def test_a_set_without_a_baseline_gets_the_absolute_limits_only(self):
        (self.dir / "answer_other.json").write_text(
            json.dumps({"run_scores": {"answer_correctness": 0.3}, "judge_model": "gpt-6-luna"}), encoding="utf-8")
        rows, ok, _ = check_regression.check("answer", "other")
        self.assertTrue(ok)
        self.assertNotIn("완전성", "\n".join(rows))


if __name__ == "__main__":
    unittest.main()
