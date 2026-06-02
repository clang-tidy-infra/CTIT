#!/usr/bin/env python3
"""Scan log files for clang-tidy crash signatures and write a structured summary."""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

CRASH_PATTERN = re.compile(
    r"Stack dump:|PLEASE submit a bug report|LLVM ERROR:|Assertion `"
)
_PROCESSING_PATTERN = re.compile(r"Processing '([^']+)' against")
_CONTEXT_LINES = 10
_PREFERRED_PROJECT = "llvm-project"


@dataclass
class _CrashExample:
    project: str
    lines: list[str]


@dataclass
class _CheckCrashes:
    count: int = 0
    examples: list[_CrashExample] = field(default_factory=list)


def _parse_log(path: str, project: str) -> dict[str, list[list[str]]]:
    """Return {check_name: [context_lines_per_crash]} for one log file."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError as e:
        print(f"Warning: could not read {path}: {e}", file=sys.stderr)
        return {}

    result: dict[str, list[list[str]]] = {}
    current_check = "unknown"

    for i, line in enumerate(lines):
        m = _PROCESSING_PATTERN.search(line)
        if m:
            current_check = m.group(1)
        if CRASH_PATTERN.search(line):
            context = lines[i : i + _CONTEXT_LINES + 1]
            result.setdefault(current_check, []).append(context)

    return result


def find_crashes(log_dir: str) -> dict[str, _CheckCrashes]:
    """Aggregate crashes across all log files, keyed by check name."""
    try:
        names = sorted(f for f in os.listdir(log_dir) if f.endswith(".log"))
    except OSError as e:
        print(f"Error reading log directory {log_dir}: {e}", file=sys.stderr)
        sys.exit(1)

    crashes: dict[str, _CheckCrashes] = {}

    for name in names:
        project = name[:-4]  # strip .log
        per_check = _parse_log(os.path.join(log_dir, name), project)
        for check, occurrences in per_check.items():
            info = crashes.setdefault(check, _CheckCrashes())
            info.count += len(occurrences)
            for ctx in occurrences:
                info.examples.append(_CrashExample(project=project, lines=ctx))

    return crashes


def _best_example(examples: list[_CrashExample]) -> _CrashExample:
    for ex in examples:
        if ex.project == _PREFERRED_PROJECT:
            return ex
    return examples[0]


def write_summary(crashes: dict[str, _CheckCrashes], output: str) -> None:
    lines: list[str] = ["## Crash Summary\n\n"]

    lines.append("| Check | Crashes |\n")
    lines.append("|-------|---------|\n")
    for check, info in sorted(crashes.items(), key=lambda x: -x[1].count):
        lines.append(f"| `{check}` | {info.count} |\n")
    lines.append("\n")

    lines.append("<details>\n<summary>Examples (click to expand)</summary>\n\n")
    for check, info in sorted(crashes.items()):
        ex = _best_example(info.examples)
        lines.append(f"### `{check}` ({ex.project})\n```\n")
        lines.extend(ex.lines)
        lines.append("```\n\n")
    lines.append("</details>\n")

    with open(output, "w") as f:
        f.writelines(lines)


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
        total = sum(info.count for info in crashes.values())
        print(
            f"Crashes found: {total} total across {len(crashes)} unique check(s). "
            f"Summary written to {args.summary_file}"
        )
    else:
        _set_github_output("crashes_found", "false")
        print("No crashes detected.")


if __name__ == "__main__":
    main()
