import io
import os
import tempfile
import unittest
from unittest.mock import patch

from testers.generate_report import (
    Issue,
    ProjectResult,
    generate_markdown,
    generate_report,
    get_relative_path,
    parse_log_file,
    write_project_details,
    write_summary_table,
)


class TestProjectResultStatus(unittest.TestCase):
    def test_pass(self):
        r = ProjectResult(name="test")
        self.assertEqual(r.status_text, "Pass")

    def test_warnings(self):
        r = ProjectResult(name="test", warnings_count=3)
        self.assertEqual(r.status_text, "Warnings")

    def test_errors(self):
        r = ProjectResult(name="test", errors_count=1)
        self.assertEqual(r.status_text, "Fail")

    def test_crash(self):
        r = ProjectResult(name="test", has_crash=True)
        self.assertEqual(r.status_text, "CRASH")

    def test_crash_takes_priority_over_errors(self):
        r = ProjectResult(name="test", errors_count=5, has_crash=True)
        self.assertEqual(r.status_text, "CRASH")

    def test_errors_take_priority_over_warnings(self):
        r = ProjectResult(name="test", warnings_count=3, errors_count=1)
        self.assertEqual(r.status_text, "Fail")


class TestGetRelativePath(unittest.TestCase):
    def testtest_projects_dir_path(self):
        path = "/home/runner/test_projects/cppcheck/lib/token.cpp"
        self.assertEqual(get_relative_path(path, "cppcheck"), "lib/token.cpp")

    def testtest_projects_path(self):
        path = "/home/user/CTIT/test-projects/cppcheck/lib/token.cpp"
        self.assertEqual(get_relative_path(path, "cppcheck"), "lib/token.cpp")

    def test_project_name_path(self):
        path = "/home/user/poco/src/file.cpp"
        self.assertEqual(get_relative_path(path, "poco"), "src/file.cpp")

    def test_without_marker(self):
        path = "/some/other/path/file.cpp"
        self.assertEqual(get_relative_path(path, "unknown"), "file.cpp")

    def test_nested_path(self):
        path = "/root/_work/cppcheck/src/deep/nested/file.h"
        self.assertEqual(get_relative_path(path, "cppcheck"), "src/deep/nested/file.h")

    def testtest_projects_dir_takes_priority(self):
        path = "/root/test_projects/cppcheck/test-projects/cppcheck/file.cpp"
        self.assertEqual(
            get_relative_path(path, "cppcheck"),
            "test-projects/cppcheck/file.cpp",
        )


