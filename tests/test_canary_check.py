"""scripts/canary_check.py: the checks a new API revision passes before it gets traffic."""

import io
import json
import sys
import threading
import unittest
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import canary_check

from src import data_gaps

COMMIT = "abc1234def"


def sse(*events):
    return "".join(f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for kind, data in events)


class FakeApi(BaseHTTPRequestHandler):
    """A deployed API: `answers` maps a question to its event stream; `commit` and `tables` as served."""

    commit = COMMIT
    tables = 200
    answers: ClassVar[dict] = {}

    def log_message(self, *args):
        pass

    def _send(self, status, body, kind="application/json"):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, json.dumps({"status": "ok", "commit": self.commit}))
        else:
            self._send(self.tables, "[]")

    def do_POST(self):
        question = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["question"]
        self.server.agents.append(self.headers["User-Agent"])
        self._send(200, self.answers.get(question, ""), "text/event-stream")


GOOD = {
    canary_check.DATE_QUESTION: sse(("result", {"route": "none", "answer": "오늘은 10월 20일입니다."})),
    canary_check.HEALTH_QUESTION: sse(("step", {"message": "찾는 중"}), ("result", {"route": "rag", "answer": "설사가…"})),
}


class CanaryCheckTests(unittest.TestCase):
    def serve(self, **overrides):
        handler = type("Api", (FakeApi,), {"answers": GOOD, **overrides})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.agents = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.server = server
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_a_good_revision_passes_every_check(self):
        lines = list(canary_check.run(self.serve(), COMMIT, sleep=lambda s: None))
        self.assertEqual(len(lines), 4)
        self.assertTrue(all(data_gaps.CHECK_AGENT in agent for agent in self.server.agents))

    def test_the_old_revision_answering_fails(self):
        with self.assertRaisesRegex(canary_check.CheckFailed, "did not report"):
            list(canary_check.run(self.serve(commit="old0000"), COMMIT, sleep=lambda s: None))

    def test_a_missing_table_fails(self):
        with self.assertRaisesRegex(canary_check.CheckFailed, "answered 500"):
            list(canary_check.run(self.serve(tables=500), COMMIT, sleep=lambda s: None))

    def test_a_broken_chat_fails(self):
        broken = {**GOOD, canary_check.HEALTH_QUESTION: sse(("error", {"message": "문제가 생겼습니다"}))}
        with self.assertRaisesRegex(canary_check.CheckFailed, "no answer"):
            list(canary_check.run(self.serve(answers=broken), COMMIT, sleep=lambda s: None))

    def test_the_quota_notice_is_not_an_answer(self):
        degraded = {**GOOD, canary_check.HEALTH_QUESTION: sse(("result", {"route": "rag", "answer": "한도", "degraded": True}))}
        with self.assertRaisesRegex(canary_check.CheckFailed, "quota notice"):
            list(canary_check.run(self.serve(answers=degraded), COMMIT, sleep=lambda s: None))

    def test_the_checks_that_passed_print_before_a_failure(self):
        """The drill's log showed only the FAIL line: the passed checks printed after run() returned."""
        broken = {**GOOD, canary_check.HEALTH_QUESTION: sse(("error", {"message": "문제가 생겼습니다"}))}
        url = self.serve(answers=broken)
        out = io.StringIO()
        with redirect_stdout(out), patch.object(canary_check.time, "sleep"):
            code = canary_check.main([url, "--expect-commit", COMMIT])
        self.assertEqual(code, 1)
        self.assertEqual([line[:4] for line in out.getvalue().splitlines()], ["ok  ", "ok  ", "ok  ", "FAIL"])

    def test_the_outage_drill_wants_the_local_search(self):
        url = self.serve()
        with self.assertRaisesRegex(canary_check.CheckFailed, "not 'local'"):
            list(canary_check.run(url, COMMIT, sleep=lambda s: None, search="local"))
        local = {**GOOD, canary_check.HEALTH_QUESTION: sse(("result", {"route": "rag", "answer": "설사", "search": "local"}))}
        lines = list(canary_check.run(self.serve(answers=local), COMMIT, sleep=lambda s: None, search="local"))
        self.assertIn("search local", lines[-1])

    def test_the_trace_id_is_printed_to_find_the_run(self):
        traced = {**GOOD, canary_check.HEALTH_QUESTION: sse(("result", {"route": "rag", "answer": "설사", "trace_id": "ab12"}))}
        lines = list(canary_check.run(self.serve(answers=traced), COMMIT, sleep=lambda s: None))
        self.assertTrue(lines[-1].endswith(", trace ab12)"), lines[-1])

    def test_each_run_asks_as_a_new_browser(self):
        self.assertRegex(canary_check.CLIENT, r"^[0-9a-f]{32}$")
        self.assertNotEqual(canary_check.CLIENT, "c0ffee00c0ffee00c0ffee00c0ffee00")

    def test_the_check_agent_is_the_projects(self):
        self.assertEqual(canary_check.CHECK_AGENT, data_gaps.CHECK_AGENT)


