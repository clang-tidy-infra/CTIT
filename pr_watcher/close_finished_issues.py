#!/usr/bin/env python3
"""Close CTIT integration-test issues whose llvm-project pull request is closed.

An issue tracks the pull request linked on the first line of its body. Once
that pull request is merged or closed there is nothing left to test, so the
issue is closed as completed (merged) or not planned (closed without merging),
with a comment saying why.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

from parse_issue import parse_body
from pr_watcher.github_api import GitHubClient, GitHubError
from pr_watcher.sync_issues import TRIGGER_LABELS

LLVM_REPO = "llvm/llvm-project"
SUMMARY_FILE = "close-summary.md"
# Only llvm-project links count: a link to a pull request of another
# repository must not close the issue because of llvm-project's PR #N.
_LLVM_PR_URL_RE: re.Pattern[str] = re.compile(
    r"^https://(?:www\.)?github\.com/llvm/llvm-project/pull/(\d+)/?$"
)

MERGED = "merged"
CLOSED = "closed"
OPEN = "open"
FAILED = "failed"


@dataclass(frozen=True)
class TrackedIssue:
    """An open CTIT issue and the llvm-project pull request it tracks."""

    number: int
    pr_number: int


@dataclass(frozen=True)
class Outcome:
    """What happened to one issue."""

    issue: TrackedIssue
    kind: str  # MERGED, CLOSED, OPEN or FAILED
    detail: str = ""


def llvm_pr_number(body: str) -> int | None:
    """The llvm-project pull request linked on the first line of an issue."""
    try:
        # Unrelated issues parse as nonsense; their option warnings are noise.
        with contextlib.redirect_stderr(io.StringIO()):
            pr_link: str = parse_body(body).pr_link
    except ValueError:
        return None
    match: re.Match[str] | None = _LLVM_PR_URL_RE.match(pr_link)
    return int(match.group(1)) if match else None


def fetch_tracked_issues(client: GitHubClient, repo: str) -> list[TrackedIssue]:
    """Open issues with a test label that link an llvm-project pull request."""
    payloads: list[dict[str, Any]] = client.paginate(
        f"repos/{repo}/issues", {"state": "open"}
    )
    issues: list[TrackedIssue] = []
    for payload in payloads:
        if "pull_request" in payload:
            continue
        labels: set[str] = {label["name"] for label in payload.get("labels", [])}
        if labels.isdisjoint(TRIGGER_LABELS.values()):
            continue
        pr_number: int | None = llvm_pr_number(payload.get("body") or "")
        if pr_number is not None:
            issues.append(TrackedIssue(payload["number"], pr_number))
    return issues


def pr_state(client: GitHubClient, pr_number: int) -> str:
    """MERGED, CLOSED or OPEN."""
    pull: dict[str, Any] = client.get(f"repos/{LLVM_REPO}/pulls/{pr_number}")
    if pull.get("state") != "closed":
        return OPEN
    return MERGED if pull.get("merged_at") else CLOSED


def pr_url(pr_number: int) -> str:
    return f"https://github.com/{LLVM_REPO}/pull/{pr_number}"


def close_issue(
    client: GitHubClient, repo: str, issue: TrackedIssue, state: str
) -> None:
    how: str = "merged" if state == MERGED else "closed without merging"
    client.post(
        f"repos/{repo}/issues/{issue.number}/comments",
        {"body": f"Closing: {pr_url(issue.pr_number)} was {how}."},
    )
    client.patch(
        f"repos/{repo}/issues/{issue.number}",
        {
            "state": "closed",
            "state_reason": "completed" if state == MERGED else "not_planned",
        },
    )


def close_finished_issues(
    client: GitHubClient, repo: str, issues: list[TrackedIssue], dry_run: bool
) -> list[Outcome]:
    """Close every issue whose pull request is closed.

    A failure is recorded and the rest still run, as in sync_issues. Pull
    requests are looked up once even when several issues test them.
    """
    states: dict[int, str] = {}
    outcomes: list[Outcome] = []
    for issue in issues:
        try:
            if issue.pr_number not in states:
                states[issue.pr_number] = pr_state(client, issue.pr_number)
            state: str = states[issue.pr_number]
            if state != OPEN and not dry_run:
                close_issue(client, repo, issue, state)
            outcomes.append(Outcome(issue, state))
        except GitHubError as error:
            print(f"Error: {error}", file=sys.stderr)
            outcomes.append(Outcome(issue, FAILED, str(error)))
    return outcomes


def format_summary(outcomes: list[Outcome], dry_run: bool) -> str:
    """Render the job summary: the closed issues and the failures."""
    lines: list[str] = ["## Close finished issues", ""]
    done: list[Outcome] = [o for o in outcomes if o.kind != OPEN]
    if not done:
        lines.append(
            f"_All {len(outcomes)} open test issues track an open pull request._"
        )
        return "\n".join(lines) + "\n"

    verb: str = "Would close" if dry_run else "Closed"
    lines.append("| Issue | Pull request | Result |")
    lines.append("|-------|--------------|--------|")
    for outcome in done:
        if outcome.kind == FAILED:
            # A failure reason is a server message and may contain a pipe.
            result: str = "failed: " + outcome.detail.replace("|", "\\|").replace(
                "\n", " "
            )
        else:
            result = f"{verb.lower()}, PR {outcome.kind}"
        lines.append(
            f"| #{outcome.issue.number} "
            f"| [llvm#{outcome.issue.pr_number}]({pr_url(outcome.issue.pr_number)}) "
            f"| {result} |"
        )
    closed: int = sum(1 for o in done if o.kind != FAILED)
    lines.append("")
    lines.append(f"**{verb} {closed} of {len(outcomes)} open test issue(s).**")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="CTIT repository (owner/name)")
    parser.add_argument(
        "--summary-file",
        default=SUMMARY_FILE,
        help=f"Markdown summary to write (default: {SUMMARY_FILE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be closed"
    )
    args: argparse.Namespace = parser.parse_args()

    token: str | None = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    client: GitHubClient = GitHubClient(token)
    try:
        issues: list[TrackedIssue] = fetch_tracked_issues(client, args.repo)
    except GitHubError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    outcomes: list[Outcome] = close_finished_issues(
        client, args.repo, issues, args.dry_run
    )
    for outcome in outcomes:
        print(
            f"#{outcome.issue.number}: llvm#{outcome.issue.pr_number} "
            f"{outcome.kind} {outcome.detail}".rstrip()
        )
    with open(args.summary_file, "w", encoding="utf-8") as stream:
        stream.write(format_summary(outcomes, args.dry_run))

    if any(outcome.kind == FAILED for outcome in outcomes):
        sys.exit(1)


if __name__ == "__main__":
    main()
