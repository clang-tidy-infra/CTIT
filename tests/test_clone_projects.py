import unittest
from unittest.mock import patch

from testers.clone_projects import clone_project


class TestCloneProject(unittest.TestCase):
    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.path.isdir", return_value=True)
    def test_only_checks_out_when_dir_exists(self, mock_isdir, mock_run):
        clone_project("proj", "https://example.com/proj.git", "abc123", "/dest/proj")
        mock_run.assert_called_once_with(
            ["git", "-C", "/dest/proj", "checkout", "abc123"],
            check=True,
        )

    @patch("testers.clone_projects.subprocess.run")
    @patch("testers.clone_projects.os.path.isdir", return_value=False)
    def test_clones_and_checks_out_when_dir_missing(self, mock_isdir, mock_run):
        clone_project("proj", "https://example.com/proj.git", "abc123", "/dest/proj")
        mock_run.assert_any_call(
            ["git", "clone", "https://example.com/proj.git", "/dest/proj"],
            check=True,
        )
        mock_run.assert_any_call(
            ["git", "-C", "/dest/proj", "checkout", "abc123"],
            check=True,
        )
        self.assertEqual(mock_run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
