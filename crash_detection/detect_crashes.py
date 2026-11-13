#!/usr/bin/env python3
"""Scan log files for clang-tidy crash signatures and write a structured summary."""

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

CRASH_PATTERN = re.compile(
    r"Stack dump:|PLEASE submit a bug report to https|LLVM ERROR:|Assertion `"
)
# A killed process can print nothing but this, without any LLVM crash banner.
SEGFAULT_PATTERN = re.compile(r"Segmentation fault")
# Pattern for lines such as "ASTMatcher: Processing '<check>' against:".
_PROCESSING_PATTERN = re.compile(r"(?:Processing|Matching) '([^']+)' against")
# Stack dump item 1 describes the phase when the crash occurred.
_STACK_PHASE = re.compile(r"^\s*1\.\s+(.+)$")
# Stack dump items of the static analyzer, e.g.
#   2.	While analyzing stack:
#   	#0 Calling inlined(int, float) at line 17
#   	#1 Calling test()
#   3.	/src/a.cpp:13:3: Error evaluating statement
# See PrettyStackTraceStackFrame.h and ExprEngine.cpp in clang/lib/StaticAnalyzer.
_ANALYZING_STACK = re.compile(r"^\s*\d+\.\s+While analyzing stack:")
_ANALYZED_CALL = re.compile(r"^\s*#\d+ Calling (.+?)(?: at line .*)?$")
_ANALYZER_ERROR = re.compile(
    r"^\s*\d+\.\s+(?:(.+):(\d+):\d+: )?(Error evaluating .+?)\s*$"
)
# Catches analyzer crashes that leave none of the items above, e.g. in a checker
# building its bug report. Needs a symbolized backtrace.
_ANALYZER_FRAME = re.compile(r"\bclang::ento::")
MAX_CRASH_LINES = 30
UNKNOWN_CHECK = "unknown"
ANALYZER_CRASH = "clang-analyzer"
_PREFERRED_PROJECT = "llvm-project"


@dataclass
class Crash:
    """A single crash occurrence with the log lines that describe it."""

    check: str
    lines: list[str]


@dataclass
class AnalyzerSite:
    """Where in the analyzed code the static analyzer crashed."""

    function: str | None = None
    file_path: str | None = None
    line: int | None = None
    phase: str | None = None


def analyzer_site(context: list[str]) -> AnalyzerSite | None:
    """Return where the analyzer crashed, or None without analyzer items."""
    site = AnalyzerSite()
    found = False
    in_stack = False
    # Later items are deeper, so the first call of the last stack and the
    # last error win.
    for line in context:
        if _ANALYZING_STACK.match(line):
            found, in_stack, site.function = True, True, None
        elif in_stack and (call := _ANALYZED_CALL.match(line)):
            site.function = site.function or call.group(1)
        else:
            in_stack = False
            error = _ANALYZER_ERROR.match(line)
            if error:
                found = True
                site.phase = error.group(3)
                if error.group(1):
                    site.file_path, site.line = error.group(1), int(error.group(2))
    return site if found else None


def check_from_context(context: list[str]) -> str:
    """Extract the crashing check name from the stack dump context.

    An analyzer crash has no ASTMatcher check, so it is named after the
    analyzer and the phase it crashed in. Other crashes without one, e.g.
    during parsing or preprocessing, fall back to the stack dump phase (item 1).
    """
    for line in context:
        m = _PROCESSING_PATTERN.search(line)
        if m:
            return m.group(1)
    site = analyzer_site(context)
    if site is not None and site.phase:
        return f"{ANALYZER_CRASH} ({site.phase})"
    if site is not None or any(_ANALYZER_FRAME.search(line) for line in context):
        return ANALYZER_CRASH
    for line in context:
        m = _STACK_PHASE.match(line)
        if m:
            return f"{UNKNOWN_CHECK} ({m.group(1).strip()})"
    return UNKNOWN_CHECK


def find_crashes_in_lines(lines: list[str]) -> list[Crash]:
    """Return every crash found in *lines*, in the order they occurred.

    Each crash keeps up to MAX_CRASH_LINES log lines from its trigger, enough
    for the stack dump to name the file and the crashing check.
    """
    crashes: list[Crash] = []
    i = 0
    while i < len(lines):
        if CRASH_PATTERN.search(lines[i]):
            context = lines[i : i + MAX_CRASH_LINES]
            crashes.append(Crash(check=check_from_context(context), lines=context))
            i += len(context)
        else:
            i += 1

    return crashes


def group_by_check(crashes: list[Crash]) -> dict[str, list[Crash]]:
    """Group crashes by the check they were attributed to."""
    grouped: dict[str, list[Crash]] = {}
    for crash in crashes:
        grouped.setdefault(crash.check, []).append(crash)
    return grouped


@dataclass
class _CrashExample:
    project: str
    lines: list[str]


@dataclass
class _CheckCrashes:
    count: int = 0
    # At most one example per project to avoid storing thousands of duplicates.
    examples: list[_CrashExample] = field(default_factory=list)


def _parse_log(path: str) -> dict[str, list[Crash]]:
    """Return {check_name: [crashes]} for one log file."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError as e:
        print(f"Warning: could not read {path}: {e}", file=sys.stderr)
        return {}

    result: dict[str, list[Crash]] = {}
    for crash in find_crashes_in_lines(lines):
        result.setdefault(crash.check, []).append(crash)
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
        per_check = _parse_log(os.path.join(log_dir, name))
        for check, occurrences in per_check.items():
            info = crashes.setdefault(check, _CheckCrashes())
            info.count += len(occurrences)
            seen_projects = {ex.project for ex in info.examples}
            if project not in seen_projects and occurrences:
                info.examples.append(
                    _CrashExample(project=project, lines=occurrences[0].lines)
                )

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
