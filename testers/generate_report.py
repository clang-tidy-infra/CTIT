import os
import glob
import re
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Optional, TextIO

LOG_DIR = "logs"
OUTPUT_FILE = "issue.md"

# TODO: In the future, dynamically determine the commit hash for accurate linking.
PROJECT_URLS: Dict[str, str] = {
    "cppcheck": "https://github.com/danmar/cppcheck/blob/main",
}

@dataclass
class Issue:
    """Represents a single static analysis issue."""
    file_path: str
    line: int
    col: int
    severity: str
    message: str
    check_name: str
    context: Optional[str] = None

@dataclass
class ProjectResult:
    """Aggregated analysis results for a single project."""
    name: str
    warnings_count: int = 0
    errors_count: int = 0
    has_crash: bool = False
    issues: List[Issue] = field(default_factory=list)

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
    marker = f"test-projects/{project_name}/"
    if marker in full_path:
        return full_path.split(marker)[1]
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
    issue_pattern = re.compile(r'^(.+):(\d+):(\d+): (warning|error): (.+) \[(.+)\]$')

    try:
        with open(log_path, 'r', errors='replace') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            line = line.strip()

            # Check for tool crash indicators
            if "Segmentation fault" in line or "Stack dump:" in line:
                result.has_crash = True
                continue

            match = issue_pattern.match(line)
            if match:
                raw_path, line_num, col_num, severity, message, check_name = match.groups()

                # Update counts
                if severity == "warning":
                    result.warnings_count += 1
                elif severity == "error":
                    result.errors_count += 1

                # Extract context code (the line following the error message)
                context_code = None
                if i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    # simplistic check to avoid capturing paths or noise
                    if next_line and not next_line.startswith("/"):
                        context_code = next_line

                issue = Issue(
                    file_path=get_relative_path(raw_path, project_name),
                    line=int(line_num),
                    col=int(col_num),
                    severity=severity,
                    message=message,
                    check_name=check_name,
                    context=context_code
                )
                result.issues.append(issue)

    except IOError as e:
        print(f"Error reading {log_path}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Unexpected error parsing {log_path}: {e}", file=sys.stderr)

    return result


def write_summary_table(f: TextIO, results: List[ProjectResult]) -> None:
    """Writes the high-level summary table to the markdown file."""
    f.write("### 🧪 Clang-Tidy Integration Test Results\n\n")
    f.write("| Project | Status | Warnings | Errors | Crash |\n")
    f.write("| :--- | :--- | :--- | :--- | :--- |\n")

    for res in results:
        status_display = f"{res.status_emoji} {res.status_text}"
        crash_mark = "YES" if res.has_crash else "-"
        f.write(f"| **{res.name}** | {status_display} | {res.warnings_count} | {res.errors_count} | {crash_mark} |\n")

    f.write("\n---\n")

def write_project_details(f: TextIO, result: ProjectResult) -> None:
    """Writes the detailed breakdown of issues for a single project."""
    if not result.issues and not result.has_crash:
        return

    summary_text = f"🔍 {result.name} Details ({result.warnings_count} warnings, {result.errors_count} errors)"
    f.write(f"\n<details>\n<summary><strong>{summary_text}</strong></summary>\n\n")

    if result.has_crash:
        f.write("🚨 **CRASH DETECTED** in this project!\n\n")

    # Group issues by file
    files_dict: Dict[str, List[Issue]] = {}
    for issue in result.issues:
        files_dict.setdefault(issue.file_path, []).append(issue)

    base_url = PROJECT_URLS.get(result.name)

    for file_path, issues in files_dict.items():
        f.write(f"#### 📄 `{file_path}`\n")

        for issue in issues:
            # Create link if base URL is available
            if base_url:
                link = f"{base_url}/{file_path}#L{issue.line}"
                loc_text = f"[{issue.line}:{issue.col}]({link})"
            else:
                loc_text = f"{issue.line}:{issue.col}"

            icon = "🛑" if issue.severity == "error" else "⚠️"

            f.write(f"- {icon} **{loc_text}**: {issue.message} `[{issue.check_name}]`\n")

            if issue.context:
                f.write(f"  ```cpp\n  {issue.context}\n  ```\n")

    f.write("\n</details>\n")

def generate_markdown(results: List[ProjectResult], output_path: str) -> None:
    """
    Orchestrates the creation of the markdown report.

    Args:
        results: List of parsed project results.
        output_path: Destination path for the report.
    """
    try:
        with open(output_path, 'w') as f:
            write_summary_table(f, results)
            for res in results:
                write_project_details(f, res)
        print(f"Report generated: {output_path}")
    except IOError as e:
        print(f"Error writing report to {output_path}: {e}", file=sys.stderr)


def main():
    if not os.path.exists(LOG_DIR):
        print(f"Log directory '{LOG_DIR}' not found.", file=sys.stderr)
        sys.exit(1)

    log_files = glob.glob(os.path.join(LOG_DIR, "*.log"))
    if not log_files:
        print(f"No log files found in '{LOG_DIR}'.", file=sys.stderr)
        sys.exit(0)

    all_results = [parse_log_file(log) for log in log_files]
    all_results.sort(key=lambda x: x.name)

    generate_markdown(all_results, OUTPUT_FILE)

if __name__ == "__main__":
    main()
