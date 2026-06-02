#!/usr/bin/env python3
"""Scan log files for clang-tidy crash signatures and write a markdown summary."""

import argparse
import os
import re
import sys

CRASH_PATTERN = re.compile(
    r"Stack dump:|PLEASE submit a bug report|LLVM ERROR:|Assertion `"
)
_CONTEXT_LINES = 10
_MAX_CONTEXT_PER_FILE = 100


def _extract_context(lines: list[str]) -> list[str]:
    included: set[int] = set()
    for i, line in enumerate(lines):
        if CRASH_PATTERN.search(line):
            for j in range(i, min(i + _CONTEXT_LINES + 1, len(lines))):
                included.add(j)
                if len(included) >= _MAX_CONTEXT_PER_FILE:
                    break
        if len(included) >= _MAX_CONTEXT_PER_FILE:
            break
    return [lines[i] for i in sorted(included)]


def find_crashes(log_dir: str) -> dict[str, list[str]]:
    """Return {filepath: context_lines} for each log file containing a crash."""
    try:
        names = sorted(f for f in os.listdir(log_dir) if f.endswith(".log"))
    except OSError as e:
        print(f"Error reading log directory {log_dir}: {e}", file=sys.stderr)
        sys.exit(1)

    crashes: dict[str, list[str]] = {}
    for name in names:
        path = os.path.join(log_dir, name)
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError as e:
            print(f"Warning: could not read {path}: {e}", file=sys.stderr)
            continue

        context = _extract_context(lines)
        if context:
            crashes[path] = context

    return crashes


def write_summary(crashes: dict[str, list[str]], output: str) -> None:
    with open(output, "w") as f:
        f.write("## Crash Summary\n\n")
        for path, lines in crashes.items():
            f.write(f"### `{path}`\n```\n")
            f.writelines(lines)
            f.write("```\n\n")


def _set_github_output(key: str, value: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-dir", default="logs", help="Directory containing .log files"
    )
    parser.add_argument(
        "--summary-file", default="crash-summary.md", help="Output markdown summary"
    )
    args = parser.parse_args()

    crashes = find_crashes(args.log_dir)

    if crashes:
        write_summary(crashes, args.summary_file)
        _set_github_output("crashes_found", "true")
        print(
            f"Crashes found in {len(crashes)} log file(s). Summary written to {args.summary_file}"
        )
    else:
        _set_github_output("crashes_found", "false")
        print("No crashes detected.")


if __name__ == "__main__":
    main()
