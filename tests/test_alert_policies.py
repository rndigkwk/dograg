"""scripts/gcp/alert_policies.json: the alerts match lines the app really logs."""

import json
import re
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
POLICIES = json.loads((PROJECT_DIR / "scripts" / "gcp" / "alert_policies.json").read_text(encoding="utf-8"))["policies"]
CODE = "\n".join(path.read_text(encoding="utf-8") for folder in ("src", "api", "team")
                 for path in (PROJECT_DIR / folder).rglob("*.py"))


FIELD_VALUES = ("cloud_run_revision", "ragdog-api", "ragdog")


def phrases(filter_text: str) -> list[str]:
    """The quoted log phrases of a filter (not the field values such as the service names)."""
    return [phrase for phrase in re.findall(r'"([^"]+)"', filter_text) if phrase not in FIELD_VALUES]


class AlertPolicyTests(unittest.TestCase):
    def test_every_phrase_is_logged_by_the_app(self):
        """Renaming a log message would silence its alert without anyone noticing."""
        for policy in POLICIES:
            found = phrases(policy["filter"])
            self.assertTrue(found, policy["displayName"])
            for phrase in found:
                if phrase == "insufficient_quota":  # the provider's error code, in the logged exception
                    self.assertIn(phrase, (PROJECT_DIR / "src" / "model_outage.py").read_text(encoding="utf-8"))
                    continue
                self.assertIn(phrase, CODE, f"{policy['displayName']}: {phrase!r} is not logged anywhere")

    def test_each_policy_is_complete_and_named_once(self):
        names = [policy["displayName"] for policy in POLICIES]
        self.assertEqual(len(names), len(set(names)))
        for policy in POLICIES:
            self.assertTrue(policy["documentation"].strip())
            self.assertIn('resource.type="cloud_run_revision"', policy["filter"])


if __name__ == "__main__":
    unittest.main()
