import unittest

from langchain_core.runnables import RunnableLambda

from scripts.jev_router_shadow import (
    _CountingChatModel,
    extract_jev_route,
    summarize_predictions,
    summarize_latencies,
)


class JevShadowHelpersTest(unittest.TestCase):
    def test_latency_summary_reports_average_and_percentiles_in_ms(self):
        summary = summarize_latencies([0.01, 0.02, 0.03, 0.04])

        self.assertEqual(summary["count"], 4)
        self.assertAlmostEqual(summary["mean_ms"], 25.0)
        self.assertAlmostEqual(summary["p50_ms"], 25.0)
        self.assertAlmostEqual(summary["p95_ms"], 38.5)

    def test_extract_jev_route_reads_choice_from_system_one_response(self):
        class Answer:
            choice = "rag"
            confidence = 0.82
            probabilities = {"rag": 0.82, "sql": 0.05, "analysis": 0.08, "none": 0.05}

        class Response:
            model = "jev-1.13.0"
            usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 2})()
            answers = {"route": Answer()}

        self.assertEqual(extract_jev_route(Response()), ("rag", 0.82))

    def test_model_call_counter_remains_composable_in_langchain_pipeline(self):
        class Model:
            def with_structured_output(self, *_args, **_kwargs):
                return RunnableLambda(lambda value: {"route": value})

        counter = {"count": 0}
        chain = RunnableLambda(lambda value: value.upper()) | _CountingChatModel(
            Model(), counter
        ).with_structured_output(dict)

        result = chain.invoke("hello")

        self.assertEqual(result, {"route": "HELLO"})
        self.assertEqual(counter["count"], 1)

    def test_accuracy_keeps_failed_and_wrong_predictions_in_total(self):
        summary = summarize_predictions(
            [
                {"expected": "rag", "existing_route": "rag"},
                {"expected": "none", "existing_route": "analysis"},
                {"expected": "none", "existing_route": None},
            ],
            "existing_route",
        )

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["correct"], 1)
        self.assertEqual(summary["wrong_route_count"], 1)
        self.assertEqual(summary["unclassified_count"], 1)
        self.assertAlmostEqual(summary["accuracy"], 1 / 3)


if __name__ == "__main__":
    unittest.main()
