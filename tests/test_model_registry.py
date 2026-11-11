"""scripts/model_registry.py: the embedding gate, the pointer match and the code's model (2026-11-11)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import model_registry


def report(short=(9, 2), short2=(2, 2), long=(0.82, 0.85)):
    return {
        "short_useful_vs_b": {"cand": {"gained": short[0], "lost": short[1]}},
        "short2_useful_vs_b": {"cand": {"gained": short2[0], "lost": short2[1]}},
        "long_useful": {"cand": {"useful@3": long[0]}, "b": {"useful@3": long[1]}},
    }


class GateTests(unittest.TestCase):
    def test_exact_mcnemar(self):
        self.assertAlmostEqual(model_registry.mcnemar(9, 2), 0.0654, places=4)  # GIST holdout, documented
        self.assertAlmostEqual(model_registry.mcnemar(11, 4), 0.1185, places=4)  # holdout + holdout2: 0.119
        self.assertEqual(model_registry.mcnemar(0, 0), 1.0)

    def test_gist_e3_fails_as_decided_on_2026_11_09(self):
        result = model_registry.gate(report(), "cand")
        self.assertEqual((result["short_gained"], result["short_lost"]), (11, 4))
        self.assertFalse(result["short_p_below_limit"])
        self.assertFalse(result["long_not_below_reference"])
        self.assertFalse(result["passed"])

    def test_passes_only_when_all_three_hold(self):
        self.assertTrue(model_registry.gate(report(short=(15, 2), short2=(5, 1), long=(0.85, 0.85)), "cand")["passed"])
        self.assertFalse(model_registry.gate(report(short=(15, 2), short2=(5, 1), long=(0.84, 0.85)), "cand")["passed"])

    def test_report_without_the_candidate_is_an_error(self):
        with self.assertRaises(SystemExit):
            model_registry.gate(report(), "other")


class PointerTests(unittest.TestCase):
    def test_the_code_ships_a_pinned_model(self):
        repo, revision = model_registry.app_model()
        self.assertTrue(repo.startswith("blanden77/"))
        self.assertRegex(revision, r"^[0-9a-f]{40}$")

    def test_a_checkpoint_in_a_subfolder_is_not_what_the_app_loads(self):
        tags = {"hf_repo": "r", "hf_revision": "x"}
        self.assertTrue(model_registry.matches(tags, "r", "x"))
        self.assertFalse(model_registry.matches({**tags, "subfolder": "gist-s13-e3"}, "r", "x"))
        self.assertFalse(model_registry.matches(tags, "r", "y"))


if __name__ == "__main__":
    unittest.main()
