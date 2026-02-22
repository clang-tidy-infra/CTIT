import json
import os
import tempfile
import unittest
from unittest.mock import patch

from testers.clone_projects import clone_project, clone_projects


class TestCloneProject(unittest.TestCase):
    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.path.isdir", return_value=True)
    def test_only_fetches_and_checks_out_when_dir_exists(self, mock_isdir, mock_run):
        clone_project("proj", "https://example.com/proj.git", "abc123", "/dest/proj")
        mock_run.assert_any_call(
            ["git", "-C", "/dest/proj", "fetch", "--depth", "1", "origin", "abc123"],
            check=True,
        )
        mock_run.assert_any_call(
            ["git", "-C", "/dest/proj", "checkout", "abc123"],
            check=True,
        )
        self.assertEqual(mock_run.call_count, 2)

    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.path.isdir", return_value=False)
    def test_clones_fetches_and_checks_out_when_dir_missing(self, mock_isdir, mock_run):
        clone_project("proj", "https://example.com/proj.git", "abc123", "/dest/proj")
        mock_run.assert_any_call(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--no-checkout",
                "https://example.com/proj.git",
                "/dest/proj",
            ],
            check=True,
        )
        mock_run.assert_any_call(
            ["git", "-C", "/dest/proj", "fetch", "--depth", "1", "origin", "abc123"],
            check=True,
        )
        mock_run.assert_any_call(
            ["git", "-C", "/dest/proj", "checkout", "abc123"],
            check=True,
        )
        self.assertEqual(mock_run.call_count, 3)


class TestCloneProjects(unittest.TestCase):
    @patch("testers.clone_projects.clone_project")
    def test_clones_all_projects_from_config(self, mock_clone):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = {
                "projects": {
                    "a": {"url": "https://example.com/a.git", "commit": "aaa"},
                    "b": {"url": "https://example.com/b.git", "commit": "bbb"},
                }
            }
            config_path = os.path.join(tmp_dir, "projects.json")
            with open(config_path, "w") as f:
                json.dump(config, f)

            work_dir = os.path.join(tmp_dir, "out")
            clone_projects(work_dir, config_path)

            self.assertTrue(os.path.isdir(work_dir))
            self.assertEqual(mock_clone.call_count, 2)
            mock_clone.assert_any_call(
                "a", "https://example.com/a.git", "aaa", os.path.join(work_dir, "a")
            )
            mock_clone.assert_any_call(
                "b", "https://example.com/b.git", "bbb", os.path.join(work_dir, "b")
            )

    @patch("testers.clone_projects.clone_project")
    def test_creates_work_dir(self, mock_clone):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = {"projects": {}}
            config_path = os.path.join(tmp_dir, "projects.json")
            with open(config_path, "w") as f:
                json.dump(config, f)

            work_dir = os.path.join(tmp_dir, "nested", "out")
            clone_projects(work_dir, config_path)

            self.assertTrue(os.path.isdir(work_dir))
            mock_clone.assert_not_called()


if __name__ == "__main__":
    unittest.main()
