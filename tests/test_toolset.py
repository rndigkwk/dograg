import re
import unittest
from pathlib import Path
from unittest.mock import patch

from src.tools import health, router
from src.tools.toolset import TOOL_SOURCES, TOOLS

GRAPH_SOURCE = Path(__file__).resolve().parents[1] / "src" / "chat_graph.py"


class ToolsetTests(unittest.TestCase):
    def test_every_name_the_graph_calls_is_provided(self):
        used = set(re.findall(r"(?<![\w.])tools\.(\w+)",GRAPH_SOURCE.read_text(encoding="utf-8")))
        provided = {name for names in TOOL_SOURCES.values() for name in names}
        self.assertEqual(used - provided, set())
        self.assertEqual(provided - used, set(), "the toolset lists names the graph never calls")

    def test_patching_a_tool_module_reaches_the_toolset(self):
        with patch.object(health, "retrieve_health", return_value=["patched"]):
            self.assertEqual(TOOLS.retrieve_health("q"), ["patched"])
        with patch.object(router, "classify_question", return_value="sql"):
            self.assertEqual(TOOLS.classify_question("q"), "sql")

    def test_unknown_names_fail_loudly(self):
        with self.assertRaises(AttributeError):
            TOOLS.not_a_tool  # noqa: B018


if __name__ == "__main__":
    unittest.main()
