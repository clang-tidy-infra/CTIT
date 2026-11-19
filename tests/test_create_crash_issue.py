import os
import sys
import tempfile
import unittest
from unittest import mock

from crash_detection import create_crash_issue


class TestMain(unittest.TestCase):
    def test_writes_output_file_without_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with open("crash-summary.md", "w") as f:
                    f.write("## Crash Summary\n")
                argv = [
                    "create_crash_issue.py",
                    "--repo",
                    "owner/repo",
                    "--run-id",
                    "1",
                    "--run-name",
                    "daily all-checks",
                    "--output-file",
                    "crash-issue.md",
                ]
                with mock.patch.object(sys, "argv", argv):
                    create_crash_issue.main()
                with open("crash-issue.md") as f:
                    body = f.read()
            finally:
                os.chdir(cwd)

        self.assertIn("Crashes detected in daily all-checks run.", body)
        self.assertIn("https://github.com/owner/repo/actions/runs/1", body)
        self.assertIn("## Crash Summary", body)


if __name__ == "__main__":
    unittest.main()
