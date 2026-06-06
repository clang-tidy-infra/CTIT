#!/usr/bin/env python3
"""CTIT - Clang Tidy Integration Tester CLI."""

import argparse
import argcomplete
import sys

from testers.analyze import DEFAULT_CLANG_TIDY_BIN, DEFAULT_LOG_DIR, analyze, configure
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
    analyze_parser.add_argument(
        "--skip-headers",
        action="store_true",
        help="Pass -header-filter= to clang-tidy so no header diagnostics are emitted",
    )
    analyze_parser.add_argument(
        "--enable-check-profile",
        action="store_true",
        default=False,
        help="Enable per-check timing profiles (appended to logs)",
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
            skip_headers=args.skip_headers,
            profile=args.enable_check_profile,
        )
    elif args.command == "report":
        generate_report(log_dir=args.log_dir, output=args.output)
    elif args.command == "report-template":
        generate_template(log_dir=args.log_dir, output=args.output)


if __name__ == "__main__":
    main()
