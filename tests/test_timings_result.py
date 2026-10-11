import json
import os
import tempfile
import unittest

from crash_detection.timings_result import create_timings, write_timings


def _profile(rows: dict[str, float]) -> str:
    total = sum(rows.values())
    lines = [
        "                          clang-tidy checks profiling\n",
        f"  Total Execution Time: {total:.4f} seconds ({total:.4f} wall clock)\n",
        "   ---User Time---    --System Time--    --User+System--    ---Wall Time---   --- Name ---\n",
    ]
    for name, wall in [*rows.items(), ("Total", total)]:
        lines.append(
            f"    {wall:.4f} ( 50.0%)    0.0000 (  0.0%)    {wall:.4f} ( 50.0%)"
            f"    {wall:.4f} ( 50.0%)  {name}\n"
        )
    return "".join(lines)


def _write_log(log_dir: str, project: str, content: str) -> None:
    with open(os.path.join(log_dir, f"{project}.log"), "w") as stream:
        stream.write(content)


def _create(log_dir: str, **kwargs):
    kwargs.setdefault("date", "2026-10-11")
    kwargs.setdefault("runner_arch", "ARM64")
    kwargs.setdefault("github_run_attempt", 1)
    return create_timings(
        log_dir=log_dir,
        github_run_id="42",
        llvm_revision="ABCDEF1234",
        runner_name="arm-1",
        machine="Linux aarch64, 80 CPUs",
        **kwargs,
    )


class TestTimingsResult(unittest.TestCase):
    def test_writes_public_timings_record(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_log(
                tmp_dir,
                "one",
                "warning before the profile\n"
                + _profile({"check-a": 2.5, "check-b": 1.0})
                + "\nCTIT analysis elapsed seconds: 12.345678\n",
            )
            _write_log(
                tmp_dir,
                "two",
                _profile({"check-a": 0.25, "check-c": 0.5})
                + "\nCTIT analysis elapsed seconds: 3.000000\n",
            )
            _write_log(tmp_dir, "progress", "[ 1/2] Running clang-tidy\n")

            output = os.path.join(tmp_dir, "results", "timings.json")
            write_timings(_create(tmp_dir), output)

            with open(output) as stream:
                text = stream.read()
            saved = json.loads(text)
            self.assertEqual(saved["date"], "2026-10-11")
            self.assertEqual(saved["github_run_id"], 42)
            self.assertEqual(saved["llvm_revision"], "abcdef1234")
            self.assertEqual(saved["runner_name"], "arm-1")
            self.assertEqual(saved["machine"], "Linux aarch64, 80 CPUs")
            self.assertEqual(
                saved["checks"], {"check-a": 2.75, "check-b": 1.0, "check-c": 0.5}
            )
            self.assertEqual(
                saved["projects"],
                {
                    "one": {"duration_seconds": 12.35, "check_seconds": 3.5},
                    "two": {"duration_seconds": 3.0, "check_seconds": 0.75},
                },
            )
            self.assertEqual(saved["check_names"], ["check-a", "check-b", "check-c"])
            self.assertEqual(
                saved["project_checks"],
                {"one": [2.5, 1.0, None], "two": [0.25, None, 0.5]},
            )
            # One line per project, not one per number.
            self.assertIn('"one": [2.5, 1.0, null]', text)

    def test_keeps_projects_without_profile(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_log(tmp_dir, "one", _profile({"check-a": 1.0}))
            _write_log(tmp_dir, "crashed", "Segmentation fault\n")

            timings = _create(tmp_dir)

            self.assertIsNone(timings.projects["one"].duration_seconds)
            self.assertIsNone(timings.projects["crashed"].check_seconds)
            self.assertEqual(timings.checks, {"check-a": 1.0})
            self.assertEqual(timings.project_checks, {"one": [1.0]})

    def test_check_times_add_up_to_the_combined_times(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_log(tmp_dir, "one", _profile({"check-a": 1.25, "check-b": 2.0}))
            _write_log(tmp_dir, "two", _profile({"check-a": 0.5}))

            timings = _create(tmp_dir)

            for i, name in enumerate(timings.check_names):
                total = sum(
                    column[i] or 0.0 for column in timings.project_checks.values()
                )
                self.assertAlmostEqual(total, timings.checks[name])

    def test_unknown_machine_is_null(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_log(tmp_dir, "one", _profile({"check-a": 1.0}))
            timings = create_timings(
                log_dir=tmp_dir,
                date="2026-10-11",
                github_run_id="42",
                github_run_attempt=1,
                llvm_revision="abc",
                runner_name="arm-1",
                runner_arch="ARM64",
                machine="",
            )
            self.assertIsNone(timings.machine)

    def test_rejects_logs_without_profiles(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_log(tmp_dir, "one", "CTIT analysis elapsed seconds: 1.0\n")
            with self.assertRaisesRegex(ValueError, "no profiling data"):
                _create(tmp_dir)

    def test_rejects_invalid_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_log(tmp_dir, "one", _profile({"check-a": 1.0}))
            with self.assertRaisesRegex(ValueError, "date"):
                _create(tmp_dir, date="previous run")
            with self.assertRaisesRegex(ValueError, "architecture"):
                _create(tmp_dir, runner_arch="arm64")
            with self.assertRaisesRegex(ValueError, "attempt"):
                _create(tmp_dir, github_run_attempt=0)


if __name__ == "__main__":
    unittest.main()
