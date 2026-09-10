#!/usr/bin/env python3
import glob
import os
import re
import sys
from dataclasses import dataclass, field
from typing import TextIO

from crash_detection.detect_crashes import (
    Crash,
    SEGFAULT_PATTERN,
    find_crashes_in_lines,
    group_by_check,
)
from testers.config import load_projects

DEFAULT_LOG_DIR = "logs"
DEFAULT_OUTPUT_FILE = "issue.md"
MAX_CRASH_EXAMPLES = 3


@dataclass
class Issue:
    """Represents a single static analysis issue."""

    file_path: str
    line: int
    col: int
    severity: str
    message: str
    check_name: str
    context: str | None = None


@dataclass
class ProjectResult:
    """Aggregated analysis results for a single project."""

    name: str
    warnings_count: int = 0
    errors_count: int = 0
    has_crash: bool = False
    issues: list[Issue] = field(default_factory=list)
    crashes: list[Crash] = field(default_factory=list)
    elapsed_seconds: float | None = None

    @property
    def status_emoji(self) -> str:
        """Returns a status emoji based on the result."""
        if self.has_crash:
            return "💥"
        if self.errors_count > 0:
            return "❌"
        if self.warnings_count > 0:
            return "⚠️"
        return "✅"

    @property
    def status_text(self) -> str:
        """Returns a human-readable status string."""
        if self.has_crash:
            return "CRASH"
        if self.errors_count > 0:
            return "Fail"
        if self.warnings_count > 0:
            return "Warnings"
        return "Pass"


def get_relative_path(full_path: str, project_name: str) -> str:
    """
    Extracts the relative path of a file within the project.

    Args:
        full_path: The absolute or relative path from the log.
        project_name: The name of the project.

    Returns:
        The relative path string.
    """
    markers = [
        f"test_projects/{project_name}/",
        f"test-projects/{project_name}/",
        f"{project_name}/",
    ]
    for marker in markers:
        if marker in full_path:
            return full_path.split(marker, 1)[1]
    return os.path.basename(full_path)


def parse_log_file(log_path: str) -> ProjectResult:
    """
    Parses a single tool log file to extract analysis results.

    Args:
        log_path: Path to the log file.

    Returns:
        A ProjectResult object containing the parsed data.
    """
    project_name = os.path.basename(log_path).replace(".log", "")
    result = ProjectResult(name=project_name)

    # Regex to capture standard clang-tidy output format:
    # Example: /path/to/file.cpp:10:5: warning: message [check-name]
    issue_pattern = re.compile(r"^(.+):(\d+):(\d+): (warning|error): (.+) \[(.+)\]$")

    # Deduplicate by (file_path, line, col, check_name)
    seen: set[tuple[str, int, int, str]] = set()

    try:
        with open(log_path, errors="replace") as f:
            lines = f.readlines()

        result.crashes = find_crashes_in_lines(lines)
        result.has_crash = bool(result.crashes)

        for i, line in enumerate(lines):
            line = line.strip()

            timing = re.fullmatch(r"CTIT analysis elapsed seconds: (\d+\.\d+)", line)
            if timing:
                result.elapsed_seconds = float(timing.group(1))
                continue

            # Check for tool crash indicators
            if SEGFAULT_PATTERN.search(line):
                result.has_crash = True
                continue

            match = issue_pattern.match(line)
            if match:
                raw_path, line_num, col_num, severity, message, check_name = (
                    match.groups()
                )

                rel_path = get_relative_path(raw_path, project_name)

                key = (rel_path, int(line_num), int(col_num), check_name)
                if key in seen:
                    continue
                seen.add(key)

                # Update counts
                if severity == "warning":
                    result.warnings_count += 1
                elif severity == "error":
                    result.errors_count += 1

                # Extract context code (the line following the error message)
                context_code = None
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    # simplistic check to avoid capturing paths or noise
                    if next_line and not next_line.startswith("/"):
                        context_code = next_line

                issue = Issue(
                    file_path=rel_path,
                    line=int(line_num),
                    col=int(col_num),
                    severity=severity,
                    message=message,
                    check_name=check_name,
                    context=context_code,
                )
                result.issues.append(issue)

    except OSError as e:
        print(f"Error reading {log_path}: {e}", file=sys.stderr)

    return result


def write_summary_table(f: TextIO, results: list[ProjectResult]) -> None:
    """Writes the high-level summary table to the markdown file."""
    f.write("### Clang-Tidy Integration Test Results\n\n")
    f.write("| Project | Status | Warnings | Errors | Crash | Full tidy time (s) |\n")
    f.write("| :--- | :--- | :--- | :--- | :--- | ---: |\n")

    for res in results:
        status_display = f"{res.status_emoji} {res.status_text}"
        crash_mark = "YES" if res.has_crash else "-"
        elapsed = (
            f"{res.elapsed_seconds:.2f}" if res.elapsed_seconds is not None else "—"
        )
        f.write(
            f"| **{res.name}** | {status_display} "
            f"| {res.warnings_count} | {res.errors_count} "
            f"| {crash_mark} | {elapsed} |\n"
        )

    f.write("\n---\n")


