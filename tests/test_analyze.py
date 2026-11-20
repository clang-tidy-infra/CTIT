import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from testers.analyze import (
    needs_static_analyzer,
    AnalysisConfig,
    analyze,
    analyze_project,
    analyzed_objects,
    build_project,
    check_clang_compiler,
    check_flags,
    configure,
    configure_cmake,
    configure_project,
    find_run_tidy_script,
    prerequisite_targets,
    remove_clang_tidy_configs,
    run_clang_tidy,
    get_analysis_configs,
    names_compiler_warnings,
)
from testers.config import Project


class TestCheckClangCompiler(unittest.TestCase):
    @patch.dict(os.environ, {"CC": "clang", "CXX": "clang++"})
    def test_passes_with_clang_env(self):
        check_clang_compiler()

    @patch.dict(os.environ, {"CC": "clang-21", "CXX": "clang++-21"})
    def test_passes_with_versioned_clang(self):
        check_clang_compiler()

    @patch.dict(os.environ, {"CC": "/usr/bin/clang", "CXX": "/usr/bin/clang++"})
    def test_passes_with_full_path(self):
        check_clang_compiler()

    @patch.dict(os.environ, {"CC": "gcc", "CXX": "g++"})
    def test_fails_with_gcc(self):
        with self.assertRaises(SystemExit) as ctx:
            check_clang_compiler()
        self.assertEqual(ctx.exception.code, 1)

    @patch.dict(os.environ, {"CC": "clang", "CXX": "g++"})
    def test_fails_with_mixed_compilers(self):
        with self.assertRaises(SystemExit) as ctx:
            check_clang_compiler()
        self.assertEqual(ctx.exception.code, 1)

    @patch.dict(os.environ, {}, clear=True)
    @patch("testers.analyze.shutil.which")
    def test_falls_back_to_path_lookup(self, mock_which):
        mock_which.side_effect = lambda name: (
            "/usr/bin/clang" if "clang" in name else f"/usr/bin/{name}"
        )
        # cc/c++ don't contain "clang", so this should fail
        with self.assertRaises(SystemExit):
            check_clang_compiler()

    @patch.dict(os.environ, {}, clear=True)
    @patch("testers.analyze.shutil.which")
    def test_passes_when_cc_symlinks_to_clang(self, mock_which):
        # cc resolves to /usr/bin/clang-21, which contains "clang".
        mock_which.side_effect = lambda name: (
            "/usr/bin/clang-21" if name == "cc" else "/usr/bin/clang++-21"
        )
        check_clang_compiler()


class TestRemoveClangTidyConfigs(unittest.TestCase):
    def test_removes_clang_tidy_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root_ct = os.path.join(tmp_dir, ".clang-tidy")
            sub_dir = os.path.join(tmp_dir, "sub")
            os.makedirs(sub_dir)
            sub_ct = os.path.join(sub_dir, ".clang-tidy")

            for path in (root_ct, sub_ct):
                with open(path, "w") as f:
                    f.write("Checks: '*'\n")

            other = os.path.join(tmp_dir, "keep.txt")
            with open(other, "w") as f:
                f.write("keep")

            remove_clang_tidy_configs(tmp_dir)

            self.assertFalse(os.path.exists(root_ct))
            self.assertFalse(os.path.exists(sub_ct))
            self.assertTrue(os.path.exists(other))

    def test_no_clang_tidy_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            remove_clang_tidy_configs(tmp_dir)


