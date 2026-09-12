"""Build the public JSON record for one finished CTIT run."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from testers.generate_report import Issue, ProjectResult, parse_log_file

OUTPUT_FILE = "ctit-result.json"


@dataclass
class Diagnostic:
    file: str
    line: int
    column: int
    message: str
    verdict: str | None


@dataclass
class ProjectRun:
    project: str
    status: str
    duration_seconds: float | None
    diagnostics: list[Diagnostic]


@dataclass
class Baseline:
    llvm_revision: str
    project_runs: list[ProjectRun] | None


@dataclass
class Run:
    github_run_id: int
    github_run_attempt: int
    pr_number: int
    llvm_revision: str
    check_name: str
    check_config: dict[str, object]
    runner_arch: str
    started_at: str
    finished_at: str
    duration_seconds: float
    status: str
    artifact_url: str | None
    project_runs: list[ProjectRun]
    baseline: Baseline | None = None


def _parse_timestamp(value: str, name: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must include a UTC offset")
    return timestamp


def _read_config(value: str) -> dict[str, object]:
    config = json.loads(value or "{}")
    if not isinstance(config, dict):
        raise TypeError("check_config must be a JSON object")
    return config


def _pr_number(pr_url: str) -> int:
    try:
        return int(pr_url.rstrip("/").rsplit("/", 1)[-1])
    except ValueError as exc:
        raise ValueError(f"invalid PR URL: {pr_url}") from exc


def _read_verdicts(report_path: str | None) -> Iterator[str | None]:
    if not report_path or not os.path.isfile(report_path):
        return iter(())

    verdicts: list[str | None] = []
    # Match a report table row and capture its Verdict column.
    report_row = re.compile(r"^\|\s*\d+\s*\|[^|]*\|\s*([^|]+?)\s*\|")
    with open(report_path) as report:
        for line in report:
            match = report_row.match(line)
            if match:
                verdict = match.group(1).strip().upper()
                verdicts.append(verdict if verdict in {"TP", "FP"} else None)
    return iter(verdicts)


def _diagnostic(issue: Issue, verdict: str | None) -> Diagnostic:
    return Diagnostic(
        file=issue.file_path,
        line=issue.line,
        column=issue.col,
        message=issue.message,
        verdict=verdict,
    )


def _project_status(result: ProjectResult) -> str:
    if result.has_crash:
        return "CRASHED"
    if result.errors_count:
        return "FAILED"
    return "COMPLETED"


def _project_run(result: ProjectResult, verdicts: Iterator[str | None]) -> ProjectRun:
    diagnostics = []
    for issue in result.issues:
        verdict = next(verdicts, None)
        if issue.severity == "warning":
            diagnostics.append(_diagnostic(issue, verdict))

    return ProjectRun(
        project=result.name,
        status=_project_status(result),
        duration_seconds=result.elapsed_seconds,
        diagnostics=diagnostics,
    )


def _read_project_runs(log_dir: str, report_path: str | None) -> list[ProjectRun]:
    log_files = sorted(Path(log_dir).glob("*.log"))
    log_files = [path for path in log_files if path.name != "progress.log"]
    verdicts = _read_verdicts(report_path)
    return [_project_run(parse_log_file(str(path)), verdicts) for path in log_files]


def create_result(
    *,
    log_dir: str,
    report_path: str | None,
    github_run_id: str,
    github_run_attempt: int,
    pr_url: str,
    llvm_revision: str,
    check_name: str,
    check_config: str,
    runner_arch: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    status: str,
    artifact_url: str | None,
    baseline_revision: str | None = None,
    baseline_log_dir: str | None = None,
) -> Run:
    """Collect the metadata, project results, warnings, and TP/FP verdicts."""
    if status not in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise ValueError(f"invalid run status: {status}")
    if runner_arch not in {"ARM64", "X64"}:
        raise ValueError(f"invalid runner architecture: {runner_arch}")
    if github_run_attempt <= 0:
        raise ValueError("github_run_attempt must be positive")
    if duration_seconds < 0:
        raise ValueError("duration_seconds must not be negative")

    baseline = None
    if baseline_revision:
        baseline_runs = None
        if baseline_log_dir:
            baseline_runs = _read_project_runs(baseline_log_dir, None)
        baseline = Baseline(
            llvm_revision=baseline_revision,
            project_runs=baseline_runs,
        )

    return Run(
        github_run_id=int(github_run_id),
        github_run_attempt=github_run_attempt,
        pr_number=_pr_number(pr_url),
        llvm_revision=llvm_revision,
        check_name=check_name,
        check_config=_read_config(check_config),
        runner_arch=runner_arch,
        started_at=_timestamp_string(started_at, "started_at"),
        finished_at=_timestamp_string(finished_at, "finished_at"),
        duration_seconds=duration_seconds,
        status=status,
        artifact_url=artifact_url,
        project_runs=_read_project_runs(log_dir, report_path),
        baseline=baseline,
    )


def write_result(result: Run, output: str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as stream:
        json.dump(asdict(result), stream, indent=2, sort_keys=True)
        stream.write("\n")


def _timestamp_string(value: str, name: str) -> str:
    _parse_timestamp(value, name)
    return value


def _required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _run_status(job_status: str) -> str:
    if job_status == "success":
        return "COMPLETED"
    if job_status == "cancelled":
        return "CANCELLED"
    return "FAILED"


def main() -> None:
    """Generate the result for the current GitHub Actions job."""
    if not os.environ.get("LLVM_REVISION") or not os.environ.get("CHECK_NAME"):
        print("LLVM revision or check name unavailable; skipping result generation")
        return

    started = _parse_timestamp(
        _required_environment("CTIT_STARTED_AT"), "CTIT_STARTED_AT"
    )
    finished = datetime.now(timezone.utc)

    llvm_revision = _required_environment("LLVM_REVISION")
    patch = os.environ.get("PATCH_SHA256")
    if patch:
        llvm_revision = f"{llvm_revision}+patch:{patch}"

    compare_baseline = os.environ.get("COMPARE_BASELINE") == "true"
    has_baseline = os.environ.get("HAS_BASELINE") == "true"
    result = create_result(
        log_dir="logs",
        report_path="report.md",
        github_run_id=_required_environment("GITHUB_RUN_ID"),
        github_run_attempt=int(_required_environment("GITHUB_RUN_ATTEMPT")),
        pr_url=_required_environment("PR_LINK"),
        llvm_revision=llvm_revision,
        check_name=_required_environment("CHECK_NAME"),
        check_config=os.environ.get("TIDY_CONFIG", "{}") or "{}",
        runner_arch=_required_environment("RUNNER_ARCH"),
        started_at=started.isoformat(),
        finished_at=finished.isoformat().replace("+00:00", "Z"),
        duration_seconds=(finished - started).total_seconds(),
        status=_run_status(_required_environment("JOB_STATUS")),
        artifact_url=os.environ.get("ARTIFACT_URL") or None,
        baseline_revision=(
            _required_environment("LLVM_REVISION") if compare_baseline else None
        ),
        baseline_log_dir="logs/baseline" if has_baseline else None,
    )
    write_result(result, OUTPUT_FILE)
    print(f"Run result generated: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
