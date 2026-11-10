"""Pick the pull requests of the next bugfix batch.

A batch applies many patches to one LLVM checkout and analyzes all their checks
in one pass, so a pull request joins only if it cannot disturb the others: it
changes nothing but the sources of existing checks, shares no check or file
with another entry, passed LLVM's test suites, and applies to the pinned LLVM.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crash_detection.select_modified_checks import check_resolver
from bugfix_batch.plan import (
    LLVM_DIR,
    PLAN_DIR,
    BatchEntry,
    Plan,
    Skipped,
    git_apply,
    joined_checks,
    patch_path,
    set_github_output,
    table_cell,
    write_plan,
)
from pr_watcher.close_finished_issues import BUGFIX_LABEL
from pr_watcher.find_new_check_prs import (
    DEFAULT_SINCE_HOURS,
    LLVM_REPO,
    PullFile,
    new_check_names,
    search_recent_prs,
    since_timestamp,
)
from pr_watcher.github_api import GitHubClient, GitHubError
from pr_watcher.sync_issues import (
    IssueRef,
    IssueState,
    fetch_issues,
    index_issues,
    make_issue_probe,
)

DEFAULT_LIMIT = 10
LLVM_BRANCH = "main"
SUMMARY_FILE = "plan-summary.md"
TEST_SUITE_PREFIX = "Build and Test"
# LLVM's CI waits for approval on pull requests of new contributors. Until then
# only bots report, all green, so the suites must be seen to have run.
REQUIRED_SUITE = "Build and Test Linux"
PASSING_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})

Resolver = Callable[[str], set[str]]
IssueIndex = dict[tuple[int, str], IssueRef]
IssueProbe = Callable[[IssueRef], IssueState]


class Ineligible(Exception):
    """A pull request cannot join this batch; the message says why."""


@dataclass(frozen=True)
class Candidate:
    """An eligible pull request, not yet checked against the rest of the batch."""

    entry: BatchEntry
    changed_checks: frozenset[str]
    files: frozenset[str]


def is_excluded(path: str) -> bool:
    """Whether ``git_apply`` leaves this path out of the batch."""
    return "/test/" in path or "/unittests/" in path or path.endswith((".rst", ".md"))


def source_files(files: list[PullFile]) -> list[PullFile]:
    return [entry for entry in files if not is_excluded(entry["filename"])]


def changed_checks(files: list[PullFile], resolve: Resolver) -> set[str]:
    """Return the checks a pull request changes, rejecting wider changes.

    Shared code would change the results of other checks in the batch, and
    build files would need more than an incremental build.
    """
    if new_check_names(files):
        raise Ineligible("adds a new check, which the new-check track tests")

    checks: set[str] = set()
    for entry in source_files(files):
        path: str = entry["filename"]
        owners: set[str] = resolve(path) if entry.get("status") == "modified" else set()
        if not owners:
            raise Ineligible(f"changes {path}, not the source of an existing check")
        checks |= owners
    if not checks:
        raise Ineligible("changes no check source")
    return checks


def ci_problem(check_runs: list[dict[str, Any]]) -> str | None:
    """Return why LLVM's test suites do not count as passed, or None if they do."""
    suites: list[dict[str, Any]] = [
        run for run in check_runs if run["name"].startswith(TEST_SUITE_PREFIX)
    ]
    for run in suites:
        if run.get("status") != "completed":
            return f"LLVM CI still running: {run['name']}"
        if run.get("conclusion") not in PASSING_CONCLUSIONS:
            return f"LLVM CI failed: {run['name']}"
    if not any(
        run["name"] == REQUIRED_SUITE and run.get("conclusion") == "success"
        for run in suites
    ):
        return f"LLVM CI has not run {REQUIRED_SUITE}"
    return None


def checks_to_test(
    pr_number: int,
    head_sha: str,
    checks: set[str],
    index: IssueIndex,
    probe: IssueProbe,
) -> tuple[str, ...]:
    """Drop checks already tested at this revision or not left to this track.

    An issue without the bugfix label was either muted by a maintainer, who
    removed the label, or opened by hand and is run through check-tester.
    """
    todo: list[str] = []
    for check in sorted(checks):
        issue: IssueRef | None = index.get((pr_number, check))
        if issue is None:
            todo.append(check)
        elif BUGFIX_LABEL in issue.labels:
            tested: str | None = probe(issue).tested_sha
            if not tested or not head_sha.lower().startswith(tested):
                todo.append(check)
    return tuple(todo)


def evaluate(
    client: GitHubClient,
    repo: str,
    pull: dict[str, Any],
    resolve: Resolver,
    index: IssueIndex,
    probe: IssueProbe,
) -> Candidate:
    """Turn one search result into a candidate, or raise ``Ineligible``."""
    number: int = pull["number"]
    files: list[PullFile] = client.paginate(f"repos/{repo}/pulls/{number}/files")
    checks: set[str] = changed_checks(files, resolve)

    # The search result carries neither the base branch nor the head revision.
    details: dict[str, Any] = client.get(f"repos/{repo}/pulls/{number}")
    if details["base"]["ref"] != LLVM_BRANCH:
        raise Ineligible(f"targets {details['base']['ref']}")

    head_sha: str = details["head"]["sha"]
    todo: tuple[str, ...] = checks_to_test(number, head_sha, checks, index, probe)
    if not todo:
        raise Ineligible(f"no check left to test at {head_sha[:12]}")

    problem: str | None = ci_problem(
        client.paginate(
            f"repos/{repo}/commits/{head_sha}/check-runs", items_key="check_runs"
        )
    )
    if problem:
        raise Ineligible(problem)

    return Candidate(
        entry=BatchEntry(
            pr_number=number,
            pr_url=f"https://github.com/{repo}/pull/{number}",
            pr_title=pull["title"],
            head_sha=head_sha,
            checks=todo,
        ),
        changed_checks=frozenset(checks),
        files=frozenset(entry["filename"] for entry in source_files(files)),
    )