class TestConfigureCmake(unittest.TestCase):
    @patch("testers.analyze.shutil.which", return_value=None)
    @patch("testers.analyze.subprocess.run")
    def test_basic_flags(self, mock_run, mock_which):
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = os.path.join(tmp_dir, "build")
            configure_cmake(tmp_dir, build_dir, [])

            args = mock_run.call_args[0][0]
            self.assertEqual(args[0], "cmake")
            self.assertIn("-G", args)
            self.assertIn("Ninja", args)
            self.assertIn("-S", args)
            self.assertIn("-B", args)
            self.assertIn("-DCMAKE_EXPORT_COMPILE_COMMANDS=ON", args)
            self.assertIn("-DCMAKE_BUILD_TYPE=Release", args)
            self.assertTrue(os.path.isdir(build_dir))

    @patch("testers.analyze.shutil.which", return_value="/usr/bin/sccache")
    @patch("testers.analyze.subprocess.run")
    def test_with_sccache(self, mock_run, mock_which):
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = os.path.join(tmp_dir, "build")
            configure_cmake(tmp_dir, build_dir, [])

            args = mock_run.call_args[0][0]
            self.assertIn("-DCMAKE_C_COMPILER_LAUNCHER=sccache", args)
            self.assertIn("-DCMAKE_CXX_COMPILER_LAUNCHER=sccache", args)

    @patch("testers.analyze.shutil.which", return_value=None)
    @patch("testers.analyze.subprocess.run")
    def test_extra_flags_appended(self, mock_run, mock_which):
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = os.path.join(tmp_dir, "build")
            extra = ["-DBUILD_TESTS=ON", "-DFOO=BAR"]
            configure_cmake(tmp_dir, build_dir, extra)

            args = mock_run.call_args[0][0]
            self.assertIn("-DBUILD_TESTS=ON", args)
            self.assertIn("-DFOO=BAR", args)


class TestBuildProject(unittest.TestCase):
    @patch("testers.analyze.subprocess.run")
    def test_build_nothing_when_no_targets(self, mock_run):
        build_project("/build", [])
        mock_run.assert_not_called()

    @patch("testers.analyze.subprocess.run")
    def test_build_specific_targets(self, mock_run):
        build_project("/build", ["clang", "clang-tidy"])
        args = mock_run.call_args[0][0]
        self.assertEqual(args, ["ninja", "-C", "/build", "clang", "clang-tidy"])


class TestCheckFlags(unittest.TestCase):
    def test_regular_checks_need_nothing(self):
        self.assertEqual(check_flags("bugprone-*,-bugprone-foo"), [])
        self.assertEqual(check_flags("*,-clang-analyzer-*"), [])

    def test_compiler_errors_do_not_change_warning_policy(self):
        for checks in (
            "clang-diagnostic-error",
            "bugprone-argument-comment, clang-diagnostic-error",
        ):
            with self.subTest(checks=checks):
                self.assertEqual(check_flags(checks), ["-allow-no-checks"])

    def test_diagnostic_group_is_enabled(self):
        self.assertEqual(
            check_flags("clang-diagnostic-lifetime-safety*"),
            [
                "-allow-no-checks",
                "-extra-arg=-Wlifetime-safety-all",
                "-extra-arg=-Wno-error=lifetime-safety-all",
            ],
        )
        for checks in (
            "clang-diagnostic-lifetime-safety-use-after-scope",
            "clang-diagnostic-lifetime-safety-use-after-*",
            "clang-diagnostic-lifetime-safety-*suggestions",
            "clang-diagnostic-lifetime-safety-noescape",
        ):
            with self.subTest(checks=checks):
                self.assertEqual(
                    check_flags(checks),
                    [
                        "-allow-no-checks",
                        "-extra-arg=-Wlifetime-safety-all",
                        "-extra-arg=-Wno-error=lifetime-safety-all",
                    ],
                )

    def test_warning_is_enabled_and_kept_a_warning(self):
        self.assertEqual(
            check_flags("bugprone-*, clang-diagnostic-unused-variable"),
            [
                "-allow-no-checks",
                "-extra-arg=-Wunused-variable",
                "-extra-arg=-Wno-error=unused-variable",
            ],
        )

    def test_diagnostics_without_an_option_enable_nothing(self):
        for checks in ("clang-diagnostic-warning", "clang-diagnostic-remark"):
            with self.subTest(checks=checks):
                self.assertEqual(check_flags(checks), ["-allow-no-checks"])

    def test_glob_enables_its_prefix_group(self):
        self.assertEqual(
            check_flags("clang-diagnostic-unused-*"),
            [
                "-allow-no-checks",
                "-extra-arg=-Wunused",
                "-extra-arg=-Wno-error=unused",
            ],
        )

    def test_unmappable_diagnostic_globs_only_allow_no_checks(self):
        self.assertEqual(check_flags("clang-diagnostic-*"), ["-allow-no-checks"])
        self.assertEqual(
            check_flags("clang-diagnostic-*lifetime*"), ["-allow-no-checks"]
        )
        self.assertEqual(check_flags("-clang-diagnostic-unused-variable"), [])
        self.assertEqual(check_flags("-clang-diagnostic-lifetime-safety*"), [])