class TestParseLogFile(unittest.TestCase):
    def _write_log(self, tmp_dir, name, content):
        path = os.path.join(tmp_dir, f"{name}.log")
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_empty_log(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = self._write_log(tmp_dir, "empty", "")
            result = parse_log_file(path)
            self.assertEqual(result.name, "empty")
            self.assertEqual(result.warnings_count, 0)
            self.assertEqual(result.errors_count, 0)
            self.assertFalse(result.has_crash)
            self.assertEqual(result.issues, [])

    def test_single_warning(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = "/path/_work/proj/src/file.cpp:10:5: warning: unused variable [bugprone-unused]\n"
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 1)
            self.assertEqual(result.errors_count, 0)
            self.assertEqual(len(result.issues), 1)
            self.assertEqual(result.issues[0].severity, "warning")
            self.assertEqual(result.issues[0].line, 10)
            self.assertEqual(result.issues[0].col, 5)
            self.assertEqual(result.issues[0].check_name, "bugprone-unused")

    def test_single_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = "/path/file.cpp:20:3: error: something bad [misc-error]\n"
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 0)
            self.assertEqual(result.errors_count, 1)
            self.assertEqual(result.issues[0].severity, "error")

    def test_multiple_issues(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/a.cpp:1:1: warning: msg1 [check-a]\n"
                "/path/b.cpp:2:2: warning: msg2 [check-b]\n"
                "/path/c.cpp:3:3: error: something bad [check-c]\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 2)
            self.assertEqual(result.errors_count, 1)
            self.assertEqual(len(result.issues), 3)

    def test_crash_segfault(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = "Segmentation fault (core dumped)\n"
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertTrue(result.has_crash)

    def test_crash_stack_dump(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = "Stack dump:\n0. some frame\n"
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertTrue(result.has_crash)

    def test_context_extraction(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/file.cpp:10:5: warning: bad code [check-a]\n" "    int x = 0;\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.issues[0].context, "int x = 0;")

    def test_context_skips_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/file.cpp:10:5: warning: bad code [check-a]\n"
                "/another/path/file.cpp:20:3: warning: other [check-b]\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertIsNone(result.issues[0].context)

    def test_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "nonexistent.log")
            result = parse_log_file(path)
            self.assertEqual(result.name, "nonexistent")
            self.assertEqual(result.warnings_count, 0)

    def test_noise_lines_ignored(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "Some random output\n"
                "clang-tidy is running...\n"
                "/path/file.cpp:10:5: warning: msg [check-a]\n"
                "More noise\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 1)
            self.assertEqual(len(result.issues), 1)

    def test_deduplicates_same_location_and_check(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/proj/include/header.h:75:9: warning: use scoped_lock [modernize-use-scoped-lock]\n"
                "75 |         std::lock_guard<std::mutex> lock(m_);\n"
                "/path/proj/include/header.h:75:9: warning: use scoped_lock [modernize-use-scoped-lock]\n"
                "75 |         std::lock_guard<std::mutex> lock(m_);\n"
                "/path/proj/include/header.h:75:9: warning: use scoped_lock [modernize-use-scoped-lock]\n"
                "75 |         std::lock_guard<std::mutex> lock(m_);\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 1)
            self.assertEqual(len(result.issues), 1)

    def test_different_lines_not_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/proj/header.h:10:5: warning: msg [check-a]\n"
                "/path/proj/header.h:20:5: warning: msg [check-a]\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 2)
            self.assertEqual(len(result.issues), 2)

    def test_different_columns_not_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/proj/header.h:10:5: warning: msg [check-a]\n"
                "/path/proj/header.h:10:9: warning: msg [check-a]\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 2)
            self.assertEqual(len(result.issues), 2)

    def test_different_checks_same_location_not_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/proj/file.cpp:10:5: warning: msg1 [check-a]\n"
                "/path/proj/file.cpp:10:5: warning: msg2 [check-b]\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 2)
            self.assertEqual(len(result.issues), 2)

    def test_different_files_same_line_not_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/proj/a.h:10:5: warning: msg [check-a]\n"
                "/path/proj/b.h:10:5: warning: msg [check-a]\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(result.warnings_count, 2)
            self.assertEqual(len(result.issues), 2)

    def test_dedup_keeps_first_occurrence_context(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/proj/header.h:10:5: warning: msg [check-a]\n"
                "10 |     int x = 0;\n"
                "/path/proj/header.h:10:5: warning: msg [check-a]\n"
                "10 |     int x = 0;\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            self.assertEqual(len(result.issues), 1)
            self.assertEqual(result.issues[0].context, "10 |     int x = 0;")

    def test_dedup_mixed_warning_and_error_same_location(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = (
                "/path/proj/file.cpp:10:5: warning: msg [check-a]\n"
                "/path/proj/file.cpp:10:5: error: msg [check-a]\n"
            )
            path = self._write_log(tmp_dir, "proj", log)
            result = parse_log_file(path)
            # Same file/line/col/check — first one wins
            self.assertEqual(len(result.issues), 1)
            self.assertEqual(result.issues[0].severity, "warning")


class TestWriteSummaryTable(unittest.TestCase):
    def test_single_project_pass(self):
        f = io.StringIO()
        results = [ProjectResult(name="proj")]
        write_summary_table(f, results)
        output = f.getvalue()
        self.assertIn("| **proj** |", output)
        self.assertIn("| 0 | 0 | - |", output)

    def test_project_with_crash(self):
        f = io.StringIO()
        results = [ProjectResult(name="proj", has_crash=True)]
        write_summary_table(f, results)
        output = f.getvalue()
        self.assertIn("YES", output)

    def test_multiple_projects(self):
        f = io.StringIO()
        results = [
            ProjectResult(name="a", warnings_count=2),
            ProjectResult(name="b", errors_count=1),
        ]
        write_summary_table(f, results)
        output = f.getvalue()
        self.assertIn("| **a** |", output)
        self.assertIn("| **b** |", output)

    def test_header_present(self):
        f = io.StringIO()
        write_summary_table(f, [])
        output = f.getvalue()
        self.assertIn("Clang-Tidy Integration Test Results", output)
        self.assertIn("| Project | Status |", output)


class TestWriteProjectDetails(unittest.TestCase):
    def test_no_issues_no_crash_writes_nothing(self):
        f = io.StringIO()
        result = ProjectResult(name="proj")
        write_project_details(f, result, {})
        self.assertEqual(f.getvalue(), "")

    def test_crash_banner(self):
        f = io.StringIO()
        result = ProjectResult(name="proj", has_crash=True)
        write_project_details(f, result, {})
        output = f.getvalue()
        self.assertIn("CRASH DETECTED", output)
        self.assertIn("<details>", output)

    def test_warning_with_context(self):
        f = io.StringIO()
        issue = Issue(
            file_path="src/file.cpp",
            line=10,
            col=5,
            severity="warning",
            message="unused var",
            check_name="bugprone-unused",
            context="int x = 0;",
        )
        result = ProjectResult(name="proj", warnings_count=1, issues=[issue])
        write_project_details(f, result, {})
        output = f.getvalue()
        self.assertIn("src/file.cpp", output)
        self.assertIn("unused var", output)
        self.assertIn("`[bugprone-unused]`", output)
        self.assertIn("```cpp", output)
        self.assertIn("int x = 0;", output)

    def test_issue_without_context(self):
        f = io.StringIO()
        issue = Issue(
            file_path="file.cpp",
            line=1,
            col=1,
            severity="error",
            message="msg",
            check_name="check",
        )
        result = ProjectResult(name="proj", errors_count=1, issues=[issue])
        write_project_details(f, result, {})
        output = f.getvalue()
        self.assertNotIn("```cpp", output)

    def test_cppcheck_links(self):
        f = io.StringIO()
        issue = Issue(
            file_path="lib/token.cpp",
            line=42,
            col=3,
            severity="warning",
            message="msg",
            check_name="check",
        )
        urls = {"cppcheck": "https://github.com/danmar/cppcheck/blob/abc123"}
        result = ProjectResult(name="cppcheck", warnings_count=1, issues=[issue])
        write_project_details(f, result, urls)
        output = f.getvalue()
        self.assertIn(
            "https://github.com/danmar/cppcheck/blob/abc123/lib/token.cpp#L42",
            output,
        )

    def test_unknown_project_no_links(self):
        f = io.StringIO()
        issue = Issue(
            file_path="file.cpp",
            line=1,
            col=1,
            severity="warning",
            message="msg",
            check_name="check",
        )
        result = ProjectResult(name="unknown", warnings_count=1, issues=[issue])
        write_project_details(f, result, {})
        output = f.getvalue()
        self.assertIn("1:1", output)
        self.assertNotIn("https://", output)

    def test_groups_issues_by_file(self):
        f = io.StringIO()
        issues = [
            Issue("a.cpp", 1, 1, "warning", "m1", "c1"),
            Issue("b.cpp", 2, 2, "warning", "m2", "c2"),
            Issue("a.cpp", 3, 3, "warning", "m3", "c3"),
        ]
        result = ProjectResult(name="proj", warnings_count=3, issues=issues)
        write_project_details(f, result, {})
        output = f.getvalue()
        self.assertLess(output.index("`a.cpp`"), output.index("`b.cpp`"))


class TestGenerateMarkdown(unittest.TestCase):
    def test_generates_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = os.path.join(tmp_dir, "report.md")
            results = [ProjectResult(name="proj", warnings_count=1)]
            generate_markdown(results, output_path)
            self.assertTrue(os.path.exists(output_path))
            with open(output_path) as f:
                content = f.read()
            self.assertIn("Clang-Tidy Integration Test Results", content)

    def test_empty_results(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = os.path.join(tmp_dir, "report.md")
            generate_markdown([], output_path)
            with open(output_path) as f:
                content = f.read()
            self.assertIn("Clang-Tidy Integration Test Results", content)

    def test_full_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_content = (
                "/home/_work/cppcheck/lib/tok.cpp:10:5: warning: bad [check-a]\n"
                "    int x;\n"
                "/home/_work/cppcheck/lib/tok.cpp:20:3: error: worse [check-b]\n"
                "Segmentation fault\n"
            )
            log_path = os.path.join(tmp_dir, "cppcheck.log")
            with open(log_path, "w") as f:
                f.write(log_content)

            result = parse_log_file(log_path)
            self.assertEqual(result.warnings_count, 1)
            self.assertEqual(result.errors_count, 1)
            self.assertTrue(result.has_crash)

            urls = {"cppcheck": "https://github.com/danmar/cppcheck/blob/main"}
            output_path = os.path.join(tmp_dir, "report.md")
            generate_markdown([result], output_path, urls)
            with open(output_path) as f:
                content = f.read()
            self.assertIn("CRASH", content)
            self.assertIn("check-a", content)
            self.assertIn("check-b", content)


class TestGenerateReport(unittest.TestCase):
    def test_exits_when_log_dir_missing(self):
        with self.assertRaises(SystemExit) as ctx:
            generate_report("/nonexistent/logs", "out.md")
        self.assertEqual(ctx.exception.code, 1)

    def test_exits_when_no_log_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(SystemExit) as ctx:
                generate_report(tmp_dir, "out.md")
            self.assertEqual(ctx.exception.code, 0)

    @patch("testers.generate_report.load_projects", side_effect=OSError)
    def test_generates_report_without_config(self, mock_load):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = os.path.join(tmp_dir, "proj.log")
            with open(log_path, "w") as f:
                f.write("/path/file.cpp:1:1: warning: msg [check]\n")

            output_path = os.path.join(tmp_dir, "report.md")
            generate_report(tmp_dir, output_path)

            self.assertTrue(os.path.exists(output_path))
            with open(output_path) as f:
                content = f.read()
            self.assertIn("Clang-Tidy Integration Test Results", content)
            self.assertIn("check", content)

    def test_generates_report_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = os.path.join(tmp_dir, "proj.log")
            with open(log_path, "w") as f:
                f.write("/path/proj/src/a.cpp:10:5: warning: bad [check-a]\n")

            output_path = os.path.join(tmp_dir, "report.md")
            generate_report(tmp_dir, output_path)

            with open(output_path) as f:
                content = f.read()
            self.assertIn("| **proj** |", content)
            self.assertIn("check-a", content)


if __name__ == "__main__":
    unittest.main()