class WorkflowTests(unittest.TestCase):
    def test_a_failed_check_fails_the_deploy_step(self):
        """The check's output goes through tee; without pipefail the step would pass on a failed check
        and the broken candidate would be promoted (found after the first canary deploy, 2026-10-20)."""
        import yaml

        workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy-cloud-run.yml"
        steps = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["deploy"]["steps"]
        check = next(step for step in steps if "canary_check.py" in step.get("run", ""))
        script = check["run"]
        self.assertIn("set -o pipefail", script)
        self.assertLess(script.index("set -o pipefail"), script.index("canary_check.py"))

    def test_a_drill_candidate_is_never_promoted(self):
        import yaml

        workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "deploy-cloud-run.yml"
        steps = {step.get("name"): step for step in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["deploy"]["steps"]}
        for name in ("Promote the API candidate", "Check the deployed API"):
            self.assertEqual(steps[name]["if"], "${{ (inputs.fault || 'none') == 'none' }}")


class FaultInjectionTests(unittest.TestCase):
    def test_a_revision_with_the_chat_fault_answers_nothing(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient

        from api import main
        from src import settings

        real = settings.get_setting
        with patch.object(settings, "get_setting", side_effect=lambda name: "chat" if name == "RAGDOG_FAULT" else real(name)):
            response = TestClient(main.create_app()).post("/chat", json={"question": "기침해요"},
                                                          headers={"X-RagDog-Client": "0" * 32})
        self.assertIn("event: error", response.text)
        self.assertNotIn("event: result", response.text)

    def test_the_supabase_fault_fails_every_connection(self):
        import psycopg

        from src import settings, supabase_store

        real = settings.get_setting
        with patch.object(settings, "get_setting", side_effect=lambda name: "supabase" if name == "RAGDOG_FAULT" else real(name)),                 self.assertRaisesRegex(psycopg.OperationalError, "injected outage"):
            supabase_store.connector("postgresql://nowhere.invalid/db")()

    def test_the_supabase_fault_answers_from_the_local_search(self):
        """The searches go through the fallback wrappers: with the fault the local store answers and
        the breaker opens, which the chat result reports as "search": "local"."""
        from src import settings, supabase_store

        class Local:
            def search(self, query, top_k, where=None):
                return ["local"]

        class Primary:
            def search(self, query, top_k, where=None):
                supabase_store.connector("postgresql://nowhere.invalid/db")()

        real = settings.get_setting
        breaker = supabase_store.Breaker()
        index = supabase_store.FallbackIndex(Primary(), Local, breaker)
        with patch.object(settings, "get_setting", side_effect=lambda name: "supabase" if name == "RAGDOG_FAULT" else real(name)):
            self.assertEqual(index.search("설사", 3), ["local"])
        self.assertTrue(breaker.open)


if __name__ == "__main__":
    unittest.main()