class TestNamesCompilerWarnings(unittest.TestCase):
    def test_names_a_compiler_warning(self):
        for check_name, expected in (
            ("clang-diagnostic-unused-variable", True),
            ("clang-diagnostic-*", True),
            ("bugprone-*, clang-diagnostic-lifetime-safety*", True),
            ("clang-diagnostic-error", False),
            ("bugprone-*,clang-diagnostic-error", False),
            ("*,-clang-diagnostic-unused-variable", False),
            ("*", False),
        ):
            with self.subTest(check_name=check_name):
                self.assertEqual(names_compiler_warnings(check_name), expected)


class TestNeedsStaticAnalyzer(unittest.TestCase):
    def test_follows_the_order_of_patterns(self):
        for check_name, expected in (
            ("clang-analyzer-unix.Malloc", True),
            ("-*,clang-analyzer-core.*", True),
            ("*", True),
            ("clang-*", True),
            ("clang-analyzer-*,-clang-analyzer-alpha.*", True),
            ("*,-clang-analyzer-*", False),
            ("*,-clang-*", False),
            ("clang-analyzer-*,-*", False),
            ("*,-clang-analyzer-*,clang-analyzer-unix.Malloc", True),
            (" bugprone-* , - clang-analyzer-* ", False),
            ("bugprone-argument-comment", False),
            ("clang-diagnostic-lifetime-safety-*", False),
            ("", False),
        ):
            with self.subTest(check_name=check_name):
                self.assertEqual(needs_static_analyzer(check_name), expected)

    def test_daily_timings_glob_keeps_every_project(self):
        # .github/workflows/daily-check-timings.yaml
        self.assertFalse(
            needs_static_analyzer(
                "*,-clang-analyzer-*,-bugprone-unchecked-optional-access,"
                "-abseil-unchecked-statusor-access"
            )
        )


class TestRunClangTidy(unittest.TestCase):
    def _make_mock_proc(self, lines: list[str]) -> MagicMock:
        proc = MagicMock()
        proc.stdout = iter(lines)
        proc.wait.return_value = 0
        return proc

    @patch("testers.analyze.subprocess.Popen")
    def test_basic_invocation(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc([])
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            progress_file = os.path.join(tmp_dir, "progress.log")
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "bugprone-*",
                "/src",
                None,
                log_file,
                progress_file,
                None,
            )

            args = mock_popen.call_args[0][0]
            self.assertIn("/bin/clang-tidy", args)
            self.assertIn("-checks=-*,bugprone-*", args)
            self.assertIn("-quiet", args)
            self.assertIn("-allow-enabling-alpha-checkers", args)
            self.assertNotIn("/src", " ".join(args))

    def _run(self, mock_popen, lines):
        mock_popen.return_value = self._make_mock_proc(lines)
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            started = run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "bugprone-argument-coment",
                "/src",
                None,
                log_file,
                os.path.join(tmp_dir, "progress.log"),
                None,
            )
            with open(log_file) as f:
                return started, f.read()

    @patch("testers.analyze.subprocess.Popen")
    def test_reports_that_clang_tidy_ran(self, mock_popen):
        started, _log = self._run(
            mock_popen,
            ["[1/1] clang-tidy a.cpp\n", "a.cpp:1:1: warning: w [check]\n"],
        )
        self.assertTrue(started)

    @patch("testers.analyze.subprocess.Popen")
    def test_reports_that_clang_tidy_did_not_start(self, mock_popen):
        # What run-clang-tidy prints for a misspelled check name.
        started, log = self._run(
            mock_popen, ["No checks enabled.\n", "Unable to run clang-tidy.\n"]
        )
        self.assertFalse(started)
        self.assertIn("No checks enabled.", log)

    @patch.dict(os.environ, {"CTIT_JOBS": "32"})
    @patch("testers.analyze.subprocess.Popen")
    def test_limits_parallel_jobs_from_environment(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc([])
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "check",
                "/src",
                None,
                os.path.join(tmp_dir, "test.log"),
                os.path.join(tmp_dir, "progress.log"),
                None,
            )

        args = mock_popen.call_args[0][0]
        self.assertIn("-j", args)
        self.assertEqual(args[args.index("-j") + 1], "32")

    @patch("testers.analyze.subprocess.Popen")
    def test_with_file_regex(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc([])
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            progress_file = os.path.join(tmp_dir, "progress.log")
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "check",
                "/src/project",
                "clang/.*$",
                log_file,
                progress_file,
                None,
            )

            args = mock_popen.call_args[0][0]
            self.assertIn("^/src/project/clang/.*$", args[-1])

    @patch("testers.analyze.subprocess.Popen")
    def test_with_tidy_config(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc([])
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            progress_file = os.path.join(tmp_dir, "progress.log")
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "check",
                "/src",
                None,
                log_file,
                progress_file,
                "VariableCase: camelBack",
            )

            args = mock_popen.call_args[0][0]
            self.assertIn("-config=VariableCase: camelBack", args)

    @patch("testers.analyze.subprocess.Popen")
    def test_passes_check_flags(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc([])
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "clang-diagnostic-lifetime-safety*",
                "/src",
                "src/.*",
                os.path.join(tmp_dir, "test.log"),
                os.path.join(tmp_dir, "progress.log"),
                None,
            )

        args = mock_popen.call_args[0][0]
        self.assertIn("-extra-arg=-Wlifetime-safety-all", args)
        # The file regex must stay the last, positional argument.
        self.assertEqual(args[-1], "^/src/src/.*")

    @patch("testers.analyze.time.monotonic", side_effect=[100.0, 112.345678])
    @patch("testers.analyze.subprocess.Popen")
    def test_writes_log_file(self, mock_popen, mock_clock):
        mock_popen.return_value = self._make_mock_proc(["line1\n", "line2\n"])
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            progress_file = os.path.join(tmp_dir, "progress.log")
            run_clang_tidy(
                "/bin/ct",
                "/script/rct.py",
                "/build",
                "check",
                "/src",
                None,
                log_file,
                progress_file,
                None,
            )

            with open(log_file) as f:
                content = f.read()
            self.assertEqual(
                content,
                "line1\nline2\n\nCTIT analysis elapsed seconds: 12.345678\n",
            )


