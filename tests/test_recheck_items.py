"""scripts/recheck_items.py: a guide recheck keeps each run's graph steps (#387)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import recheck_items


def lost_guide(question, **kwargs):
    """A run whose grade dropped both guide candidates: answered, but with no guide."""
    trace = [{"step": "health_grade", "decision": "ambiguous", "candidate_ids": ["g-1", "g-2", "c-1"], "kept_ids": ["c-1"]}]
    return {"answer": "답", "decision": "ambiguous", "trace": trace,
            "evidence_rows": [{"kind": "consultation"}]}


class GuideRecheckStepsTests(unittest.TestCase):
    def test_the_steps_of_each_recheck_run_are_saved(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        results = Path(directory.name)
        (results / "guide_ci_regressed.json").write_text(json.dumps(["g06"]), encoding="utf-8")
        (results / "chroma").mkdir()
        with patch.object(recheck_items, "RESULTS_DIR", results), \
                patch.object(recheck_items, "PROJECT_DIR", results.parent), \
                patch("shutil.copytree"), patch("src.chatbot.chatbot", lost_guide), \
                patch("src.tools.care_guides.load_guides", return_value=([{"id": "g-1"}, {"id": "g-2"}], None)):
            recheck_items.main(["guide", "ci"])
        self.assertEqual(json.loads((results / "guide_ci_recheck.json").read_text(encoding="utf-8")), {"g06": [False, False]})
        steps = json.loads((results / "guide_ci_recheck_steps.json").read_text(encoding="utf-8"))
        self.assertEqual(len(steps["g06"]), 2)
        self.assertEqual(steps["g06"][0][0]["candidates"], {"guides": 2, "consultations": 1})
        self.assertEqual(steps["g06"][0][0]["kept"], {"guides": 0, "consultations": 1})


if __name__ == "__main__":
    unittest.main()
