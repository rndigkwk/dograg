"""scripts/compare_nemo_guardrails.py: how a layer's blocks are counted (no model, no NeMo)."""

import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

import compare_nemo_guardrails as nemo


class SummaryTests(unittest.TestCase):
    def test_a_block_on_a_fair_question_is_harmful(self):
        by_id = {"inj": {"category": "injection"}, "off": {"category": "off_scope"},
                 "cri": {"category": "crisis"}, "ind": {"category": "indirect", "notes": [{"days_ago": 1, "text": "x"}]}}
        app = {i: {"ok": True} for i in by_id}
        entry = {"verdicts": {"inj": True, "off": True, "cri": True, "ind": False}, "seconds": [0.1, 0.2, 0.3, 0.4]}
        summary = nemo.summarize(entry, by_id, app, "nemo_input")
        self.assertEqual(summary["attacks_blocked"], "1/2")
        self.assertEqual(summary["off_scope_blocked"], "1/1")
        self.assertEqual(summary["harmful_blocks"], ["cri"])
        self.assertEqual(summary["attacks_out_of_reach"], ["ind"])  # an input rail never reads the notes
        self.assertEqual(summary["seconds_p50"], 0.3)

    def test_the_input_rail_reads_the_earlier_turns(self):
        item = {"question": "지금 질문", "history": [{"role": "user", "content": "앞 질문"}, {"role": "assistant", "content": "답"}]}
        self.assertEqual([m["role"] for m in nemo.user_messages(item)], ["user", "assistant", "user"])
        self.assertEqual(nemo.flat_user_text(item), "앞 질문\n지금 질문")


if __name__ == "__main__":
    unittest.main()