def _skip(pull: dict[str, Any], repo: str, reason: str) -> Skipped:
    number: int = pull["number"]
    url: str = f"https://github.com/{repo}/pull/{number}"
    return Skipped(number, url, pull["title"], reason)


def collect_candidates(
    client: GitHubClient,
    repo: str,
    pulls: list[dict[str, Any]],
    resolve: Resolver,
    index: IssueIndex,
    probe: IssueProbe,
) -> tuple[list[Candidate], list[Skipped]]:
    """Evaluate every pull request; one failure must not cost the whole batch."""
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    for pull in pulls:
        try:
            candidates.append(evaluate(client, repo, pull, resolve, index, probe))
        except (Ineligible, GitHubError) as error:
            skipped.append(_skip(pull, repo, str(error)))
    return candidates, skipped


def _ensure_fits(candidate: Candidate, taken: list[Candidate], limit: int) -> None:
    if len(taken) >= limit:
        raise Ineligible(f"batch limit of {limit} reached")
    for other in taken:
        if (
            other.changed_checks & candidate.changed_checks
            or other.files & candidate.files
        ):
            raise Ineligible(f"overlaps PR {other.entry.pr_number} of this batch")


def pick_batch(
    candidates: list[Candidate],
    prepare: Callable[[BatchEntry], None],
    limit: int,
) -> tuple[list[BatchEntry], list[Skipped]]:
    """Take candidates in order, keeping checks and files of the batch distinct.

    A candidate left out here stays untested, so the next batch retries it.
    """
    taken: list[Candidate] = []
    skipped: list[Skipped] = []
    for candidate in candidates:
        try:
            _ensure_fits(candidate, taken, limit)
            prepare(candidate.entry)
        except Ineligible as error:
            skipped.append(Skipped.of(candidate.entry, str(error)))
        else:
            taken.append(candidate)
    return [candidate.entry for candidate in taken], skipped


def make_patch_preparer(llvm_dir: str, plan_dir: str) -> Callable[[BatchEntry], None]:
    """Build the step that downloads a patch and proves it applies.

    Entries share no file, so patches that apply alone also apply together.
    """

    def prepare(entry: BatchEntry) -> None:
        path: Path = patch_path(plan_dir, entry.pr_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(f"{entry.pr_url}.diff", timeout=60) as response:
                path.write_bytes(response.read())
        except OSError as error:
            raise Ineligible(f"could not download the patch: {error}") from error
        if not git_apply(llvm_dir, path, "--check"):
            path.unlink()
            raise Ineligible("patch does not apply to the pinned LLVM")

    return prepare


def format_summary(plan: Plan, since: str) -> str:
    """Render the job summary: what joined the batch and why the rest did not."""
    lines: list[str] = [
        "## Bugfix batch plan",
        "",
        f"Pull requests with activity since `{since}`.",
        "",
    ]
    if not plan.entries and not plan.skipped:
        lines.append("_No clang-tidy pull request saw any activity._")
        return "\n".join(lines) + "\n"

    lines.append("| PR | Title | Decision |")
    lines.append("|----|-------|----------|")
    for entry in plan.entries:
        checks: str = ", ".join(f"`{check}`" for check in entry.checks)
        lines.append(
            f"| [#{entry.pr_number}]({entry.pr_url}) | {table_cell(entry.pr_title)} "
            f"| **batched:** {checks} |"
        )
    for skip in plan.skipped:
        lines.append(
            f"| [#{skip.pr_number}]({skip.pr_url}) | {table_cell(skip.pr_title)} "
            f"| {table_cell(skip.reason)} |"
        )
    lines.append("")
    lines.append(f"**Batched {len(plan.entries)} pull request(s).**")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="CTIT repository (owner/name)")
    parser.add_argument("--llvm-repo", default=LLVM_REPO, help="Upstream repository")
    parser.add_argument("--llvm-dir", default=LLVM_DIR, help="Pinned LLVM checkout")
    parser.add_argument("--plan-dir", default=PLAN_DIR, help="Directory for the plan")
    parser.add_argument(
        "--since-hours",
        type=int,
        default=DEFAULT_SINCE_HOURS,
        help=f"Activity window in hours (default: {DEFAULT_SINCE_HOURS})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum pull requests per batch (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Also consider draft pull requests",
    )
    args: argparse.Namespace = parser.parse_args()

    token: str | None = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    client: GitHubClient = GitHubClient(token)
    since: str = since_timestamp(args.since_hours)
    try:
        # Oldest first: the newest pull requests stay in the window the longest.
        pulls: list[dict[str, Any]] = search_recent_prs(
            client, args.llvm_repo, since, args.include_drafts
        )[::-1]
        index: IssueIndex = index_issues(fetch_issues(client, args.repo))
    except GitHubError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    candidates, ineligible = collect_candidates(
        client,
        args.llvm_repo,
        pulls,
        check_resolver(args.llvm_dir, "HEAD"),
        index,
        make_issue_probe(client, args.repo, since),
    )
    entries, left_out = pick_batch(
        candidates, make_patch_preparer(args.llvm_dir, args.plan_dir), args.limit
    )

    plan: Plan = Plan(tuple(entries), tuple(left_out + ineligible))
    write_plan(plan, args.plan_dir)
    summary: str = format_summary(plan, since)
    print(summary)
    (Path(args.plan_dir) / SUMMARY_FILE).write_text(summary, encoding="utf-8")

    set_github_output("has_work", "true" if plan.entries else "false")
    set_github_output("checks", joined_checks(plan.entries))


if __name__ == "__main__":
    main()
