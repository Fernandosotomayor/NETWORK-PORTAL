from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from app.services.git_history import (
    get_file_diff,
    get_file_history,
    get_recent_changes,
)


class GitHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        # Create a temporary directory for the mock git repository
        self.test_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.test_dir.name).resolve()

        # Initialize git repo
        self._run_git(["init"])
        self._run_git(["config", "user.name", "Test Author"])
        self._run_git(["config", "user.email", "test@example.com"])
        self._run_git(["config", "commit.gpgsign", "false"])

        # Create first commit
        self.file_path = self.repo_path / "SW-1.cfg"
        self.file_path.write_text("hostname SW-1\ninterface gi1\n description Trunk\n", encoding="utf-8")
        self._run_git(["add", "SW-1.cfg"])
        self._run_git(["commit", "-m", "Initial configuration"])

        # Create second commit (modify file)
        self.file_path.write_text("hostname SW-1_New\ninterface gi1\n description Link_to_Core\n", encoding="utf-8")
        self._run_git(["add", "SW-1.cfg"])
        self._run_git(["commit", "-m", "Update hostname and port desc"])

    def tearDown(self) -> None:
        self.test_dir.cleanup()

    def _run_git(self, args: list[str]) -> str:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout

    def test_get_file_history(self) -> None:
        history = get_file_history(self.repo_path, "SW-1.cfg")
        self.assertEqual(len(history), 2)

        # Newest commit first
        self.assertEqual(history[0].message, "Update hostname and port desc")
        self.assertEqual(history[0].filename, "SW-1.cfg")
        self.assertEqual(history[0].author, "Test Author")

        self.assertEqual(history[1].message, "Initial configuration")
        self.assertEqual(history[1].filename, "SW-1.cfg")
        self.assertTrue(history[0].commit_hash)

    def test_get_file_diff(self) -> None:
        history = get_file_history(self.repo_path, "SW-1.cfg")
        latest_commit = history[0].commit_hash

        diff_content = get_file_diff(self.repo_path, "SW-1.cfg", latest_commit)
        self.assertIn("-hostname SW-1", diff_content)
        self.assertIn("+hostname SW-1_New", diff_content)
        self.assertIn("- description Trunk", diff_content)
        self.assertIn("+ description Link_to_Core", diff_content)

    def test_get_recent_changes(self) -> None:
        changes = get_recent_changes(self.repo_path)
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0].message, "Update hostname and port desc")
        self.assertEqual(changes[0].filename, "SW-1.cfg")