class TestAnalyzedObjects(unittest.TestCase):
    def _write_database(self, build_dir: str, entries: list[dict]) -> None:
        os.makedirs(build_dir, exist_ok=True)
        with open(os.path.join(build_dir, "compile_commands.json"), "w") as f:
            json.dump(entries, f)

    def test_selects_files_like_run_clang_tidy(self):
        with tempfile.TemporaryDirectory() as src:
            build = os.path.join(src, "build")
            self._write_database(
                build,
                [
                    {
                        "directory": build,
                        "file": f"{src}/clang/lib/a.cpp",
                        "output": "tools/clang/a.cpp.o",
                    },
                    {
                        "directory": build,
                        "file": f"{src}/llvm/lib/b.cpp",
                        "output": f"{build}/lib/b.cpp.o",
                    },
                    {
                        "directory": build,
                        "file": "../clang/lib/c.cpp",
                        "output": f"{build}/tools/clang/c.cpp.o",
                    },
                ],
            )

            self.assertEqual(
                analyzed_objects(build, src, "clang/.*"),
                ["tools/clang/a.cpp.o", "tools/clang/c.cpp.o"],
            )
            self.assertEqual(
                analyzed_objects(build, src, None),
                ["lib/b.cpp.o", "tools/clang/a.cpp.o", "tools/clang/c.cpp.o"],
            )


