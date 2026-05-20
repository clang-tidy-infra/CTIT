#!/usr/bin/env python3
"""CTIT - Clang Tidy Integration Tester CLI."""

import argparse
import argcomplete
import sys

from testers.analyze import DEFAULT_CLANG_TIDY_BIN, DEFAULT_LOG_DIR, analyze, configure
from testers.clang_tests import (
    DEFAULT_CLANG_TEST_LOG_DIR,
    DEFAULT_CLANG_TEST_OUTPUT,
    DEFAULT_LLVM_DIR,
    DEFAULT_TEST_TIMEOUT,
    run_clang_tests,
)
from testers.clone_projects import clone_projects
from testers.config import CONFIG_FILE, PROJECTS_DIR
from testers.generate_report import (
    DEFAULT_OUTPUT_FILE,
    generate_report,
    generate_template,
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="ctit",
        description="Clang Tidy Integration Tester",
    )
    subparsers = parser.add_subparsers(dest="command")

    clone_parser = subparsers.add_parser(
        "clone",
        help="Clone test projects defined in projects.json",
    )
    clone_parser.add_argument(
        "--work-dir",
        default=PROJECTS_DIR,
        help=f"Directory to clone projects into (default: {PROJECTS_DIR})",
    )
    clone_parser.add_argument(
        "--config",
        default=CONFIG_FILE,
        help="Path to config file (default: bundled projects.json)",
    )

    configure_parser = subparsers.add_parser(
        "configure",
        help="Configure and build test projects for analysis",
    )
    configure_parser.add_argument(
        "--work-dir",
        default=PROJECTS_DIR,
        help=f"Directory containing cloned projects (default: {PROJECTS_DIR})",
    )
    configure_parser.add_argument(
        "--config",
        default=CONFIG_FILE,
        help="Path to config file (default: bundled projects.json)",
    )

    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Run clang-tidy analysis on test projects",
    )
    analyze_parser.add_argument(
        "--check-name",
        required=True,
        help="Clang-tidy check name pattern (e.g. bugprone-*)",
    )
    analyze_parser.add_argument(
        "--clang-tidy-binary",
        default=DEFAULT_CLANG_TIDY_BIN,
        help=f"Path to clang-tidy binary (default: {DEFAULT_CLANG_TIDY_BIN})",
    )
    analyze_parser.add_argument(
        "--run-tidy-script",
        default=None,
        help="Path to run-clang-tidy script (default: auto-detect from PATH)",
    )
    analyze_parser.add_argument(
        "--tidy-config",
        default=None,
        help="Extra clang-tidy configuration string",
    )
    analyze_parser.add_argument(
        "--work-dir",
        default=PROJECTS_DIR,
        help=f"Directory containing cloned projects (default: {PROJECTS_DIR})",
    )
    analyze_parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Directory for analysis logs (default: {DEFAULT_LOG_DIR})",
    )
    analyze_parser.add_argument(
        "--config",
        default=CONFIG_FILE,
        help="Path to config file (default: bundled projects.json)",
    )

    clang_tests_parser = subparsers.add_parser(
        "clang-tests",
        help="Run clang-tidy on LLVM's clang test inputs",
    )
    clang_tests_parser.add_argument(
        "--check-name",
        required=True,
        help="Clang-tidy check name pattern (e.g. bugprone-*)",
    )
    clang_tests_parser.add_argument(
        "--clang-tidy-binary",
        default=DEFAULT_CLANG_TIDY_BIN,
        help=f"Path to clang-tidy binary (default: {DEFAULT_CLANG_TIDY_BIN})",
    )
    clang_tests_parser.add_argument(
        "--llvm-dir",
        default=DEFAULT_LLVM_DIR,
        help=f"Path to llvm-project checkout (default: {DEFAULT_LLVM_DIR})",
    )
    clang_tests_parser.add_argument(
        "--tidy-config",
        default=None,
        help="Extra clang-tidy configuration string",
    )
    clang_tests_parser.add_argument(
        "--log-dir",
        default=DEFAULT_CLANG_TEST_LOG_DIR,
        help=f"Directory for per-file logs (default: {DEFAULT_CLANG_TEST_LOG_DIR})",
    )
    clang_tests_parser.add_argument(
        "--output",
        default=DEFAULT_CLANG_TEST_OUTPUT,
        help=f"Output markdown file (default: {DEFAULT_CLANG_TEST_OUTPUT})",
    )
    clang_tests_parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TEST_TIMEOUT,
        help=f"Timeout per test file in seconds (default: {DEFAULT_TEST_TIMEOUT})",
    )
    clang_tests_parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Number of test files to run in parallel (default: 1)",
    )
    clang_tests_parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra compiler argument passed after '--' (can be repeated)",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Generate markdown report from clang-tidy logs",
    )
    report_parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Directory containing log files (default: {DEFAULT_LOG_DIR})",
    )
    report_parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"Output markdown file (default: {DEFAULT_OUTPUT_FILE})",
    )

    report_template_parser = subparsers.add_parser(
        "report-template",
        help="Generate the pre-filled FP-analysis template (report.md) for the AI to complete",
    )
    report_template_parser.add_argument(
        "--log-dir",
        default=DEFAULT_LOG_DIR,
        help=f"Directory containing log files (default: {DEFAULT_LOG_DIR})",
    )
    report_template_parser.add_argument(
        "--output",
        default="report.md",
        help="Output template file (default: report.md)",
    )

    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_usage(sys.stderr)
        sys.exit(1)
    elif args.command == "clone":
        clone_projects(work_dir=args.work_dir, config_path=args.config)
    elif args.command == "configure":
        configure(work_dir=args.work_dir, config_path=args.config)
    elif args.command == "analyze":
        analyze(
            check_name=args.check_name,
            tidy_config=args.tidy_config,
            clang_tidy_bin=args.clang_tidy_binary,
            run_tidy_script=args.run_tidy_script,
            work_dir=args.work_dir,
            log_dir=args.log_dir,
            config_path=args.config,
        )
    elif args.command == "clang-tests":
        run_clang_tests(
            check_name=args.check_name,
            tidy_config=args.tidy_config,
            clang_tidy_bin=args.clang_tidy_binary,
            llvm_dir=args.llvm_dir,
            log_dir=args.log_dir,
            output=args.output,
            timeout=args.timeout,
            jobs=args.jobs,
            extra_args=args.extra_arg,
        )
    elif args.command == "report":
        generate_report(log_dir=args.log_dir, output=args.output)
    elif args.command == "report-template":
        generate_template(log_dir=args.log_dir, output=args.output)


if __name__ == "__main__":
    main()
