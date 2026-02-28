import os
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from testers.analyze import (
    AnalysisConfig,
    analyze,
    analyze_project,
    build_project,
    configure_cmake,
    remove_clang_tidy_configs,
    run_clang_tidy,
    get_analysis_configs,
)
from testers.config import Project


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
    @patch(
        "testers.analyze.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout=b""),
    )
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
    @patch(
        "testers.analyze.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout=b""),
    )
    def test_with_sccache(self, mock_run, mock_which):
        with tempfile.TemporaryDirectory() as tmp_dir:
            build_dir = os.path.join(tmp_dir, "build")
            configure_cmake(tmp_dir, build_dir, [])

            args = mock_run.call_args[0][0]
            self.assertIn("-DCMAKE_C_COMPILER_LAUNCHER=sccache", args)
            self.assertIn("-DCMAKE_CXX_COMPILER_LAUNCHER=sccache", args)

    @patch("testers.analyze.shutil.which", return_value=None)
    @patch(
        "testers.analyze.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout=b""),
    )
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

    @patch(
        "testers.analyze.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, stdout=b""),
    )
    def test_build_specific_targets(self, mock_run):
        build_project("/build", ["clang", "clang-tidy"])
        args = mock_run.call_args[0][0]
        self.assertEqual(args, ["ninja", "-C", "/build", "clang", "clang-tidy"])


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
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "bugprone-*",
                "/src",
                None,
                log_file,
                None,
            )

            args = mock_popen.call_args[0][0]
            self.assertIn("/bin/clang-tidy", args)
            self.assertIn("-checks=-*,bugprone-*", args)
            self.assertIn("-quiet", args)
            self.assertNotIn("/src", " ".join(args))

    @patch("testers.analyze.subprocess.Popen")
    def test_with_file_regex(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc([])
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "check",
                "/src/project",
                "clang/.*$",
                log_file,
                None,
            )

            args = mock_popen.call_args[0][0]
            self.assertIn("^/src/project/clang/.*$", args[-1])

    @patch("testers.analyze.subprocess.Popen")
    def test_with_tidy_config(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc([])
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            run_clang_tidy(
                "/bin/clang-tidy",
                "/script/run-clang-tidy.py",
                "/build",
                "check",
                "/src",
                None,
                log_file,
                "VariableCase: camelBack",
            )

            args = mock_popen.call_args[0][0]
            self.assertIn("-config=VariableCase: camelBack", args)

    @patch("testers.analyze.subprocess.Popen")
    def test_writes_log_file(self, mock_popen):
        mock_popen.return_value = self._make_mock_proc(["line1\n", "line2\n"])
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_file = os.path.join(tmp_dir, "test.log")
            run_clang_tidy(
                "/bin/ct",
                "/script/rct.py",
                "/build",
                "check",
                "/src",
                None,
                log_file,
                None,
            )

            with open(log_file) as f:
                content = f.read()
            self.assertEqual(content, "line1\nline2\n")


class TestAnalyzeProject(unittest.TestCase):
    @patch("testers.analyze.run_clang_tidy")
    @patch("testers.analyze.build_project")
    @patch("testers.analyze.configure_cmake")
    @patch("testers.analyze.remove_clang_tidy_configs")
    def test_calls_steps_in_order(self, mock_remove, mock_cmake, mock_build, mock_tidy):
        project = Project(
            name="cppcheck", url="https://example.com/p.git", commit="abc"
        )
        config = AnalysisConfig(
            name="cppcheck",
            cmake_flags=["-DBUILD_TESTS=ON"],
        )
        analyze_project(
            project,
            config,
            "/work/cppcheck",
            "/bin/ct",
            "/script/rct.py",
            "check",
            "/logs",
        )

        mock_remove.assert_called_once()
        mock_cmake.assert_called_once()
        mock_build.assert_called_once()
        mock_tidy.assert_called_once()

        cmake_args = mock_cmake.call_args[0]
        self.assertIn("-DBUILD_TESTS=ON", cmake_args[2])

        build_args = mock_build.call_args[0]
        self.assertEqual(build_args[1], [])

    @patch("testers.analyze.run_clang_tidy")
    @patch("testers.analyze.build_project")
    @patch("testers.analyze.configure_cmake")
    @patch("testers.analyze.remove_clang_tidy_configs")
    def test_cmake_source_subdir(self, mock_remove, mock_cmake, mock_build, mock_tidy):
        project = Project(
            name="llvm-project", url="https://example.com/llvm.git", commit="abc"
        )
        config = AnalysisConfig(
            name="llvm-project",
            cmake_source_subdir="llvm",
            build_targets=["clang"],
        )
        analyze_project(
            project,
            config,
            "/work/llvm-project",
            "/bin/ct",
            "/script/rct.py",
            "check",
            "/logs",
        )

        cmake_args = mock_cmake.call_args[0]
        self.assertTrue(cmake_args[0].endswith("/llvm"))

        build_args = mock_build.call_args[0]
        self.assertIn("clang", build_args[1])


class TestAnalyze(unittest.TestCase):
    def test_exits_when_clang_tidy_missing(self):
        with self.assertRaises(SystemExit) as ctx:
            analyze(
                check_name="check",
                clang_tidy_bin="/nonexistent/clang-tidy",
                run_tidy_script="/nonexistent/script.py",
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
        self.assertTrue(len(cfg.build_targets) > 0)
        self.assertIsNotNone(cfg.file_regex)

    def test_unknown_project_not_present(self):
        configs = get_analysis_configs()
        self.assertNotIn("nonexistent", configs)


if __name__ == "__main__":
    unittest.main()