class TestPrerequisiteTargets(unittest.TestCase):
    TARGETS = (
        "ninja: Entering directory `/build'\n"
        "a.o: CXX_COMPILER\n"
        "b.o: CXX_COMPILER\n"
        "gen/a.c: CUSTOM_COMMAND\n"
        "gen/b.h: CUSTOM_COMMAND\n"
        "gen/unused.h: CUSTOM_COMMAND\n"
        "cmake_object_order_depends_target_lib: phony\n"
    )
    QUERY = (
        "a.o:\n"
        "  input: CXX_COMPILER\n"
        "    gen/a.c\n"
        "    | gen/b.h\n"
        "    || cmake_object_order_depends_target_lib\n"
        "  outputs:\n"
        "    lib.a\n"
        "b.o:\n"
        "  input: CXX_COMPILER\n"
        "    /src/b.cpp\n"
        "    || cmake_object_order_depends_target_lib\n"
        "  validations:\n"
        "    gen/unused.h\n"
    )

    @patch("testers.analyze._ninja_tool")
    def test_returns_generated_inputs_of_objects(self, mock_tool):
        mock_tool.side_effect = lambda _build, tool, *args: (
            self.TARGETS if tool == "targets" else self.QUERY
        )
        self.assertEqual(
            prerequisite_targets("/build", ["a.o", "b.o"]),
            ["cmake_object_order_depends_target_lib", "gen/a.c", "gen/b.h"],
        )
        mock_tool.assert_any_call("/build", "query", "a.o", "b.o")

    @patch("testers.analyze._ninja_tool")
    def test_does_not_build_other_analyzed_objects(self, mock_tool):
        query = "a.o:\n  input: CXX_COMPILER\n    b.o\n  outputs:\n"
        mock_tool.side_effect = lambda _build, tool, *args: (
            self.TARGETS if tool == "targets" else query
        )
        self.assertEqual(prerequisite_targets("/build", ["a.o", "b.o"]), [])

    @patch("testers.analyze._ninja_tool")
    def test_nothing_to_analyze(self, mock_tool):
        self.assertEqual(prerequisite_targets("/build", []), [])
        mock_tool.assert_not_called()

    @patch("testers.analyze.NINJA_QUERY_CHUNK", 2)
    @patch("testers.analyze._ninja_tool", return_value="")
    def test_queries_in_chunks(self, mock_tool):
        prerequisite_targets("/build", ["a.o", "b.o", "c.o"])
        mock_tool.assert_any_call("/build", "query", "a.o", "b.o")
        mock_tool.assert_any_call("/build", "query", "c.o")


class TestConfigureProject(unittest.TestCase):
    @patch("testers.analyze.prerequisite_targets", return_value=[])
    @patch("testers.analyze.analyzed_objects", return_value=[])
    @patch("testers.analyze.build_project")
    @patch("testers.analyze.configure_cmake")
    @patch("testers.analyze.remove_clang_tidy_configs")
    def test_calls_steps_in_order(
        self, mock_remove, mock_cmake, mock_build, mock_objects, mock_prereqs
    ):
        project = Project(
            name="cppcheck", url="https://example.com/p.git", commit="abc"
        )
        config = AnalysisConfig(
            name="cppcheck",
            cmake_flags=["-DBUILD_TESTS=ON"],
        )
        configure_project(project, config, "/work/cppcheck")

        mock_remove.assert_called_once()
        mock_cmake.assert_called_once()
        mock_build.assert_called_once()

        cmake_args = mock_cmake.call_args[0]
        self.assertIn("-DBUILD_TESTS=ON", cmake_args[2])

        build_args = mock_build.call_args[0]
        self.assertEqual(build_args[1], [])

    @patch("testers.analyze.prerequisite_targets")
    @patch("testers.analyze.analyzed_objects")
    @patch("testers.analyze.build_project")
    @patch("testers.analyze.configure_cmake")
    @patch("testers.analyze.remove_clang_tidy_configs")
    def test_builds_prerequisites_of_analyzed_files(
        self, mock_remove, mock_cmake, mock_build, mock_objects, mock_prereqs
    ):
        mock_objects.return_value = ["tools/clang/a.cpp.o"]
        mock_prereqs.return_value = ["clang-tablegen-targets", "gen.h"]
        project = Project(
            name="llvm-project", url="https://example.com/llvm.git", commit="abc"
        )
        config = AnalysisConfig(
            name="llvm-project",
            cmake_source_subdir="llvm",
            build_targets=["gen.h", "extra"],
            file_regex="clang/.*",
        )
        configure_project(project, config, "/work/llvm-project")

        cmake_args = mock_cmake.call_args[0]
        self.assertTrue(cmake_args[0].endswith("/llvm"))

        mock_objects.assert_called_once_with(
            "/work/llvm-project/build", "/work/llvm-project", "clang/.*"
        )
        mock_prereqs.assert_called_once_with(
            "/work/llvm-project/build", ["tools/clang/a.cpp.o"]
        )
        build_args = mock_build.call_args[0]
        self.assertEqual(build_args[1], ["gen.h", "extra", "clang-tablegen-targets"])


