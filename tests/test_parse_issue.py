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

    def test_empty_body(self):
        with self.assertRaises(ValueError):
            parse_body("")

    def test_malformed_first_line(self):
        with self.assertRaises(ValueError):
            parse_body("https://github.com/llvm/llvm-project/pull/789")


if __name__ == "__main__":
    unittest.main()
