import unittest
from unittest.mock import patch

from ctit import main


class TestCtitCli(unittest.TestCase):
    def test_help_exits_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_clone_help(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["clone", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_report_help(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["report", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_analyze_help(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["analyze", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    @patch("ctit.clone_projects")
    def test_clone_calls_clone_projects(self, mock_clone):
        main(["clone", "--work-dir", "/tmp/out", "--config", "custom.json"])
        mock_clone.assert_called_once_with(
            work_dir="/tmp/out", config_path="custom.json"
        )

    @patch("ctit.configure")
    def test_configure_calls_configure(self, mock_configure):
        main(["configure"])
        mock_configure.assert_called_once()

    @patch("ctit.analyze")
    def test_analyze_calls_analyze(self, mock_analyze):
        main(["analyze", "--check-name", "bugprone-*"])
        mock_analyze.assert_called_once_with(
            check_name="bugprone-*",
            tidy_config=None,
        )

    @patch("ctit.analyze")
    def test_analyze_with_tidy_config(self, mock_analyze):
        main(
            [
                "analyze",
                "--check-name",
                "readability-*",
                "--tidy-config",
                "VariableCase: camelBack",
            ]
        )
        mock_analyze.assert_called_once_with(
            check_name="readability-*",
            tidy_config="VariableCase: camelBack",
        )

    @patch("ctit.generate_report")
    def test_report_calls_generate_report(self, mock_report):
        main(["report", "--log-dir", "/tmp/logs", "--output", "/tmp/out.md"])
        mock_report.assert_called_once_with(log_dir="/tmp/logs", output="/tmp/out.md")

    def test_no_subcommand_exits_nonzero(self):
        with self.assertRaises(SystemExit) as ctx:
            main([])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
