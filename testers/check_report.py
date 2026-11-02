"""Check that the AI triage looked at every warning in report.md.

A row passes when it has a TP, FP, or Uncertain verdict and its rationale
names something from the flagged code: a variable, container, type, or
function in the flagged statement or the few lines after it. A bare
"Same as #N" names nothing and fails, so the agent cannot fill rows without
reading them. Rows whose flagged statement has nothing specific to name pass
with any rationale.
"""

from __future__ import annotations

import os
import re
import sys

from testers.generate_report import Issue
from testers.reproduce import report_rows

VERDICTS = {"TP", "FP", "UNCERTAIN"}
# The longest flagged statement read, and how many lines after it a rationale
# may also cite, e.g. the container a loop body indexes.
MAX_STATEMENT_LINES = 10
CONTEXT_LINES = 3
COMMENT_RE = re.compile(r"//.*|/\*.*?\*/")
# One report.md row: number, project, verdict, rationale, location.
ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|[^|]*\|([^|]*)\|(.*)\|[^|]*\|\s*$")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Too common in source lines to show that the agent read this one.
COMMON = {
    "auto", "begin", "bool", "break", "case", "cbegin", "cend", "char",
    "const", "const_iterator", "continue", "do", "double", "else", "end",
    "false", "float", "for", "if", "int", "iterator", "long", "nullptr",
    "rbegin", "rend", "return", "short", "signed", "size", "size_t", "static",
    "std", "string", "true", "unsigned", "vector", "void", "while",
}  # fmt: skip


def flagged_code(project: str, issue: Issue, work_dir: str) -> tuple[str, str]:
    """Returns the flagged statement and the few lines after it.

    The statement runs from the flagged line until its parentheses balance,
    so a `for` split over several lines is whole. Without the project
    sources, both are clang-tidy's copy of the flagged line.
    """
    path = os.path.join(work_dir, project, issue.file_path)
    try:
        with open(path, errors="replace") as source:
            lines = source.readlines()[issue.line - 1 :]
    except OSError:
        # clang-tidy prefixes the line with its number, e.g. "  68 | for (...".
        line = (issue.context or "").split("|", 1)[-1]
        return line, line
    lines = [COMMENT_RE.sub("", line) for line in lines[:MAX_STATEMENT_LINES]]
    depth = 0
    end = len(lines)
    for index, line in enumerate(lines):
        depth += line.count("(") - line.count(")")
        if depth <= 0:
            end = index + 1
            break
    return "".join(lines[:end]), "".join(lines[: end + CONTEXT_LINES])


def names_in(code: str) -> set[str]:
    """The names in the code worth citing."""
    return {
        name
        for name in IDENT_RE.findall(code)
        if len(name) >= 3 and name.lower() not in COMMON
    }


def read_report(path: str) -> dict[int, tuple[str, str]]:
    """Maps report.md row numbers to their verdict and rationale."""
    rows = {}
    with open(path) as report:
        for line in report:
            match = ROW_RE.match(line)
            if match:
                rows[int(match.group(1))] = (
                    match.group(2).strip(),
                    match.group(3).strip(),
                )
    return rows


def row_problem(
    statement: str, context: str, verdict: str, rationale: str
) -> str | None:
    if verdict.upper() not in VERDICTS:
        return f"verdict is {verdict or 'empty'!r}, not TP, FP, or Uncertain"
    if not rationale or rationale == "TBD":
        return "no rationale"
    names = names_in(statement)
    if names and not names_in(context) & set(IDENT_RE.findall(rationale)):
        return (
            "the rationale names nothing from the flagged code; read the source "
            f"and cite what it uses, e.g. {', '.join(sorted(names))}"
        )
    return None


def check_report(log_dir: str, report: str, work_dir: str) -> None:
    """Prints the rows to redo and exits nonzero if there are any."""
    rows = report_rows(log_dir)
    verdicts = read_report(report)
    problems = []
    for number, (project, issue) in rows.items():
        verdict, rationale = verdicts.get(number, ("", ""))
        statement, context = flagged_code(project, issue, work_dir)
        problem = row_problem(statement, context, verdict, rationale)
        if problem:
            location = f"{project} {issue.file_path}:{issue.line}"
            problems.append(f"#{number} ({location}): {problem}")
    if not problems:
        print(f"All {len(rows)} rows of {report} pass.")
        return
    print(f"{len(problems)} of {len(rows)} rows of {report} need another look:")
    print("\n".join(problems), flush=True)
    sys.exit(1)
