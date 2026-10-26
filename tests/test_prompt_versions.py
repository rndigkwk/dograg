"""src/prompt_versions.py: every prompt listed, hashes of the text only, and the result-file shape."""

import ast
import re
import unittest
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src import prompt_versions

SRC = Path(__file__).resolve().parents[1] / "src"
# A module-level constant named like a prompt; HIDDEN_INSTRUCTION_PATTERNS (src/untrusted.py) is regexes.
PROMPT_NAME = re.compile(r"^[A-Z_]*(PROMPT|INSTRUCTIONS)[A-Z_]*$")
NOT_PROMPTS = {("src.untrusted", "HIDDEN_INSTRUCTION_PATTERNS"), ("src.prompt_versions", "PROMPTS")}


def prompt_constants() -> set[tuple[str, str]]:
    found = set()
    for path in SRC.rglob("*.py"):
        module = ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            found |= {(module, t.id) for t in targets if isinstance(t, ast.Name) and PROMPT_NAME.match(t.id)}
    return found - NOT_PROMPTS


class PromptVersionsTest(unittest.TestCase):
    def test_every_prompt_constant_is_listed(self):
        self.assertEqual(prompt_constants(), set(prompt_versions.PROMPTS.values()))

    def test_hashes_the_template_text(self):
        prompt = ChatPromptTemplate.from_messages([("system", "규칙 {x}"), MessagesPlaceholder("history"), ("human", "{q}")])
        text = prompt_versions.prompt_text(prompt)
        self.assertIn("규칙 {x}", text)
        self.assertIn("history", text)
        self.assertNotIn(" object at 0x", text)
        same = ChatPromptTemplate.from_messages([("system", "규칙 {x}"), MessagesPlaceholder("history"), ("human", "{q}")])
        changed = ChatPromptTemplate.from_messages([("system", "규칙 {x}!"), MessagesPlaceholder("history"), ("human", "{q}")])
        self.assertEqual(prompt_versions.short_hash(text), prompt_versions.short_hash(prompt_versions.prompt_text(same)))
        self.assertNotEqual(prompt_versions.short_hash(text), prompt_versions.short_hash(prompt_versions.prompt_text(changed)))

    def test_real_prompts_hash_their_text(self):
        import importlib

        for name, (module, attribute) in prompt_versions.PROMPTS.items():
            text = prompt_versions.prompt_text(getattr(importlib.import_module(module), attribute))
            self.assertNotIn(" object at 0x", text, name)

    def test_record_shape(self):
        record = prompt_versions.record()
        self.assertEqual(set(record["versions"]), set(prompt_versions.PROMPTS))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{8}", h) for h in record["versions"].values()))
        self.assertEqual(record["digest"], prompt_versions.digest(record["versions"]))
        moved = dict(record["versions"], router="00000000")
        self.assertNotEqual(prompt_versions.digest(moved), record["digest"])


if __name__ == "__main__":
    unittest.main()
