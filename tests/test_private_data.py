"""src/private_data.py: download the private data at the pinned revision, never mix versions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import private_data


class EnsureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        token = patch.object(private_data.settings, "get_setting", return_value="test-token")
        token.start()
        self.addCleanup(token.stop)

    def write_required(self, revision=None):
        for path in private_data.REQUIRED:
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("x", encoding="utf-8")
        if revision:
            (self.root / private_data.REVISION_MARKER).write_text(revision, encoding="utf-8")

    def test_files_of_the_pinned_revision_are_not_downloaded_again(self):
        self.write_required(private_data.REVISION)
        with patch("huggingface_hub.snapshot_download") as download:
            self.assertEqual(private_data.ensure(self.root), [])
        download.assert_not_called()

    def test_files_of_another_revision_are_replaced(self):
        # A server keeps its files across redeploys: present files may hold another model's vectors.
        self.write_required("main")
        with patch("huggingface_hub.snapshot_download") as download:
            self.assertEqual(private_data.ensure(self.root), [])
        self.assertEqual(download.call_args.kwargs["revision"], private_data.REVISION)
        self.assertEqual(private_data.downloaded_revision(self.root), private_data.REVISION)

    def test_a_failed_download_never_leaves_another_revision_in_use(self):
        self.write_required("main")
        with patch("huggingface_hub.snapshot_download", side_effect=OSError("offline")):
            self.assertEqual(private_data.ensure(self.root), [f"{private_data.REPO_ID}@{private_data.REVISION}"])

    def test_missing_files_are_reported(self):
        with patch("huggingface_hub.snapshot_download"):
            self.assertEqual(private_data.ensure(self.root), list(private_data.REQUIRED))


if __name__ == "__main__":
    unittest.main()
