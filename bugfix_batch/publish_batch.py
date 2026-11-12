"""Split a batch run by check and post each result to the check's own issue.

The issues carry the bugfix label instead of a trigger label and are written
with the workflow's own token, whose events start no workflow, so nothing here
can start a check-tester run.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bugfix_batch.plan import (
    PLAN_DIR,
    BatchEntry,
    BuildResult,
    read_build_result,
    table_cell,
)
from pr_watcher.close_finished_issues import BUGFIX_LABEL
from pr_watcher.github_api import GitHubClient, GitHubError
from pr_watcher.sync_issues import IssueRef, fetch_issues, format_marker, index_issues
from slim_comment import slim_comment
from testers.config import load_projects
from testers.generate_report import (
    ProjectResult,
    diff_against_baseline,
    generate_markdown,
    parse_log_file,
)

DEFAULT_LOG_DIR = "logs"
DEFAULT_BASELINE_LOG_DIR = "logs/baseline"
REPORTS_DIR = "reports"
SUMMARY_FILE = "publish-summary.md"


@dataclass(frozen=True)
class BatchRun:
    """What every report of one batch run shares."""

    build: BuildResult
    project_urls: dict[str, str]
    run_url: str
    artifact_url: str
    crash_notice: str


@dataclass(frozen=True)
class Outcome:
    """What happened to the report of one check."""

    entry: BatchEntry
    check: str
    new: int
    removed: int
    issue_number: int | None = None
    error: str | None = None


def load_results(log_dir: str) -> list[ProjectResult]:
    logs: list[Path] = sorted(Path(log_dir).glob("*.log"))
    return [parse_log_file(str(log)) for log in logs if log.name != "progress.log"]


def for_check(result: ProjectResult, check: str) -> ProjectResult:
    """Narrow one project's results to one check of the batch.

    The analysis time stays out: it covers the whole batch, not this check.
    """
    # Checks registered twice report as [first-name,second-name].
    issues = [issue for issue in result.issues if check in issue.check_name.split(",")]
    crashes = [crash for crash in result.crashes if crash.check == check]
    return ProjectResult(
        name=result.name,
        warnings_count=sum(issue.severity == "warning" for issue in issues),
        errors_count=sum(issue.severity == "error" for issue in issues),
        has_crash=bool(crashes),
        issues=issues,
        crashes=crashes,
    )


def crash_notice(
    results: list[ProjectResult], baseline_results: list[ProjectResult]
) -> str:
    """Warn about crashes, which distort the comparison for the whole batch.

    A crash loses every diagnostic of the translation unit, those of the other
    checks in the batch included, and shows up as removed or new diagnostics.
    """
    projects: set[str] = {
        result.name for result in results + baseline_results if result.has_crash
    }
    if not projects:
        return ""
    names: str = ", ".join(f"`{name}`" for name in sorted(projects))
    return (
        f"⚠️ clang-tidy crashed on {names} during this batch. Differences in these "
        "projects may come from the crash and not from this pull request.\n\n"
    )


def render_report(
    entry: BatchEntry,
    run: BatchRun,
    results: list[ProjectResult],
    baseline_results: list[ProjectResult],
    output: Path,
) -> str:
    """Write the issue comment for one check, ready to post."""
    generate_markdown(
        results,
        str(output),
        run.project_urls,
        baseline_results,
        run.build.llvm_revision,
    )
    # Other pull requests stay unnamed: a link would put this comment on their
    # timelines in llvm-project.
    header: str = (
        f"{format_marker(entry.head_sha)}\n\n"
        f"Tested at `{entry.head_sha[:12]}` in [batch run]({run.run_url}) "
        f"with {len(run.build.built)} pull request(s) applied.\n\n"
        f"{run.crash_notice}"
    )
    report: str = slim_comment(header + output.read_text(), run.artifact_url)
    output.write_text(report)
    return report


def create_issue(client: GitHubClient, repo: str, entry: BatchEntry, check: str) -> int:
    """Open an issue in the format pr_watcher reads back."""
    issue: dict[str, Any] = client.post(
        f"repos/{repo}/issues",
        {"title": f"[Bugfix] {check}", "body": f"{entry.pr_url} {check}\n"},
    )
    number: int = issue["number"]
    client.post(f"repos/{repo}/issues/{number}/labels", {"labels": [BUGFIX_LABEL]})
    return number


def post_report(
    client: GitHubClient,
    repo: str,
    entry: BatchEntry,
    check: str,
    issue: IssueRef | None,
    report: str,
) -> int:
    """Post the report, whose marker records the revision as tested.

    The marker goes out last, so a failure here makes the next batch retry.
    """
    number: int = issue.number if issue else create_issue(client, repo, entry, check)
    client.post(f"repos/{repo}/issues/{number}/comments", {"body": report})
    return number


def publish(
    client: GitHubClient,
    repo: str,
    run: BatchRun,
    results: list[ProjectResult],
    baseline_results: list[ProjectResult],
    index: dict[tuple[int, str], IssueRef],
    reports_dir: Path,
    dry_run: bool,
) -> list[Outcome]:
    """Render every report and post it, unless this is a dry run.

    A failed post is recorded and the rest still go out, as in sync_issues.
    """
    reports_dir.mkdir(parents=True, exist_ok=True)
    outcomes: list[Outcome] = []
    for entry in run.build.built:
        for check in entry.checks:
            check_results = [for_check(result, check) for result in results]
            check_baseline = [for_check(result, check) for result in baseline_results]
            report: str = render_report(
                entry,
                run,
                check_results,
                check_baseline,
                reports_dir / f"{entry.pr_number}-{check}.md",
            )

            issue: IssueRef | None = index.get((entry.pr_number, check))
            number: int | None = issue.number if issue else None
            failure: str | None = None
            if not dry_run:
                try:
                    number = post_report(client, repo, entry, check, issue, report)
                except GitHubError as error:
                    print(f"Error: {error}", file=sys.stderr)
                    failure = str(error)

            diffs = diff_against_baseline(check_results, check_baseline)
            outcomes.append(
                Outcome(
                    entry,
                    check,
                    new=sum(len(diff.new) for diff in diffs),
                    removed=sum(len(diff.removed) for diff in diffs),
                    issue_number=number,
                    error=failure,
                )
            )
    return outcomes


def format_summary(outcomes: list[Outcome], build: BuildResult, dry_run: bool) -> str:
    """Render the job summary: one row per check, then the dropped patches."""
    title: str = "## Bugfix batch results" + (" (dry run)" if dry_run else "")
    lines: list[str] = [title, "", f"LLVM revision: `{build.llvm_revision}`", ""]
    if outcomes:
        lines.append("| PR | Check | New | Removed | Issue |")
        lines.append("|----|-------|----:|--------:|-------|")
    for outcome in outcomes:
        issue: str = f"#{outcome.issue_number}" if outcome.issue_number else "-"
        if outcome.error:
            issue = f"failed: {table_cell(outcome.error)}"
        lines.append(
            f"| [#{outcome.entry.pr_number}]({outcome.entry.pr_url}) "
            f"| `{outcome.check}` | {outcome.new} | {outcome.removed} | {issue} |"
        )
    if build.failed:
        lines += ["", "Dropped from the batch, retried next time:", ""]
        lines += [
            f"- [#{skip.pr_number}]({skip.pr_url}): {table_cell(skip.reason)}"
            for skip in build.failed
        ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="CTIT repository (owner/name)")
    parser.add_argument("--plan-dir", default=PLAN_DIR, help="Directory of the plan")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="Patched run logs")
    parser.add_argument(
        "--baseline-log-dir",
        default=DEFAULT_BASELINE_LOG_DIR,
        help="Baseline run logs",
    )
    parser.add_argument("--run-url", required=True, help="This workflow run")
    parser.add_argument("--artifact-url", required=True, help="The logs artifact")
    parser.add_argument(
        "--dry-run", action="store_true", help="Render reports without posting"
    )
    args: argparse.Namespace = parser.parse_args()

    token: str | None = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    client: GitHubClient = GitHubClient(token)
    try:
        index: dict[tuple[int, str], IssueRef] = index_issues(
            fetch_issues(client, args.repo)
        )
    except GitHubError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    build: BuildResult = read_build_result(args.plan_dir)
    results: list[ProjectResult] = load_results(args.log_dir)
    baseline_results: list[ProjectResult] = load_results(args.baseline_log_dir)
    run: BatchRun = BatchRun(
        build=build,
        project_urls={project.name: project.browse_url for project in load_projects()},
        run_url=args.run_url,
        artifact_url=args.artifact_url,
        crash_notice=crash_notice(results, baseline_results),
    )
    outcomes: list[Outcome] = publish(
        client,
        args.repo,
        run,
        results,
        baseline_results,
        index,
        Path(args.plan_dir) / REPORTS_DIR,
        args.dry_run,
    )

    summary: str = format_summary(outcomes, build, args.dry_run)
    print(summary)
    (Path(args.plan_dir) / SUMMARY_FILE).write_text(summary, encoding="utf-8")

    if any(outcome.error for outcome in outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()
