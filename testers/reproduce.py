"""Run the AI triage's minimal reproducers with the patched and baseline clang-tidy.

The triage agent writes `reproducers/<row>.cpp` (or `.c`), where <row> is the
row number in report.md. One reproducer can stand for several rows with the
same cause: its header lists them, e.g. `// ctit-rows: 7 12-15`. This module
runs each file with both binaries and keeps only those whose patched output
has a warning from the check of every row they claim, so the reported outputs
always come from real runs.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from testers.analyze import check_flags
from testers.generate_report import Issue, _load_results

DEFAULT_REPRO_DIR = "reproducers"
REPRODUCERS_JSON = "reproducers.json"
REPRODUCERS_MD = "reproducers.md"
# Directives in the leading `//` comment lines of a reproducer.
ARGS_RE = re.compile(r"^//\s*ctit-args:(.*)$")
ROWS_RE = re.compile(r"^//\s*ctit-rows:(.*)$")
DEFAULT_ARGS = {".cpp": ["-std=c++20"], ".c": ["-std=c17"]}
MAX_SOURCE_CHARS = 4_000
MAX_OUTPUT_CHARS = 4_000
# Warnings listed per reproducer in issue.md; the rest are counted.
MAX_LISTED_WARNINGS = 10
TIMEOUT_SECONDS = 120

# Baseline states.
BASELINE_RAN = "ran"
BASELINE_UNAVAILABLE = "unavailable"  # The check does not exist on LLVM main.
BASELINE_NOT_REQUESTED = "not-requested"  # The run has no /baseline.


@dataclass
class Target:
    row: int
    project: str
    file: str
    line: int
    column: int
    message: str


@dataclass
class Reproducer:
    # The warnings it reproduces; the first is the row the file is named after.
    warnings: list[Target]
    language: str
    source: str
    compiler_args: list[str]
    patched_output: str
    baseline_status: str
    baseline_output: str | None


Rows = dict[int, tuple[str, Issue]]


def report_rows(log_dir: str) -> Rows:
    """Maps report.md row numbers to their project and diagnostic."""
    results, _ = _load_results(log_dir)
    rows: Rows = {}
    for res in results:
        for issue in res.issues:
            rows[len(rows) + 1] = (res.name, issue)
    return rows


def _directives(source: str) -> tuple[str | None, str | None]:
    """Returns the ctit-args and ctit-rows values of the leading comments."""
    args = rows = None
    for line in source.splitlines():
        line = line.strip()
        if not line.startswith("//"):
            break
        if match := ARGS_RE.match(line):
            args = match.group(1)
        elif match := ROWS_RE.match(line):
            rows = match.group(1)
    return args, rows


def compiler_args(path: Path, source: str) -> list[str]:
    args, _ = _directives(source)
    return args.split() if args is not None else DEFAULT_ARGS.get(path.suffix, [])


def claimed_rows(path: Path, source: str) -> list[int]:
    """The row the file is named after, then those its ctit-rows line adds."""
    rows = [int(path.stem)]
    _, extra = _directives(source)
    for part in (extra or "").replace(",", " ").split():
        first, _, last = part.lstrip("#").partition("-")
        start = int(first)
        end = int(last.lstrip("#")) if last else start
        rows += [row for row in range(start, end + 1) if row not in rows]
    return rows


def run_tidy(
    binary: str,
    path: Path,
    check_name: str,
    tidy_config: str | None,
    args: list[str],
) -> str:
    """Runs clang-tidy on one file and returns its combined output."""
    # clang-tidy runs in the reproducer's directory, so resolve relative paths.
    if os.sep in binary:
        binary = os.path.abspath(binary)
    cmd = [binary, f"-checks=-*,{check_name}", "-quiet", *check_flags(check_name)]
    if tidy_config:
        cmd.append(f"-config={tidy_config}")
    cmd += [path.name, "--", *args]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            cwd=path.parent,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=TIMEOUT_SECONDS,
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        output = f"clang-tidy timed out after {TIMEOUT_SECONDS} seconds\n"
    output = output.replace(str(path.resolve()), path.name)
    output = output.replace(str(path), path.name)
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n[... output truncated ...]\n"
    return output


def has_warning(output: str, check: str) -> bool:
    return (
        re.search(rf": warning: .*\[{re.escape(check)}\]$", output, re.MULTILINE)
        is not None
    )


def has_error(output: str) -> bool:
    return re.search(r": (?:fatal )?error: ", output) is not None


def run_reproducer(
    path: Path,
    rows: Rows,
    clang_tidy_bin: str,
    baseline_bin: str | None,
    baseline_status: str,
    check_name: str,
    tidy_config: str | None,
) -> tuple[Reproducer | None, str]:
    """Runs one reproducer; returns it, or None and why it was rejected."""
    if not path.stem.isdigit() or int(path.stem) not in rows:
        return None, f"name it <row>{path.suffix}, with a row of report.md"
    source = path.read_text(errors="replace")
    if len(source) > MAX_SOURCE_CHARS:
        return None, f"longer than {MAX_SOURCE_CHARS} characters"
    try:
        claimed = claimed_rows(path, source)
    except ValueError:
        return None, "write ctit-rows as row numbers and ranges, e.g. 7 12-15"
    unknown = [row for row in claimed if row not in rows]
    if unknown:
        return None, f"ctit-rows has rows not in report.md: {unknown}"

    args = compiler_args(path, source)
    patched = run_tidy(clang_tidy_bin, path, check_name, tidy_config, args)
    checks = dict.fromkeys(rows[row][1].check_name for row in claimed)
    missing = [check for check in checks if not has_warning(patched, check)]
    if has_error(patched) or missing:
        problem = "has compiler errors" if has_error(patched) else f"lacks {missing}"
        return None, f"patched output {problem}:\n{patched}"

    baseline = None
    if baseline_bin:
        baseline = run_tidy(baseline_bin, path, check_name, tidy_config, args)
    warnings = [
        Target(
            row=row,
            project=rows[row][0],
            file=rows[row][1].file_path,
            line=rows[row][1].line,
            column=rows[row][1].col,
            message=rows[row][1].message,
        )
        for row in claimed
    ]
    return (
        Reproducer(
            warnings=warnings,
            language=path.suffix.removeprefix("."),
            source=source,
            compiler_args=args,
            patched_output=patched,
            baseline_status=baseline_status,
            baseline_output=baseline,
        ),
        "",
    )


def _fence(text: str, lang: str = "") -> str:
    # A longer fence than any backtick run in the text keeps it intact.
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}\n"


def write_markdown(reproducers: list[Reproducer], output: str) -> None:
    """Writes the reproducers for the AI analysis section of issue.md."""
    with open(output, "w") as f:
        f.write("### Reproducers\n\n")
        f.write(
            "Minimal reproducers written by the AI. CTIT ran each one with the "
            "patched clang-tidy and kept it only if it reproduces the warnings "
            "it stands for.\n\n"
        )
        for number, repro in enumerate(reproducers, 1):
            count = len(repro.warnings)
            f.write(
                f"#### Reproducer {number}: "
                f"{count} warning{'s' if count > 1 else ''}\n\n"
            )
            f.writelines(
                f"- #{w.row} {w.project}: `{w.file}:{w.line}` {w.message}\n"
                for w in repro.warnings[:MAX_LISTED_WARNINGS]
            )
            remaining = len(repro.warnings) - MAX_LISTED_WARNINGS
            if remaining > 0:
                f.write(f"- ...and {remaining} more\n")
            f.write(f"\nCompiler arguments: `{' '.join(repro.compiler_args)}`\n\n")
            f.write(_fence(repro.source, repro.language))
            f.write("\nPatched clang-tidy:\n\n")
            f.write(_fence(repro.patched_output or "(no output)"))
            if repro.baseline_status == BASELINE_RAN:
                f.write("\nBaseline clang-tidy:\n\n")
                f.write(_fence(repro.baseline_output or "(no output)"))
            elif repro.baseline_status == BASELINE_UNAVAILABLE:
                f.write("\nBaseline clang-tidy: check unavailable.\n")
            f.write("\n")


def reproduce(
    sources: list[str],
    repro_dir: str,
    log_dir: str,
    check_name: str,
    tidy_config: str | None,
    clang_tidy_bin: str,
    baseline_bin: str | None,
    baseline_unavailable: bool,
) -> None:
    """Runs reproducers.

    With `sources`, runs those files and prints the outputs, so the agent can
    try a reproducer before saving it. Otherwise runs every file in
    `repro_dir` and writes the accepted ones to reproducers.json and .md.
    """
    if baseline_bin:
        baseline_status = BASELINE_RAN
    elif baseline_unavailable:
        baseline_status = BASELINE_UNAVAILABLE
    else:
        baseline_status = BASELINE_NOT_REQUESTED

    rows = report_rows(log_dir)
    trying = bool(sources)
    paths = (
        [Path(s) for s in sources]
        if trying
        else sorted(
            (p for p in Path(repro_dir).glob("*") if p.suffix in DEFAULT_ARGS),
            key=lambda p: (int(p.stem) if p.stem.isdigit() else 0, p.name),
        )
    )

    accepted: list[Reproducer] = []
    covered: set[int] = set()
    for path in paths:
        repro, reason = run_reproducer(
            path,
            rows,
            clang_tidy_bin,
            baseline_bin,
            baseline_status,
            check_name,
            tidy_config,
        )
        if repro is None:
            print(f"{path}: rejected, {reason}")
            continue
        # Each row keeps its first reproducer.
        repro.warnings = [w for w in repro.warnings if w.row not in covered]
        if not repro.warnings:
            print(f"{path}: rejected, earlier reproducers cover all its rows")
            continue
        covered.update(w.row for w in repro.warnings)
        accepted.append(repro)
        if trying:
            claimed = " ".join(str(w.row) for w in repro.warnings)
            print(f"{path}: reproduces rows {claimed}\n--- patched ---")
            print(repro.patched_output)
            print(f"--- baseline: {baseline_status} ---")
            if repro.baseline_output is not None:
                print(repro.baseline_output)

    if trying:
        return
    with open(REPRODUCERS_JSON, "w") as f:
        json.dump([asdict(r) for r in accepted], f, indent=2)
        f.write("\n")
    if accepted:
        write_markdown(accepted, REPRODUCERS_MD)
    elif os.path.exists(REPRODUCERS_MD):
        os.remove(REPRODUCERS_MD)
    print(
        f"{len(accepted)} of {len(paths)} reproducers accepted, "
        f"covering {len(covered)} warnings",
        file=sys.stderr,
    )
