"""scripts/mlflow_tracking.py: where runs go and which token is used (no server, no mlflow import)."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import mlflow_tracking  # noqa: E402

KEYS = ("MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_USERNAME", "MLFLOW_TRACKING_PASSWORD")


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        saved = {key: os.environ.pop(key, None) for key in KEYS}
        self.addCleanup(lambda: [os.environ.pop(key, None) for key in KEYS]
                        + [os.environ.__setitem__(k, v) for k, v in saved.items() if v is not None])

    def test_the_dagshub_token_from_env_file_becomes_the_password(self):
        with patch("src.settings.get_setting", return_value=" token-from-env \n"):
            self.assertEqual(mlflow_tracking.configure(), mlflow_tracking.TRACKING_URI)
        self.assertEqual(os.environ["MLFLOW_TRACKING_USERNAME"], "rndigkwk")
        self.assertEqual(os.environ["MLFLOW_TRACKING_PASSWORD"], "token-from-env")

    def test_no_token_stops_before_any_request(self):
        with patch("src.settings.get_setting", return_value=None), self.assertRaises(SystemExit):
            mlflow_tracking.configure()

    def test_local_runs_stay_under_output(self):
        uri = mlflow_tracking.configure(local=True)
        self.assertTrue(uri.startswith("sqlite:///") and uri.endswith("output/mlflow.db"))
        self.assertNotIn("MLFLOW_TRACKING_PASSWORD", os.environ)


class MetricNameTests(unittest.TestCase):
    """Every comparison logs the same names, so MLflow shows the systems side by side."""

    def test_sets_and_p_values_share_one_name(self):
        useful = {"kure hybrid": {"short": 0.683, "long_useful": 0.77, "all": 0.723,
                                  "vs_app_p": {"short": 0.023, "long_useful": 0.21, "all": 0.008}}}
        self.assertEqual(mlflow_tracking.system_metrics(useful, "hybrid", "kure"), {
            "hybrid_useful3_short": 0.683, "hybrid_useful3_long": 0.77, "hybrid_useful3_all": 0.723,
            "hybrid_p_short": 0.023, "hybrid_p_long": 0.21, "hybrid_p_all": 0.008})

    def test_a_missing_system_logs_nothing(self):
        self.assertEqual(mlflow_tracking.system_metrics({}, "dense", "app"), {})


if __name__ == "__main__":
    unittest.main()
