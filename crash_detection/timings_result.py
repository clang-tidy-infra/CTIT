#!/usr/bin/env python3
"""Build the public JSON record for one daily check timings run.

The record has the wall time of each check per project and summed over all
projects, as in the tracking issue comment, and the analysis time of each
project. The results repository stores one record per run under ``timings/``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from crash_detection.parse_check_profile import combine_profiles, parse_profile
from crash_detection.post_check_timings import describe_machine

OUTPUT_FILE = "ctit-timings.json"
_ELAPSED_RE: re.Pattern[str] = re.compile(
    r"CTIT analysis elapsed seconds: (\d+(?:\.\d+)?)"
)
_DATE_RE: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class ProjectTimings:
    # How long run-clang-tidy took on the project; None if it did not finish.
    duration_seconds: float | None
    # Wall time of all checks from the profile; None if the log has no profile.
    check_seconds: float | None


@dataclass
class TimingsRun:
    date: str
    github_run_id: int
    github_run_attempt: int
    llvm_revision: str
    runner_name: str
    runner_arch: str
    machine: str | None
    projects: dict[str, ProjectTimings]
    # Wall time of each check summed over all projects.
    checks: dict[str, float]
    # Wall time of each check in each project, stored by column to keep the
    # record small: project_checks[project][i] is the time of check_names[i],
    # or None if that check did not run on the project. Projects without a
    # profile are left out.
    check_names: list[str]
    project_checks: dict[str, list[float | None]]


def _read_log(path: Path) -> tuple[float | None, float, dict[str, float]]:
    """Return (analysis duration, profile total wall, {check: wall}) of a log."""
    with path.open() as f:
        lines = f.readlines()
    total_wall, checks = parse_profile(lines)
    duration: float | None = None
    # analyze.py writes the elapsed time as the last line of the log.
    for line in reversed(lines):
        match = _ELAPSED_RE.fullmatch(line.strip())
        if match:
            duration = float(match.group(1))
            break
    return duration, total_wall, checks


def create_timings(
    *,
    log_dir: str,
    date: str,
    github_run_id: str,
    github_run_attempt: int,
    llvm_revision: str,
    runner_name: str,
    runner_arch: str,
    machine: str | None,
) -> TimingsRun:
    """Collect the check timings and project durations from the logs."""
    if not _DATE_RE.match(date):
        raise ValueError(f"date must look like YYYY-MM-DD, got: {date}")
    if runner_arch not in {"ARM64", "X64"}:
        raise ValueError(f"invalid runner architecture: {runner_arch}")
    if github_run_attempt <= 0:
        raise ValueError("github_run_attempt must be positive")

    projects: dict[str, ProjectTimings] = {}
    profiles: dict[str, tuple[float, dict[str, float]]] = {}
    for path in sorted(Path(log_dir).glob("*.log")):
        if path.name == "progress.log":
            continue
        duration, total_wall, checks = _read_log(path)
        if checks:
            profiles[path.stem] = (total_wall, checks)
        projects[path.stem] = ProjectTimings(
            duration_seconds=None if duration is None else round(duration, 2),
            check_seconds=round(total_wall, 2) if checks else None,
        )
    if not profiles:
        raise ValueError(f"no profiling data found in {log_dir}")

    check_names = sorted({check for _, checks in profiles.values() for check in checks})
    return TimingsRun(
        date=date,
        github_run_id=int(github_run_id),
        github_run_attempt=github_run_attempt,
        llvm_revision=llvm_revision.lower(),
        runner_name=runner_name,
        runner_arch=runner_arch,
        machine=machine or None,
        projects=projects,
        # Rounded like the tracking issue comment, so both show the same numbers.
        checks={
            check: round(wall, 2) for check, wall in combine_profiles(profiles).items()
        },
        check_names=check_names,
        project_checks={
            project: [
                round(checks[name], 2) if name in checks else None
                for name in check_names
            ]
            for project, (_, checks) in profiles.items()
        },
    )


def format_timings(timings: TimingsRun) -> str:
    """Return the record as indented JSON, with each project's column of check
    times on one line instead of one line per number."""
    data = asdict(timings)
    columns: dict[str, list[float | None]] = data["project_checks"]
    # json.dumps cannot indent only some lists, so each column is swapped for a
    # placeholder string that cannot occur in the record, then put back.
    placeholders = {project: f"\0{project}" for project in columns}
    data["project_checks"] = placeholders
    text = json.dumps(data, indent=2, sort_keys=True)
    for project, placeholder in placeholders.items():
        text = text.replace(json.dumps(placeholder), json.dumps(columns[project]))
    return text + "\n"


def write_timings(timings: TimingsRun, output: str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_timings(timings))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-dir", default="logs", help="Directory containing .log files"
    )
    parser.add_argument(
        "--llvm-revision", required=True, help="LLVM commit clang-tidy was built from"
    )
    parser.add_argument("--runner", required=True, help="Name of the runner")
    parser.add_argument(
        "--runner-arch", required=True, help="Architecture of the runner (ARM64, X64)"
    )
    parser.add_argument("--run-id", required=True, help="GitHub Actions run ID")
    parser.add_argument(
        "--run-attempt", required=True, type=int, help="GitHub Actions run attempt"
    )
    parser.add_argument(
        "--date",
        default=datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        help="Date of the timings, YYYY-MM-DD (default: today in UTC)",
    )
    parser.add_argument(
        "--machine",
        default=None,
        help="Hardware description (default: describe this machine; '' for unknown)",
    )
    parser.add_argument(
        "--output", default=OUTPUT_FILE, help=f"Output file (default: {OUTPUT_FILE})"
    )
    args = parser.parse_args()

    try:
        timings = create_timings(
            log_dir=args.log_dir,
            date=args.date,
            github_run_id=args.run_id,
            github_run_attempt=args.run_attempt,
            llvm_revision=args.llvm_revision,
            runner_name=args.runner,
            runner_arch=args.runner_arch,
            machine=describe_machine() if args.machine is None else args.machine,
        )
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    write_timings(timings, args.output)
    print(f"Timings record generated: {args.output}")


if __name__ == "__main__":
    main()