def write_project_details(
    f: TextIO, result: ProjectResult, project_urls: dict[str, str]
) -> None:
    """Writes the detailed breakdown of issues for a single project."""
    if not result.issues and not result.has_crash:
        return

    summary_text = f"{result.name} Details ({result.warnings_count} warnings, {result.errors_count} errors)"
    f.write(f"\n<details>\n<summary><strong>{summary_text}</strong></summary>\n\n")

    if result.has_crash:
        write_crash_details(f, result)

    base_url = project_urls.get(result.name)

    for issue in result.issues:
        if base_url:
            link = f"{base_url}/{issue.file_path}#L{issue.line}"
            loc_text = f"[{issue.file_path}:{issue.line}]({link})"
        else:
            loc_text = f"{issue.file_path}:{issue.line}"

        icon = "🛑" if issue.severity == "error" else "⚠️"

        f.write(f"#### {icon} {loc_text}\n")
        f.write(f"{issue.message} `[{issue.check_name}]`\n")

        if issue.context:
            f.write(f"  ```cpp\n  {issue.context}\n  ```\n")

    f.write("\n</details>\n")


def write_crash_details(f: TextIO, result: ProjectResult) -> None:
    """Writes the crash banner and a stack dump excerpt per crashing check."""
    total = len(result.crashes)
    count_text = f" ({total} crash(es))" if total else ""
    f.write(f"🚨 **CRASH DETECTED** in this project!{count_text}\n\n")

    grouped = sorted(
        group_by_check(result.crashes).items(), key=lambda item: -len(item[1])
    )

    for check, crashes in grouped[:MAX_CRASH_EXAMPLES]:
        f.write(f"**`{check}`** - {len(crashes)} crash(es), first occurrence:\n\n")
        f.write("```\n")
        f.writelines(line.rstrip("\n") + "\n" for line in crashes[0].lines)
        f.write("```\n\n")

    remaining = len(grouped) - MAX_CRASH_EXAMPLES
    if remaining > 0:
        f.write(
            f"_...and {remaining} more crashing check(s); "
            "see the full logs in the workflow artifacts._\n\n"
        )


def write_ai_report_template(
    f: TextIO,
    results: list[ProjectResult],
    project_urls: dict[str, str],
) -> None:
    """Writes a pre-filled FP-analysis table for the AI to complete in place.

    One row per warning; the AI replaces the TBD cells in Verdict and Rationale
    and the TBD counts in the Summary line. Other columns must stay untouched.
    """
    f.write("### AI FP Analysis\n\n")
    f.write("| # | Project | Verdict | Rationale | Location |\n")
    f.write("| :--- | :--- | :--- | :--- | :--- |\n")

    n = 0
    for res in results:
        base_url = project_urls.get(res.name)
        for issue in res.issues:
            n += 1
            if base_url:
                link = f"{base_url}/{issue.file_path}#L{issue.line}"
                loc_text = f"[{issue.file_path}:{issue.line}]({link})"
            else:
                loc_text = f"{issue.file_path}:{issue.line}"
            f.write(f"| {n} | {res.name} | TBD | TBD | {loc_text} |\n")

    if n == 0:
        f.write("\n_No warnings to analyze._\n")
        return

    f.write(
        f"\n**Summary**: TBD True Positives, TBD False Positives, "
        f"TBD Uncertain out of {n} total warnings.\n"
    )


def generate_markdown(
    results: list[ProjectResult],
    output_path: str,
    project_urls: dict[str, str] | None = None,
    baseline_results: list[ProjectResult] | None = None,
    baseline_revision: str | None = None,
) -> None:
    """Writes the human-facing warnings report (issue.md)."""
    if project_urls is None:
        project_urls = {}

    try:
        with open(output_path, "w") as f:
            if baseline_revision:
                f.write(f"Baseline LLVM revision: `{baseline_revision}`\n\n")
                if baseline_results is None:
                    f.write(
                        "Check unavailable in baseline; baseline analysis skipped.\n\n"
                    )
            if baseline_results is not None:
                f.write("## PR results\n\n")
            write_summary_table(f, results)
            if baseline_results is not None:
                f.write("## Baseline results\n\n")
                write_summary_table(f, baseline_results)
                f.write("## PR diagnostics\n\n")
            for res in results:
                write_project_details(f, res, project_urls)
            if baseline_results is not None:
                f.write("## Baseline diagnostics\n\n")
                for res in baseline_results:
                    write_project_details(f, res, project_urls)
        print(f"Report generated: {output_path}")
    except OSError as e:
        print(f"Error writing report to {output_path}: {e}", file=sys.stderr)


def _load_results(log_dir: str) -> tuple[list[ProjectResult], dict[str, str]]:
    if not os.path.exists(log_dir):
        print(f"Log directory '{log_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    log_files = [
        p
        for p in glob.glob(os.path.join(log_dir, "*.log"))
        if os.path.basename(p) != "progress.log"
    ]
    if not log_files:
        print(f"No log files found in '{log_dir}'.", file=sys.stderr)
        sys.exit(0)

    try:
        projects = load_projects()
        project_urls = {p.name: p.browse_url for p in projects}
    except (OSError, KeyError):
        project_urls = {}

    results = [parse_log_file(log) for log in log_files]
    results.sort(key=lambda x: x.name)
    return results, project_urls


def generate_report(
    log_dir: str,
    output: str,
    baseline_log_dir: str | None = None,
    baseline_revision: str | None = None,
) -> None:
    results, project_urls = _load_results(log_dir)
    baseline_results = None
    if baseline_log_dir is not None:
        baseline_results, _ = _load_results(baseline_log_dir)
    generate_markdown(
        results, output, project_urls, baseline_results, baseline_revision
    )


def generate_template(log_dir: str, output: str) -> None:
    """Writes the pre-filled FP-analysis template for the AI to complete."""
    results, project_urls = _load_results(log_dir)
    try:
        with open(output, "w") as f:
            write_ai_report_template(f, results, project_urls)
        print(f"FP-analysis template generated: {output}")
    except OSError as e:
        print(f"Error writing template to {output}: {e}", file=sys.stderr)
