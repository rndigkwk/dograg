import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import git_guard


def run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class UnmergedReasonTest(unittest.TestCase):
    """A local clone of a throwaway origin; no network."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        origin, self.clone = root / "origin.git", root / "clone"
        run(root, "init", "-q", "--bare", "-b", "main", str(origin))
        run(root, "clone", "-q", str(origin), str(self.clone))
        run(self.clone, "symbolic-ref", "HEAD", "refs/heads/main")  # CI git may default to master
        for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("core.autocrlf", "false")):
            run(self.clone, "config", key, value)
        (self.clone / "src").mkdir()
        (self.clone / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        run(self.clone, "add", ".")
        run(self.clone, "commit", "-q", "-m", "first")
        run(self.clone, "push", "-q", "origin", "main")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_merged_main_passes(self) -> None:
        self.assertIsNone(git_guard.unmerged_reason(self.clone))

    def test_untracked_files_do_not_block(self) -> None:
        (self.clone / "notes.txt").write_text("local\n", encoding="utf-8")
        self.assertIsNone(git_guard.unmerged_reason(self.clone))

    def test_behind_origin_main_is_refused(self) -> None:
        other = Path(self.tmp.name) / "other"
        run(Path(self.tmp.name), "clone", "-q", str(Path(self.tmp.name) / "origin.git"), str(other))
        for key, value in (("user.email", "t@example.com"), ("user.name", "t")):
            run(other, "config", key, value)
        (other / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
        run(other, "commit", "-q", "-am", "newer main")
        run(other, "push", "-q", "origin", "main")
        reason = git_guard.unmerged_reason(self.clone)
        self.assertIn("is not origin/main", reason or "")

    def test_unpushed_commit_is_refused(self) -> None:
        (self.clone / "src" / "a.py").write_text("x = 3\n", encoding="utf-8")
        run(self.clone, "commit", "-q", "-am", "local only")
        self.assertIn("is not origin/main", git_guard.unmerged_reason(self.clone) or "")

    def test_local_change_in_checked_paths_is_refused(self) -> None:
        (self.clone / "src" / "a.py").write_text("x = 4\n", encoding="utf-8")
        self.assertIn("src/a.py", git_guard.unmerged_reason(self.clone) or "")

    def test_git_failure_is_a_reason(self) -> None:
        with mock.patch.object(git_guard, "git", side_effect=subprocess.CalledProcessError(1, "git")):
            self.assertIn("could not check", git_guard.unmerged_reason(self.clone) or "")


if __name__ == "__main__":
    unittest.main()
