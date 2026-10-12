import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest

from parse_issue import parse_body, write_env

PARSE_ISSUE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "parse_issue.py")


def _read_env(path: str) -> dict[str, str]:
    """Read a GitHub environment file written with name<<delimiter entries."""
    values: dict[str, str] = {}
    with open(path) as f:
        lines = f.read().splitlines()
    i = 0
    while i < len(lines):
        name, delimiter = lines[i].split("<<", 1)
        end = lines.index(delimiter, i + 1)
        values[name] = "\n".join(lines[i + 1 : end])
        i = end + 1
    return values


class TestParseIssue(unittest.TestCase):
    def test_simple_parse(self):
        body = """
        https://github.com/llvm/llvm-project/pull/12345 bugprone-argument-comment
        """
        result = parse_body(body)
        self.assertEqual(
            result.pr_link, "https://github.com/llvm/llvm-project/pull/12345"
        )
        self.assertEqual(result.check_name, "bugprone-argument-comment")
        self.assertEqual(result.tidy_config, "")
        self.assertFalse(result.compare_baseline)

    def test_baseline_opt_in(self):
        result = parse_body("https://example.com/pr check\n /baseline \nOption: true")
        self.assertTrue(result.compare_baseline)
        self.assertEqual(
            json.loads(result.tidy_config), {"CheckOptions": {"check.Option": "true"}}
        )

    def test_baseline_requires_standalone_directive(self):
        result = parse_body("https://example.com/pr check\nOption: /baseline")
        self.assertFalse(result.compare_baseline)

    def test_lifetime_baseline_defaults(self):
        for checks, expected in (
            ("clang-diagnostic-lifetime-safety*", True),
            ("clang-diagnostic-lifetime-safety-use-after-scope", True),
            ("clang-diagnostic-lifetime-safety-*suggestions", True),
            ("bugprone-*,clang-diagnostic-lifetime-safety-noescape", True),
            ("bugprone-*,-clang-diagnostic-lifetime-safety*", False),
            ("clang-diagnostic-unused-variable", False),
            ("bugprone-*", False),
        ):
            with self.subTest(checks=checks):
                result = parse_body(f"https://example.com/pr {checks}")
                self.assertEqual(result.compare_baseline, expected)
                self.assertEqual(result.check_name, checks)
                self.assertFalse(parse_body(checks).compare_baseline)
                self.assertFalse(parse_body(f"{checks}\n/baseline").compare_baseline)

    def test_readability_naming_options(self):
        body = """
        https://github.com/llvm/llvm-project/pull/123 readability-identifier-naming
        VariableCase: camelBack
        VariablePrefix: v_
        IgnoreFailedSplit: true
        """
        result = parse_body(body)
        self.assertEqual(
            result.pr_link, "https://github.com/llvm/llvm-project/pull/123"
        )
        self.assertEqual(result.check_name, "readability-identifier-naming")

        config = json.loads(result.tidy_config)
        opts = config["CheckOptions"]
        self.assertEqual(
            opts["readability-identifier-naming.VariableCase"], "camelBack"
        )
        self.assertEqual(opts["readability-identifier-naming.VariablePrefix"], "v_")
        self.assertEqual(
            opts["readability-identifier-naming.IgnoreFailedSplit"], "true"
        )

    def test_modernize_auto_options(self):
        body = """
        https://github.com/llvm/llvm-project/pull/456 readability-identifier-naming
        MinTypeNameLength: 5
        RemoveStars: false
        """
        result = parse_body(body)
        self.assertEqual(result.check_name, "readability-identifier-naming")

        opts = json.loads(result.tidy_config)["CheckOptions"]
        self.assertEqual(opts["readability-identifier-naming.MinTypeNameLength"], "5")
        self.assertEqual(opts["readability-identifier-naming.RemoveStars"], "false")

    def test_full_prefix_consistency(self):
        body = """
        https://github.com/llvm/llvm-project/pull/789 readability-identifier-naming
        readability-identifier-naming.StrictMode: true
        """
        result = parse_body(body)
        self.assertEqual(result.check_name, "readability-identifier-naming")

        config = json.loads(result.tidy_config)
        self.assertEqual(
            config["CheckOptions"]["readability-identifier-naming.StrictMode"], "true"
        )
        self.assertNotIn(
            "readability-identifier-naming.readability-identifier-naming.StrictMode",
            config["CheckOptions"],
        )

    def test_mismatched_prefix(self):
        body = """
        https://github.com/llvm/llvm-project/pull/789 readability-identifier-naming
        bugprone-use-after-move.VariableCase: camelBack
        """
        result = parse_body(body)
        config = json.loads(result.tidy_config)

        self.assertEqual(
            config["CheckOptions"]["readability-identifier-naming.VariableCase"],
            "camelBack",
        )
        self.assertNotIn(
            "bugprone-use-after-move.VariableCase",
            config["CheckOptions"],
        )

    def test_check_name_without_pr_link(self):
        result = parse_body("bugprone-argument-comment")
        self.assertEqual(result.pr_link, "")
        self.assertEqual(result.check_name, "bugprone-argument-comment")
        self.assertEqual(result.tidy_config, "")
        self.assertFalse(result.compare_baseline)

    def test_options_without_pr_link(self):
        body = """
        readability-identifier-naming
        VariableCase: camelBack
        """
        result = parse_body(body)
        self.assertEqual(result.pr_link, "")
        opts = json.loads(result.tidy_config)["CheckOptions"]
        self.assertEqual(
            opts["readability-identifier-naming.VariableCase"], "camelBack"
        )

    def test_baseline_ignored_without_pr_link(self):
        result = parse_body("check\n/baseline")
        self.assertFalse(result.compare_baseline)

    def test_empty_body(self):
        with self.assertRaises(ValueError):
            parse_body("")

    def test_malformed_first_line(self):
        with self.assertRaises(ValueError):
            parse_body("https://github.com/llvm/llvm-project/pull/789")


