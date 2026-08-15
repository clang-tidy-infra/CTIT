import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from codechecker_integration.store_logs import store_project


class TestStoreProject(unittest.TestCase):
    def test_skips_when_log_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = os.path.join(tmp, "reports")
            missing = os.path.join(tmp, "nope.log")
            with patch("codechecker_integration.store_logs.subprocess.run") as mock_run:
                ok = store_project(
                    "cppcheck",
                    missing,
                    reports,
                    "https://cc.example/Default",
                    "nightly-2026-06-07",
                    env={"HOME": tmp},
                )
            self.assertTrue(ok)
            mock_run.assert_not_called()

    def test_skips_when_log_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = os.path.join(tmp, "reports")
            log = os.path.join(tmp, "empty.log")
            open(log, "w").close()
            with patch("codechecker_integration.store_logs.subprocess.run") as mock_run:
                ok = store_project(
                    "cppcheck",
                    log,
                    reports,
                    "https://cc.example/Default",
                    "nightly-2026-06-07",
                    env={"HOME": tmp},
                )
            self.assertTrue(ok)
            mock_run.assert_not_called()

    def test_runs_converter_then_store_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = os.path.join(tmp, "reports")
            log = os.path.join(tmp, "cppcheck.log")
            with open(log, "w") as f:
                f.write("/x/y.cpp:1:1: warning: foo [bar]\n")

            calls: list[list[str]] = []

            def fake_run(cmd, env=None, check=False):
                calls.append(cmd)

                class _R:
                    returncode = 0

                return _R()

            with patch(
                "codechecker_integration.store_logs.subprocess.run",
                side_effect=fake_run,
            ):
                ok = store_project(
                    "cppcheck",
                    log,
                    reports,
                    "https://cc.example/Default",
                    "nightly-2026-06-07",
                    env={"HOME": tmp},
                )

            self.assertTrue(ok)
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], "report-converter")
            self.assertIn("-t", calls[0])
            self.assertIn("clang-tidy", calls[0])
            self.assertEqual(calls[1][0], "CodeChecker")
            self.assertIn("store", calls[1])
            self.assertIn("--name", calls[1])
            self.assertIn("cppcheck", calls[1])
            self.assertIn("--tag", calls[1])
            self.assertIn("nightly-2026-06-07", calls[1])

    def test_returns_false_on_subprocess_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = os.path.join(tmp, "reports")
            log = os.path.join(tmp, "cppcheck.log")
            with open(log, "w") as f:
                f.write("noise\n")

            def fake_run(cmd, env=None, check=False):
                raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

            with patch(
                "codechecker_integration.store_logs.subprocess.run",
                side_effect=fake_run,
            ):
                ok = store_project(
                    "cppcheck",
                    log,
                    reports,
                    "https://cc.example/Default",
                    "nightly-2026-06-07",
                    env={"HOME": tmp},
                )

            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
