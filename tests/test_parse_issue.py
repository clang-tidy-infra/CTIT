import unittest
import json
from parse_issue import parse_body


class TestParseIssue(unittest.TestCase):
    def test_simple_parse(self):
        body = """
        https://github.com/llvm/llvm-project/pull/12345 bugprone-argument-comment
        """
        pr_link, check_name, tidy_config = parse_body(body)
        self.assertEqual(pr_link, "https://github.com/llvm/llvm-project/pull/12345")
        self.assertEqual(check_name, "bugprone-argument-comment")
        self.assertEqual(tidy_config, "")

    def test_readability_naming_options(self):
        body = """
        https://github.com/llvm/llvm-project/pull/123 readability-identifier-naming
        VariableCase: camelBack
        VariablePrefix: v_
        IgnoreFailedSplit: true
        """
        pr_link, check_name, tidy_config = parse_body(body)
        self.assertEqual(pr_link, "https://github.com/llvm/llvm-project/pull/123")
        self.assertEqual(check_name, "readability-identifier-naming")

        config = json.loads(tidy_config)
        opts = config["CheckOptions"]
        self.assertEqual(
            opts["readability-identifier-naming.VariableCase"], "camelBack"
        )
        self.assertEqual(opts["readability-identifier-naming.VariablePrefix"], "v_")
        self.assertEqual(opts["readability-identifier-naming.IgnoreFailedSplit"], True)

    def test_modernize_auto_options(self):
        body = """
        https://github.com/llvm/llvm-project/pull/456 readability-identifier-naming
        MinTypeNameLength: 5
        RemoveStars: false
        """
        pr_link, check_name, tidy_config = parse_body(body)
        self.assertEqual(check_name, "readability-identifier-naming")

        opts = json.loads(tidy_config)["CheckOptions"]
        self.assertEqual(opts["readability-identifier-naming.MinTypeNameLength"], 5)
        self.assertEqual(opts["readability-identifier-naming.RemoveStars"], False)

    def test_full_prefix_consistency(self):
        body = """
        https://github.com/llvm/llvm-project/pull/789 readability-identifier-naming
        readability-identifier-naming.StrictMode: true
        """
        _, check_name, tidy_config = parse_body(body)
        self.assertEqual(check_name, "readability-identifier-naming")

        config = json.loads(tidy_config)
        self.assertIn(
            "readability-identifier-naming.StrictMode", config["CheckOptions"]
        )
        self.assertNotIn(
            "readability-identifier-naming.readability-identifier-naming.StrictMode",
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