class TestConfigure(unittest.TestCase):
    def _write_config(self, tmp_dir: str, names: list[str]) -> str:
        config_path = os.path.join(tmp_dir, "projects.json")
        projects = {
            name: {"url": f"https://example.com/{name}.git", "commit": "abc"}
            for name in names
        }
        with open(config_path, "w") as f:
            json.dump({"projects": projects}, f)
        return config_path

    @patch("testers.analyze.check_clang_compiler")
    @patch("testers.analyze.configure_project")
    def test_configures_every_project_and_prints_its_log(
        self, mock_configure, mock_check
    ):
        mock_configure.side_effect = lambda project, _config, _src, output: (
            output.write(f"{project.name} output\n")
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = self._write_config(tmp_dir, ["a", "b"])
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                configure(work_dir="/work", config_path=config_path)

        self.assertEqual(mock_configure.call_count, 2)
        dirs = sorted(call.args[2] for call in mock_configure.call_args_list)
        self.assertEqual(dirs, ["/work/a", "/work/b"])
        out = stdout.getvalue()
        for name in ("a", "b"):
            self.assertIn(f"[{name}] Configuring...\n{name} output\n[{name}] Done", out)

    @patch("testers.analyze.check_clang_compiler")
    @patch("testers.analyze.configure_project")
    def test_raises_after_other_projects_finish(self, mock_configure, mock_check):
        def configure_one(project, _config, _src, output):
            if project.name == "bad":
                output.write("cmake error\n")
                raise subprocess.CalledProcessError(1, ["cmake"])

        mock_configure.side_effect = configure_one
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = self._write_config(tmp_dir, ["bad", "good"])
            stdout = io.StringIO()
            with (
                redirect_stdout(stdout),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                configure(work_dir="/work", config_path=config_path)

        out = stdout.getvalue()
        self.assertIn("cmake error\n[bad] Failed", out)
        self.assertIn("[good] Done", out)


class TestAnalyzeProject(unittest.TestCase):
    @patch("testers.analyze.run_clang_tidy")
    def test_runs_clang_tidy(self, mock_tidy):
        project = Project(
            name="cppcheck", url="https://example.com/p.git", commit="abc"
        )
        config = AnalysisConfig(name="cppcheck")
        mock_tidy.return_value = False
        started = analyze_project(
            project,
            config,
            "/work/cppcheck",
            "/bin/ct",
            "/script/rct.py",
            "check",
            "/logs",
            "/logs/progress.log",
        )

        mock_tidy.assert_called_once()
        self.assertFalse(started)


class TestFindRunTidyScript(unittest.TestCase):
    @patch("testers.analyze.shutil.which")
    def test_finds_run_clang_tidy(self, mock_which):
        mock_which.side_effect = lambda name: (
            "/usr/bin/run-clang-tidy" if name == "run-clang-tidy" else None
        )
        self.assertEqual(find_run_tidy_script(), "/usr/bin/run-clang-tidy")

    @patch("testers.analyze.shutil.which")
    def test_finds_run_clang_tidy_py(self, mock_which):
        mock_which.side_effect = lambda name: (
            "/usr/bin/run-clang-tidy.py" if name == "run-clang-tidy.py" else None
        )
        self.assertEqual(find_run_tidy_script(), "/usr/bin/run-clang-tidy.py")

    @patch("testers.analyze.shutil.which", return_value=None)
    def test_returns_none_when_not_found(self, mock_which):
        self.assertIsNone(find_run_tidy_script())


class TestAnalyze(unittest.TestCase):
    def test_exits_when_clang_tidy_missing(self):
        with self.assertRaises(SystemExit) as ctx:
            analyze(
                check_name="check",
                clang_tidy_bin="/nonexistent/clang-tidy",
                run_tidy_script="/nonexistent/script.py",
            )
        self.assertEqual(ctx.exception.code, 1)

    @patch("testers.analyze.find_run_tidy_script", return_value=None)
    def test_exits_when_run_tidy_script_not_found(self, mock_find):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ct_bin = os.path.join(tmp_dir, "clang-tidy")
            with open(ct_bin, "w") as f:
                f.write("")
            with self.assertRaises(SystemExit) as ctx:
                analyze(
                    check_name="check",
                    clang_tidy_bin=ct_bin,
                )
            self.assertEqual(ctx.exception.code, 1)

    @patch("testers.analyze.analyze_project")
    @patch("testers.analyze.load_projects")
    def test_iterates_projects(self, mock_load, mock_analyze):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ct_bin = os.path.join(tmp_dir, "clang-tidy")
            script = os.path.join(tmp_dir, "run-clang-tidy.py")
            for path in (ct_bin, script):
                with open(path, "w") as f:
                    f.write("")

            projects = [
                Project(name="a", url="u", commit="c"),
                Project(name="b", url="u", commit="c"),
            ]
            mock_load.return_value = projects

            log_dir = os.path.join(tmp_dir, "logs")
            analyze(
                check_name="check",
                clang_tidy_bin=ct_bin,
                run_tidy_script=script,
                log_dir=log_dir,
            )

            self.assertEqual(mock_analyze.call_count, 2)
            self.assertTrue(os.path.isdir(log_dir))

    def _analyzed(self, check_name):
        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            patch("testers.analyze.load_projects") as mock_load,
            patch("testers.analyze.get_analysis_configs") as mock_configs,
            patch("testers.analyze.analyze_project", return_value=True) as mock_run,
        ):
            ct_bin = os.path.join(tmp_dir, "clang-tidy")
            script = os.path.join(tmp_dir, "run-clang-tidy.py")
            for path in (ct_bin, script):
                with open(path, "w") as f:
                    f.write("")
            mock_load.return_value = [
                Project(name="heavy", url="u", commit="c"),
                Project(name="light", url="u", commit="c"),
            ]
            mock_configs.return_value = {
                "heavy": AnalysisConfig(name="heavy", static_analyzer=False)
            }
            analyze(
                check_name=check_name,
                clang_tidy_bin=ct_bin,
                run_tidy_script=script,
                log_dir=os.path.join(tmp_dir, "logs"),
            )
            return [call.args[0].name for call in mock_run.call_args_list]

    def test_skips_projects_excluded_from_the_static_analyzer(self):
        self.assertEqual(self._analyzed("clang-analyzer-unix.Malloc"), ["light"])
        self.assertEqual(self._analyzed("bugprone-*,clang-analyzer-*"), ["light"])

    def test_excluded_projects_still_run_other_checks(self):
        self.assertEqual(
            self._analyzed("bugprone-argument-comment"), ["heavy", "light"]
        )
        self.assertEqual(self._analyzed("*,-clang-analyzer-*"), ["heavy", "light"])

    @patch("testers.analyze.analyze_project", return_value=False)
    @patch("testers.analyze.load_projects")
    def test_stops_when_clang_tidy_does_not_start(self, mock_load, mock_analyze):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ct_bin = os.path.join(tmp_dir, "clang-tidy")
            script = os.path.join(tmp_dir, "run-clang-tidy.py")
            for path in (ct_bin, script):
                with open(path, "w") as f:
                    f.write("")
            mock_load.return_value = [
                Project(name="a", url="u", commit="c"),
                Project(name="b", url="u", commit="c"),
            ]
            log_dir = os.path.join(tmp_dir, "logs")
            os.makedirs(log_dir)
            with open(os.path.join(log_dir, "a.log"), "w") as f:
                f.write("No checks enabled.\nUnable to run clang-tidy.\n")

            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as ctx:
                analyze(
                    check_name="bugprone-argument-coment",
                    clang_tidy_bin=ct_bin,
                    run_tidy_script=script,
                    log_dir=log_dir,
                )

        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(mock_analyze.call_count, 1)
        self.assertIn("No checks enabled.", stderr.getvalue())


class TestGetAnalysisConfigs(unittest.TestCase):
    def test_discovers_cppcheck(self):
        configs = get_analysis_configs()
        self.assertIn("cppcheck", configs)
        self.assertIn("-DBUILD_TESTS=ON", configs["cppcheck"].cmake_flags)

    def test_discovers_llvm_project(self):
        configs = get_analysis_configs()
        self.assertIn("llvm-project", configs)
        cfg = configs["llvm-project"]
        self.assertEqual(cfg.cmake_source_subdir, "llvm")
        # The generated headers are built from the analyzed files' prerequisites.
        self.assertEqual(cfg.build_targets, [])
        self.assertIsNotNone(cfg.file_regex)

    def test_llvm_project_skips_the_static_analyzer(self):
        configs = get_analysis_configs()
        self.assertFalse(configs["llvm-project"].static_analyzer)
        self.assertTrue(configs["cppcheck"].static_analyzer)

    def test_unknown_project_not_present(self):
        configs = get_analysis_configs()
        self.assertNotIn("nonexistent", configs)


if __name__ == "__main__":
    unittest.main()
