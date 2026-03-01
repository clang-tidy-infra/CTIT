#!/usr/bin/env python3
"""CTIT - Clang Tidy Integration Tester CLI."""

import argparse
import argcomplete
import sys

from testers.analyze import analyze, configure
from testers.clone_projects import clone_projects
from testers.config import CONFIG_FILE, PROJECTS_DIR
from testers.generate_report import (
    DEFAULT_LOG_DIR,
    DEFAULT_OUTPUT_FILE,
    generate_report,
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
        help=f"Path to config file (default: {CONFIG_FILE})",
    )

    subparsers.add_parser(
        "configure",
        help="Configure and build test projects for analysis",
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
        "--tidy-config",
        default=None,
        help="Extra clang-tidy configuration string",
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

    argcomplete.autocomplete(parser)
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_usage(sys.stderr)
        sys.exit(1)
    elif args.command == "clone":
        clone_projects(work_dir=args.work_dir, config_path=args.config)
    elif args.command == "configure":
        configure()
    elif args.command == "analyze":
        analyze(
            check_name=args.check_name,
            tidy_config=args.tidy_config,
        )
    elif args.command == "report":
        generate_report(log_dir=args.log_dir, output=args.output)


if __name__ == "__main__":
    main()
