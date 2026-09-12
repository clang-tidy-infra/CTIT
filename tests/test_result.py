import json
import os
import tempfile
import unittest

from testers.result import create_result, write_result


class TestResult(unittest.TestCase):
    def test_writes_public_run_result(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs = os.path.join(tmp_dir, "logs")
            os.mkdir(logs)
            with open(os.path.join(logs, "demo.log"), "w") as stream:
                stream.write(
                    "/work/test_projects/demo/a.cpp:7:3: warning: bad move [check-a]\n"
                    "CTIT analysis elapsed seconds: 1.250000\n"
                )
            report = os.path.join(tmp_dir, "report.md")
            with open(report, "w") as stream:
                stream.write(
                    "| # | Project | Verdict | Rationale | Location |\n"
                    "| 1 | demo | TP | Real issue. | a.cpp:7 |\n"
                )

            result = create_result(
                log_dir=logs,
                report_path=report,
                github_run_id="42",
                github_run_attempt=2,
                pr_url="https://github.com/llvm/llvm-project/pull/123",
                llvm_revision="base+patch",
                check_name="check-a",
                check_config='{"CheckOptions": {"check-a.Option": "x"}}',
                runner_arch="ARM64",
                started_at="2026-09-12T01:00:00Z",
                finished_at="2026-09-12T01:01:00Z",
                duration_seconds=60.0,
                status="COMPLETED",
                artifact_url="https://example.test/artifact",
            )
            output = os.path.join(tmp_dir, "results", "run.json")
            write_result(result, output)

            with open(output) as stream:
                saved = json.load(stream)
            self.assertEqual(saved["github_run_id"], 42)
            self.assertEqual(saved["pr_number"], 123)
            self.assertEqual(saved["project_runs"][0]["duration_seconds"], 1.25)
            diagnostic = saved["project_runs"][0]["diagnostics"][0]
            self.assertEqual(diagnostic["message"], "bad move")
            self.assertEqual(diagnostic["verdict"], "TP")
            self.assertIsNone(saved["baseline"])

    def test_includes_optional_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs = os.path.join(tmp_dir, "logs")
            baseline_logs = os.path.join(logs, "baseline")
            os.makedirs(baseline_logs)
            for directory, message in (
                (logs, "patched warning"),
                (baseline_logs, "baseline warning"),
            ):
                with open(os.path.join(directory, "demo.log"), "w") as stream:
                    stream.write(
                        f"/work/test_projects/demo/a.cpp:7:3: warning: {message} [check-a]\n"
                    )

            result = create_result(
                log_dir=logs,
                report_path=None,
                github_run_id="42",
                github_run_attempt=1,
                pr_url="https://github.com/llvm/llvm-project/pull/123",
                llvm_revision="base+patch",
                check_name="check-a",
                check_config="{}",
                runner_arch="X64",
                started_at="2026-09-12T01:00:00Z",
                finished_at="2026-09-12T01:01:00Z",
                duration_seconds=60.0,
                status="COMPLETED",
                artifact_url=None,
                baseline_revision="base",
                baseline_log_dir=baseline_logs,
            )

            self.assertEqual(result.baseline.llvm_revision, "base")
            self.assertEqual(
                result.baseline.project_runs[0].diagnostics[0].message,
                "baseline warning",
            )
            self.assertIsNone(result.baseline.project_runs[0].diagnostics[0].verdict)

    def test_marks_requested_but_unavailable_baseline(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = create_result(
                log_dir=tmp_dir,
                report_path=None,
                github_run_id="42",
                github_run_attempt=1,
                pr_url="https://github.com/llvm/llvm-project/pull/123",
                llvm_revision="base+patch",
                check_name="check-a",
                check_config="{}",
                runner_arch="ARM64",
                started_at="2026-09-12T01:00:00Z",
                finished_at="2026-09-12T01:01:00Z",
                duration_seconds=60.0,
                status="COMPLETED",
                artifact_url=None,
                baseline_revision="base",
            )

            self.assertEqual(result.baseline.llvm_revision, "base")
            self.assertIsNone(result.baseline.project_runs)

    def test_keeps_report_rows_aligned_when_log_contains_an_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with open(os.path.join(tmp_dir, "demo.log"), "w") as stream:
                stream.write(
                    "/work/demo/a.cpp:1:1: error: compile error [clang-diagnostic-error]\n"
                    "/work/demo/a.cpp:2:1: warning: real warning [check-a]\n"
                )
            report = os.path.join(tmp_dir, "report.md")
            with open(report, "w") as stream:
                stream.write(
                    "| 1 | demo | FP | Error row. | a.cpp:1 |\n"
                    "| 2 | demo | TP | Warning row. | a.cpp:2 |\n"
                )

            result = create_result(
                log_dir=tmp_dir,
                report_path=report,
                github_run_id="42",
                github_run_attempt=1,
                pr_url="https://github.com/llvm/llvm-project/pull/123",
                llvm_revision="base+patch",
                check_name="check-a",
                check_config="{}",
                runner_arch="ARM64",
                started_at="2026-09-12T01:00:00Z",
                finished_at="2026-09-12T01:01:00Z",
                duration_seconds=60.0,
                status="COMPLETED",
                artifact_url=None,
            )

            diagnostics = result.project_runs[0].diagnostics
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics[0].verdict, "TP")


if __name__ == "__main__":
    unittest.main()
