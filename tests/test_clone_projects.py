import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from testers.clone_projects import clone_project, clone_projects
from testers.config import Project


def _git_calls(mock_run: MagicMock) -> list[list[str]]:
    return [call.args[0] for call in mock_run.call_args_list]


def _completed(stdout: str = "") -> MagicMock:
    return MagicMock(returncode=0, stdout=stdout)


class TestCloneProject(unittest.TestCase):
    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.path.isdir", return_value=True)
    def test_skips_commit_already_checked_out(self, mock_isdir, mock_run):
        mock_run.return_value = _completed("abc123\n")
        clone_project("https://example.com/proj.git", "abc123", "/dest/proj")
        self.assertEqual(
            _git_calls(mock_run), [["git", "-C", "/dest/proj", "rev-parse", "HEAD"]]
        )

    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.path.isdir", return_value=True)
    def test_fetches_and_checks_out_other_commit(self, mock_isdir, mock_run):
        mock_run.return_value = _completed("old456\n")
        clone_project("https://example.com/proj.git", "abc123", "/dest/proj")
        self.assertEqual(
            _git_calls(mock_run)[1:],
            [
                [
                    "git",
                    "-C",
                    "/dest/proj",
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    "abc123",
                ],
                [
                    "git",
                    "-C",
                    "/dest/proj",
                    "-c",
                    "advice.detachedHead=false",
                    "checkout",
                    "abc123",
                ],
            ],
        )

    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.makedirs")
    @patch("testers.clone_projects.os.path.isdir", return_value=False)
    def test_fetches_only_the_commit_when_dir_missing(
        self, mock_isdir, mock_makedirs, mock_run
    ):
        mock_run.return_value = _completed()
        clone_project("https://example.com/proj.git", "abc123", "/dest/proj")
        mock_makedirs.assert_called_once_with("/dest/proj")
        self.assertEqual(
            _git_calls(mock_run),
            [
                ["git", "-C", "/dest/proj", "init", "--quiet"],
                [
                    "git",
                    "-C",
                    "/dest/proj",
                    "remote",
                    "add",
                    "origin",
                    "https://example.com/proj.git",
                ],
                [
                    "git",
                    "-C",
                    "/dest/proj",
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    "abc123",
                ],
                [
                    "git",
                    "-C",
                    "/dest/proj",
                    "-c",
                    "advice.detachedHead=false",
                    "checkout",
                    "abc123",
                ],
            ],
        )

    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.makedirs")
    @patch("testers.clone_projects.os.path.isdir", return_value=False)
    def test_sparse_checkout_downloads_only_matching_files(
        self, mock_isdir, mock_makedirs, mock_run
    ):
        mock_run.return_value = _completed()
        clone_project(
            "https://example.com/proj.git", "abc123", "/dest/proj", ["/src/", "!/test/"]
        )
        calls = _git_calls(mock_run)
        self.assertIn(
            [
                "git",
                "-C",
                "/dest/proj",
                "sparse-checkout",
                "set",
                "--no-cone",
                "/src/",
                "!/test/",
            ],
            calls,
        )
        self.assertIn(
            [
                "git",
                "-C",
                "/dest/proj",
                "fetch",
                "--depth",
                "1",
                "--filter=blob:none",
                "origin",
                "abc123",
            ],
            calls,
        )

    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.path.isdir", return_value=True)
    def test_failure_raises_with_git_output(self, mock_isdir, mock_run):
        mock_run.side_effect = [
            _completed("old456\n"),
            subprocess.CalledProcessError(128, ["git"], output="fatal: remote error"),
        ]
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            clone_project("https://example.com/proj.git", "abc123", "/dest/proj")
        self.assertIn("fatal: remote error", ctx.exception.output)


class TestCloneProjects(unittest.TestCase):
    def _write_config(self, tmp_dir: str, projects: dict) -> str:
        config_path = os.path.join(tmp_dir, "projects.json")
        with open(config_path, "w") as f:
            json.dump({"projects": projects}, f)
        return config_path

    @patch("testers.clone_projects.clone_project", return_value="")
    def test_clones_all_projects_from_config(self, mock_clone):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = self._write_config(
                tmp_dir,
                {
                    "a": {"url": "https://example.com/a.git", "commit": "aaa"},
                    "b": {
                        "url": "https://example.com/b.git",
                        "commit": "bbb",
                        "sparse_checkout": ["/src/"],
                    },
                },
            )

            work_dir = os.path.join(tmp_dir, "out")
            clone_projects(work_dir, config_path)

            self.assertTrue(os.path.isdir(work_dir))
            self.assertEqual(mock_clone.call_count, 2)
            mock_clone.assert_any_call(
                "https://example.com/a.git", "aaa", os.path.join(work_dir, "a"), []
            )
            mock_clone.assert_any_call(
                "https://example.com/b.git",
                "bbb",
                os.path.join(work_dir, "b"),
                ["/src/"],
            )

    @patch("testers.clone_projects.clone_project")
    def test_failed_clone_raises(self, mock_clone):
        mock_clone.side_effect = subprocess.CalledProcessError(1, ["git"], "boom")
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = self._write_config(
                tmp_dir, {"a": {"url": "https://example.com/a.git", "commit": "aaa"}}
            )
            with self.assertRaises(subprocess.CalledProcessError):
                clone_projects(os.path.join(tmp_dir, "out"), config_path)

    @patch("testers.clone_projects.clone_project")
    def test_creates_work_dir(self, mock_clone):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = self._write_config(tmp_dir, {})

            work_dir = os.path.join(tmp_dir, "nested", "out")
            clone_projects(work_dir, config_path)

            self.assertTrue(os.path.isdir(work_dir))
            mock_clone.assert_not_called()


class TestProjectSparseCheckout(unittest.TestCase):
    def test_defaults_to_whole_tree(self):
        project = Project(name="p", url="https://example.com/p.git", commit="abc")
        self.assertEqual(project.sparse_checkout, [])


if __name__ == "__main__":
    unittest.main()