class TestFlags(unittest.TestCase):
    def test_flags_are_collected_in_order(self):
        result = parse_body(
            "https://github.com/llvm/llvm-project/pull/1 bugprone-x\n"
            "/flags -extra-arg=-std=c++20 -header-filter=.*\n"
            "Option: value\n"
            "/flags -extra-arg-before=-DNAME=1"
        )
        self.assertEqual(
            result.tidy_args,
            [
                "-extra-arg=-std=c++20",
                "-header-filter=.*",
                "-extra-arg-before=-DNAME=1",
            ],
        )
        self.assertEqual(
            json.loads(result.tidy_config),
            {"CheckOptions": {"bugprone-x.Option": "value"}},
        )

    def test_flags_line_is_not_a_check_option(self):
        result = parse_body("check\n/flags -extra-arg=-DURL=http://example.com")
        self.assertEqual(result.tidy_config, "")
        self.assertEqual(result.tidy_args, ["-extra-arg=-DURL=http://example.com"])

    def test_flags_are_quoted_like_in_a_shell(self):
        result = parse_body(
            "check\n/flags '-extra-arg=-DMSG=a b' --removed-arg=-Werror"
        )
        self.assertEqual(
            result.tidy_args, ["-extra-arg=-DMSG=a b", "-removed-arg=-Werror"]
        )

    def test_no_flags(self):
        self.assertEqual(parse_body("check\n/flags").tidy_args, [])
        self.assertEqual(parse_body("check").tidy_args, [])

    def test_rejects_flags_that_are_not_allowed(self):
        for flags in (
            "-load=plugin.so",
            "-fix",
            "-export-fixes=out.yaml",
            "-checks=*",
            "-clang-tidy-binary=/bin/sh",
            "header-filter=.*",
            "-extra-arg",
            "'-extra-arg=-DX",
        ):
            with (
                self.subTest(flags=flags),
                self.assertRaisesRegex(ValueError, "/flags"),
            ):
                parse_body(f"check\n/flags {flags}")


class TestMain(unittest.TestCase):
    def _run(self, body: str) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = os.path.join(tmp_dir, "env")
            open(env_file, "w").close()
            process = subprocess.run(
                [sys.executable, PARSE_ISSUE, env_file],
                input=body,
                capture_output=True,
                text=True,
                check=False,
            )
            return process, _read_env(env_file)

    def test_writes_inputs_to_the_environment_file(self):
        process, env = self._run(
            "https://github.com/llvm/llvm-project/pull/1 bugprone-x\n"
            "/flags '-extra-arg=-DMSG=a b'"
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(env["PR_LINK"], "https://github.com/llvm/llvm-project/pull/1")
        self.assertEqual(env["CHECK_NAME"], "bugprone-x")
        self.assertEqual(shlex.split(env["TIDY_ARGS"]), ["-extra-arg=-DMSG=a b"])
        self.assertEqual(env["COMPARE_BASELINE"], "false")

    def test_body_cannot_add_variables(self):
        # With a fixed delimiter such as EOF, this body would set BASH_ENV.
        process, env = self._run("check\nEOF\nBASH_ENV=/tmp/evil\nEOF")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertNotIn("BASH_ENV", env)
        self.assertEqual(env["CHECK_NAME"], "check")

    def test_reports_bad_flags(self):
        process, env = self._run("check\n/flags -load=plugin.so")
        self.assertEqual(process.returncode, 1)
        self.assertIn("-load=plugin.so", env["PARSE_ERROR"])
        self.assertNotIn("CHECK_NAME", env)

    def test_write_env_rejects_the_delimiter(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = os.path.join(tmp_dir, "env")
            write_env(env_file, {"A": "1"})
            with open(env_file) as f:
                delimiter = f.readline().split("<<", 1)[1].strip()
            self.assertTrue(delimiter.startswith("CTIT_"))


if __name__ == "__main__":
    unittest.main()
