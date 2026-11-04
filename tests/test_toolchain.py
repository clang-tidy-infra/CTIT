import glob
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from testers.analyze import (
    CONFIGURED_MARKER,
    AnalysisConfig,
    analyze,
    configure_project,
)
from testers.config import Project
from testers.generate_report import generate_report
from testers.result import create_result
from testers.toolchain import RECORD_FILE, Toolchain, load_toolchain


def _touch(path: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    return path


class ToolchainDirTestCase(unittest.TestCase):
    """Creates an installed-looking compiler and library layout in a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.cc = _touch(os.path.join(self.root, "bin", "clang-21"))
        self.cxx = _touch(os.path.join(self.root, "bin", "clang++-21"))
        self.gcc_dir = os.path.join(self.root, "gcc", "13")
        os.makedirs(self.gcc_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def libstdcxx(self, **overrides) -> dict:
        profile = {
            "name": "libstdcxx-13",
            "stdlib": "libstdc++",
            "cc": self.cc,
            "cxx": self.cxx,
            "gcc_install_dir": self.gcc_dir,
            "library_dir": self.gcc_dir,
        }
        profile.update(overrides)
        return {k: v for k, v in profile.items() if v is not None}

    def write_profile(self, profile: dict) -> str:
        path = os.path.join(self.root, "profile.json")
        with open(path, "w") as f:
            json.dump(profile, f)
        return path


class TestLoadToolchain(ToolchainDirTestCase):
    def test_loads_valid_profile(self):
        toolchain = load_toolchain(self.write_profile(self.libstdcxx()))
        self.assertEqual(toolchain.gcc_install_dir, self.gcc_dir)
        self.assertIsNone(toolchain.include_dir)

    def test_rejects_invalid_profiles(self):
        cases = {
            "stdlib": self.libstdcxx(stdlib="msvc"),
            "missing field 'gcc_install_dir'": self.libstdcxx(gcc_install_dir=None),
            # include_dir belongs to libc++ profiles only.
            "unknown field 'include_dir'": self.libstdcxx(include_dir=self.gcc_dir),
            "'library_dir' must be an absolute path": self.libstdcxx(
                library_dir="gcc/13"
            ),
            "does not exist": self.libstdcxx(library_dir=self.gcc_dir + "-missing"),
            "must be a clang compiler": self.libstdcxx(
                cxx=_touch(os.path.join(self.root, "bin", "g++-13"))
            ),
            "'name' may only contain": self.libstdcxx(name="../escape"),
        }
        for message, profile in cases.items():
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValueError, message),
            ):
                load_toolchain(self.write_profile(profile))

    def test_key_changes_with_any_field(self):
        base = Toolchain(**self.libstdcxx())
        other_dir = Toolchain(**self.libstdcxx(library_dir=self.root))
        self.assertEqual(base.key, Toolchain(**self.libstdcxx()).key)
        self.assertTrue(base.key.startswith("libstdcxx-13-"))
        self.assertNotEqual(base.key, other_dir.key)


class TestToolchainFlags(unittest.TestCase):
    def test_libcxx_link_only_flags_stay_out_of_compile_flags(self):
        toolchain = Toolchain(
            name="libcxx-21",
            stdlib="libc++",
            cc="/usr/bin/clang-21",
            cxx="/usr/bin/clang++-21",
            include_dir="/llvm/include/c++/v1",
            library_dir="/llvm/lib",
        )
        flags = dict(flag.split("=", 1) for flag in toolchain.cmake_flags())
        # Compiles use CMAKE_CXX_FLAGS; -stdlib there is an unused argument.
        self.assertEqual(
            flags["-DCMAKE_CXX_FLAGS"], "-nostdinc++ -isystem /llvm/include/c++/v1"
        )
        # LLVM objects reference libc++abi directly (e.g. __cxa_guard_acquire).
        for kind in ("EXE", "SHARED", "MODULE"):
            self.assertEqual(
                flags[f"-DCMAKE_{kind}_LINKER_FLAGS"],
                "-stdlib=libc++ -L/llvm/lib -Wl,-rpath,/llvm/lib -lc++abi",
            )
        self.assertNotIn("-DCMAKE_C_FLAGS", flags)


class TestToolchainBuilds(ToolchainDirTestCase):
    def setUp(self):
        super().setUp()
        self.toolchain = Toolchain(**self.libstdcxx())
        self.work_dir = os.path.join(self.root, "projects")
        self.source_dir = os.path.join(self.work_dir, "demo")
        self.build_dir = os.path.join(self.source_dir, "build-ctit", self.toolchain.key)
        self.project = Project(name="demo", url="u", commit="c")

    @patch("testers.analyze.build_project")
    @patch("testers.analyze.configure_cmake")
    def test_profile_flags_follow_project_flags(self, mock_cmake, mock_build):
        config = AnalysisConfig(name="demo", cmake_flags=["-DCMAKE_CXX_FLAGS=-O0"])
        configure_project(self.project, config, self.source_dir, self.toolchain)

        _source, build_dir, flags = mock_cmake.call_args[0]
        self.assertEqual(build_dir, self.build_dir)
        self.assertEqual(flags[0], "-DCMAKE_CXX_FLAGS=-O0")
        self.assertEqual(flags[1:], self.toolchain.cmake_flags())
        self.assertTrue(os.path.isfile(os.path.join(build_dir, CONFIGURED_MARKER)))
        self.assertTrue(os.path.isfile(os.path.join(build_dir, RECORD_FILE)))

    @patch("testers.analyze.build_project", side_effect=RuntimeError("build failed"))
    @patch("testers.analyze.configure_cmake")
    def test_failed_reconfigure_removes_marker(self, mock_cmake, mock_build):
        marker = _touch(os.path.join(self.build_dir, CONFIGURED_MARKER))
        with self.assertRaises(RuntimeError):
            configure_project(
                self.project,
                AnalysisConfig(name="demo"),
                self.source_dir,
                self.toolchain,
            )
        self.assertFalse(os.path.exists(marker))

    def _analyze(self, log_dir: str, toolchain: Toolchain | None) -> None:
        script = _touch(os.path.join(self.root, "run-clang-tidy.py"))
        with patch("testers.analyze.load_projects", return_value=[self.project]):
            analyze(
                check_name="check",
                clang_tidy_bin=self.cc,
                run_tidy_script=script,
                work_dir=self.work_dir,
                log_dir=log_dir,
                toolchain=toolchain,
            )

    @patch("testers.analyze.analyze_project")
    def test_analyze_refuses_unconfigured_profile(self, mock_analyze):
        # A compilation database alone is not enough without the success marker.
        _touch(os.path.join(self.build_dir, "compile_commands.json"))
        with self.assertRaises(SystemExit):
            self._analyze(os.path.join(self.root, "logs"), self.toolchain)
        mock_analyze.assert_not_called()

    @patch("testers.analyze.analyze_project")
    def test_profile_is_recorded_in_report_and_result(self, mock_analyze):
        _touch(os.path.join(self.build_dir, "compile_commands.json"))
        _touch(os.path.join(self.build_dir, CONFIGURED_MARKER))
        log_dir = os.path.join(self.root, "logs")
        self._analyze(log_dir, self.toolchain)
        self.assertEqual(
            mock_analyze.call_args.args[-1], self.toolchain, "analyzes profile build"
        )
        with open(os.path.join(log_dir, "demo.log"), "w") as f:
            f.write("CTIT analysis elapsed seconds: 1.000000\n")

        issue = os.path.join(self.root, "issue.md")
        generate_report(log_dir=log_dir, output=issue)
        with open(issue) as f:
            self.assertIn(
                f"Toolchain profile: `libstdcxx-13` (libstdc++, key "
                f"`{self.toolchain.key}`)",
                f.read(),
            )

        result = create_result(
            log_dir=log_dir,
            report_path=None,
            github_run_id="1",
            github_run_attempt=1,
            pr_url="",
            llvm_revision="rev",
            check_name="check",
            check_config="",
            runner_arch="X64",
            started_at="2026-11-01T00:00:00Z",
            finished_at="2026-11-01T00:01:00Z",
            duration_seconds=60.0,
            status="COMPLETED",
            artifact_url=None,
        )
        assert result.toolchain is not None
        self.assertEqual(result.toolchain["key"], self.toolchain.key)

        # A later default-toolchain analysis in the same directory drops the record.
        self._analyze(log_dir, None)
        generate_report(log_dir=log_dir, output=issue)
        with open(issue) as f:
            self.assertNotIn("Toolchain profile", f.read())


CXX_SOURCE = """
#include <cstdio>
#include <iostream>
#include <stdexcept>
#include <string>
struct Init { Init() {} };
Init &init() { static Init value; return value; }
int main() {
  init();
  try { throw std::runtime_error(std::to_string(1)); } catch (...) {}
  std::cout << "";
#if defined(_LIBCPP_VERSION)
  std::printf("libc++ %d\\n", _LIBCPP_VERSION);
#else
  std::printf("libstdc++ %d\\n", _GLIBCXX_RELEASE);
#endif
}
"""


def _run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True).stdout


@unittest.skipUnless(
    os.environ.get("CTIT_TOOLCHAIN_DIR"), "runs inside the ctit-runner image"
)
class TestBundledProfiles(unittest.TestCase):
    """Builds and runs C++ and C programs with every profile in the image."""

    def test_profiles_build_and_run(self):
        directory = os.environ["CTIT_TOOLCHAIN_DIR"]
        profiles = sorted(glob.glob(os.path.join(directory, "*.json")))
        self.assertTrue(profiles, f"no toolchain profiles in {directory}")
        with tempfile.TemporaryDirectory() as work_dir:
            for path in profiles:
                with self.subTest(profile=os.path.basename(path)):
                    self._check(load_toolchain(path), work_dir)

    def _check(self, toolchain: Toolchain, work_dir: str) -> None:
        cxx, link = toolchain.cxx_flags(), toolchain.linker_flags()
        base = os.path.join(work_dir, toolchain.name)
        with open(base + ".cpp", "w") as f:
            f.write(CXX_SOURCE)
        with open(base + ".c", "w") as f:
            f.write("int main(void) { return 0; }\n")

        _run(toolchain.cxx, "-Werror", *cxx, "-c", base + ".cpp", "-o", base + ".o")
        _run(toolchain.cxx, "-Werror", *cxx, *link, base + ".o", "-o", base + "-cxx")
        stdlib, version = _run(base + "-cxx").split()
        self.assertEqual(stdlib, toolchain.stdlib)
        if toolchain.gcc_install_dir:
            self.assertTrue(
                version.startswith(os.path.basename(toolchain.gcc_install_dir))
            )

        _run(toolchain.cc, "-Werror", "-c", base + ".c", "-o", base + ".c.o")
        _run(toolchain.cc, "-Werror", *link, base + ".c.o", "-o", base + "-c")


if __name__ == "__main__":
    unittest.main()
