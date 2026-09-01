import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from testers.clang_tests import (
    CRASH,
    ERROR,
    PASS,
    build_clang_tidy_command,
    classify_result,
    compile_args_for_file,
    discover_test_files,
    log_file_for_test,
    run_clang_test_file,
    run_clang_tests,
    write_markdown_report,
)


class TestDiscoverTestFiles(unittest.TestCase):
    def test_discovers_supported_clang_tests(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = [
                "clang/test/Sema/a.c",
                "clang/test/Sema/b.cpp",
                "clang-tools-extra/test/clang-tidy/c.cxx",
                "clang/test/Sema/skip.h",
            ]
            for rel_path in paths:
                full_path = os.path.join(tmp_dir, rel_path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write("int x;\n")

            files = [
                os.path.relpath(path, tmp_dir) for path in discover_test_files(tmp_dir)
            ]

            self.assertEqual(
                files,
                [
                    "clang-tools-extra/test/clang-tidy/c.cxx",
                    "clang/test/Sema/a.c",
                    "clang/test/Sema/b.cpp",
                ],
            )


class TestCommandBuilding(unittest.TestCase):
    def test_c_file_uses_c_args(self):
        args = compile_args_for_file("/tmp/llvm/clang/test/a.c", "/tmp/llvm")
        self.assertIn("c", args)
        self.assertIn("-std=c17", args)

    def test_cpp_file_uses_cpp_args(self):
        args = compile_args_for_file("/tmp/llvm/clang/test/a.cpp", "/tmp/llvm")
        self.assertIn("c++", args)
        self.assertIn("-std=c++20", args)

    def test_build_command_with_config_and_extra_args(self):
        cmd = build_clang_tidy_command(
            "/bin/clang-tidy",
            "/tmp/llvm/clang/test/a.cpp",
            "bugprone-test",
            '{"CheckOptions":{}}',
            "/tmp/llvm",
            ["-DFOO=1"],
        )

        self.assertEqual(cmd[0], "/bin/clang-tidy")
        self.assertIn("-checks=-*,bugprone-test", cmd)
        self.assertIn('-config={"CheckOptions":{}}', cmd)
        self.assertIn("--", cmd)
        self.assertIn("-DFOO=1", cmd)

    def test_log_file_for_test_is_stable(self):
        log_file = log_file_for_test(
            "/tmp/llvm/clang/test/Sema/a.cpp",
            "/tmp/llvm",
            "/logs",
        )
        self.assertEqual(log_file, "/logs/clang__test__Sema__a.cpp.log")


class TestClassification(unittest.TestCase):
    def test_crash_marker_wins(self):
        status, reason = classify_result(1, "Stack dump:\nframe")
        self.assertEqual(status, CRASH)
        self.assertEqual(reason, "Stack dump:")

    def test_negative_returncode_is_crash(self):
        status, reason = classify_result(-11, "")
        self.assertEqual(status, CRASH)
        self.assertEqual(reason, "terminated by signal 11")

    def test_nonzero_without_crash_is_error(self):
        status, reason = classify_result(1, "file.cpp:1:1: error: broken\n")
        self.assertEqual(status, ERROR)
        self.assertIn("status 1", reason)

    def test_zero_returncode_is_pass_even_with_warnings(self):
        status, reason = classify_result(0, "file.cpp:1:1: warning: noisy [check]\n")
        self.assertEqual(status, PASS)
        self.assertEqual(reason, "completed")


class TestRunClangTestFile(unittest.TestCase):
    @patch("testers.clang_tests.subprocess.run")
    def test_runs_file_and_writes_log(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="warning only\n")
        with tempfile.TemporaryDirectory() as tmp_dir:
            llvm_dir = os.path.join(tmp_dir, "llvm")
            log_dir = os.path.join(tmp_dir, "logs")
            file_path = os.path.join(llvm_dir, "clang/test/a.cpp")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write("int x;\n")

            result = run_clang_test_file(
                file_path,
                "check",
                "/bin/clang-tidy",
                llvm_dir,
                log_dir,
            )

            self.assertEqual(result.file_path, "clang/test/a.cpp")
            self.assertEqual(result.status, PASS)
            self.assertTrue(os.path.exists(result.log_file))
            with open(result.log_file) as f:
                content = f.read()
            self.assertIn("/bin/clang-tidy", content)
            self.assertIn("warning only", content)

    @patch("testers.clang_tests.subprocess.run")
    def test_timeout_is_crash(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["clang-tidy"],
            timeout=7,
            output="partial output",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            llvm_dir = os.path.join(tmp_dir, "llvm")
            log_dir = os.path.join(tmp_dir, "logs")
            file_path = os.path.join(llvm_dir, "clang/test/a.cpp")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write("int x;\n")

            result = run_clang_test_file(
                file_path,
                "check",
                "/bin/clang-tidy",
                llvm_dir,
                log_dir,
                timeout=7,
            )

            self.assertEqual(result.status, CRASH)
            self.assertEqual(result.reason, "timeout")
            with open(result.log_file) as f:
                self.assertIn("Timed out after 7 seconds", f.read())


class TestMarkdownReport(unittest.TestCase):
    def test_writes_grouped_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = os.path.join(tmp_dir, "clang-tests.md")
            write_markdown_report(
                [
                    SimpleNamespace(
                        file_path="a.cpp",
                        status=PASS,
                        returncode=0,
                        reason="completed",
                        log_file="logs/a.log",
                    ),
                    SimpleNamespace(
                        file_path="b.cpp",
                        status=ERROR,
                        returncode=1,
                        reason="clang-tidy exited with status 1",
                        log_file="logs/b.log",
                    ),
                    SimpleNamespace(
                        file_path="c.cpp",
                        status=CRASH,
                        returncode=None,
                        reason="timeout",
                        log_file="logs/c.log",
                    ),
                ],
                output,
            )

            with open(output) as f:
                content = f.read()
            self.assertIn("### Clang Test Crashes", content)
            self.assertIn("**Summary**: 1 CRASH out of 3 total files.", content)
            self.assertIn("| File | Return Code |", content)
            self.assertIn("| `c.cpp` | - |", content)
            self.assertIn("c.cpp", content)
            self.assertNotIn("Reason", content)
            self.assertNotIn("Log", content)
            self.assertNotIn("timeout", content)
            self.assertNotIn("logs/c.log", content)
            self.assertNotIn("a.cpp", content)
            self.assertNotIn("b.cpp", content)

    def test_writes_no_crashes_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = os.path.join(tmp_dir, "clang-tests.md")
            write_markdown_report(
                [
                    SimpleNamespace(
                        file_path="a.cpp",
                        status=PASS,
                        returncode=0,
                        reason="completed",
                        log_file="logs/a.log",
                    ),
                ],
                output,
            )

            with open(output) as f:
                content = f.read()
            self.assertIn("**Summary**: 0 CRASH out of 1 total files.", content)
            self.assertIn("_No crashes detected._", content)
            self.assertNotIn("a.cpp", content)


class TestRunClangTests(unittest.TestCase):
    @patch("testers.clang_tests.write_markdown_report")
    @patch("testers.clang_tests._run_files", return_value=[])
    @patch("testers.clang_tests.discover_test_files", return_value=[])
    def test_runs_even_when_no_files(self, mock_discover, mock_run, mock_write):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ct_bin = os.path.join(tmp_dir, "clang-tidy")
            llvm_dir = os.path.join(tmp_dir, "llvm")
            os.makedirs(llvm_dir)
            with open(ct_bin, "w") as f:
                f.write("")

            output = os.path.join(tmp_dir, "clang-tests.md")
            run_clang_tests("check", ct_bin, llvm_dir=llvm_dir, output=output)

            mock_discover.assert_called_once_with(llvm_dir)
            mock_run.assert_called_once()
            mock_write.assert_called_once()


if __name__ == "__main__":
    unittest.main()
