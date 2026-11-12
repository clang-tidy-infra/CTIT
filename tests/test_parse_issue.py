import json
import unittest

from parse_issue import parse_body


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

    def _analyzer_options(self, body):
        return json.loads(parse_body(body).tidy_config)["CheckOptions"]

    def test_analyzer_option_takes_a_colon(self):
        options = self._analyzer_options("""
        https://github.com/llvm/llvm-project/pull/789 clang-analyzer-optin.cplusplus.UninitializedObject
        Pedantic: true
        """)
        self.assertEqual(
            options,
            {"clang-analyzer-optin.cplusplus.UninitializedObject:Pedantic": "true"},
        )

    def test_analyzer_option_of_another_checker(self):
        # unix.Malloc reads its options from the modeling checker behind it.
        for line in (
            "unix.DynamicMemoryModeling:Optimistic: true",
            "clang-analyzer-unix.DynamicMemoryModeling:Optimistic: true",
            "unix.DynamicMemoryModeling : Optimistic : true",
        ):
            with self.subTest(line=line):
                options = self._analyzer_options(
                    f"clang-analyzer-unix.Malloc\n{line}\n"
                )
                self.assertEqual(
                    options,
                    {"clang-analyzer-unix.DynamicMemoryModeling:Optimistic": "true"},
                )

    def test_analyzer_option_value_keeps_its_colons(self):
        options = self._analyzer_options(
            "clang-analyzer-core.NullDereference\n"
            "core.NullDereference:Path: a:b\n"
            "Other: c:d\n"
        )
        self.assertEqual(
            options,
            {
                "clang-analyzer-core.NullDereference:Path": "a:b",
                "clang-analyzer-core.NullDereference:Other": "c:d",
            },
        )

    def test_static_analyzer_only_for_globs_that_reach_it(self):
        for check_name, expected in (
            ("clang-analyzer-unix.Malloc", True),
            ("clang-analyzer-alpha.*", True),
            ("clang-analyzer-*", True),
            ("clang-*", True),
            ("*", True),
            ("bugprone-*,clang-analyzer-core.NullDereference", True),
            ("bugprone-argument-comment", False),
            ("bugprone-*,-clang-analyzer-*", False),
            ("*,-clang-analyzer-*", False),
            ("clang-diagnostic-lifetime-safety-*", False),
            ("clang-diagnostic-error", False),
        ):
            with self.subTest(check_name=check_name):
                self.assertEqual(parse_body(check_name).static_analyzer, expected)

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


if __name__ == "__main__":
    unittest.main()
