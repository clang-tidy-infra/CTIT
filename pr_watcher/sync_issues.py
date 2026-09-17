#!/usr/bin/env python3
"""Open or refresh CTIT integration-test issues for new clang-tidy check PRs."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from parse_issue import parse_body
from pr_watcher.find_new_check_prs import (
    DEFAULT_SINCE_HOURS,
    OUTPUT_FILE,
    CheckTarget,
    since_timestamp,
)
from pr_watcher.github_api import MAX_PAGES, PAGE_SIZE, GitHubClient, GitHubError

DEFAULT_LIMIT = 10
SUMMARY_FILE = "nightly-summary.md"
_MARKER_RE: re.Pattern[str] = re.compile(
    r"<!-- ctit-(?:nightly|run)(?:\s+sha=([0-9a-fA-F]{7,40}))?\s*-->"
)
# Labels check-tester.yaml listens on; adding one starts an analysis run.
TRIGGER_LABELS = frozenset({"cpp", "c"})
# Matches the PR link on the first line of an integration-test issue.
_PR_URL_RE: re.Pattern[str] = re.compile(r"^https?://\S*/pull/(\d+)/?$")

CREATE = "create"
REDO = "redo"
SKIP = "skip"
FAILED = "failed"

IssuePayload: TypeAlias = dict[str, Any]  # one entry of GET /issues


@dataclass(frozen=True)
class IssueRef:
    """An existing CTIT issue, keyed by the PR and check it tracks."""

    number: int
    pr_number: int | None
    check_name: str | None
    state: str
    labels: frozenset[str]
    body: str
    created_at: str


@dataclass(frozen=True)
class IssueState:
    """What earlier nightly runs left behind on an issue."""

    recently_triggered: bool
    tested_sha: str | None


@dataclass(frozen=True)
class Action:
    """What the watcher decided to do about one target."""

    kind: str
    target: CheckTarget
    reason: str
    issue_number: int | None = None


def _pr_number(pr_link: str) -> int | None:
    match: re.Match[str] | None = _PR_URL_RE.match(pr_link.strip())
    return int(match.group(1)) if match else None


def parse_issue_ref(payload: IssuePayload) -> IssueRef:
    """Read the PR and check an issue tracks from its first body line."""
    body: str = payload.get("body") or ""
    pr_number: int | None = None
    check_name: str | None = None
    try:
        # Unrelated issues parse as nonsense; their option warnings are noise.
        with contextlib.redirect_stderr(io.StringIO()):
            parsed = parse_body(body)
    except ValueError:
        pass
    else:
        # Issues unrelated to CTIT still parse; only a real PR link counts.
        pr_number = _pr_number(parsed.pr_link)
        check_name = parsed.check_name if pr_number is not None else None

    return IssueRef(
        number=payload["number"],
        pr_number=pr_number,
        check_name=check_name,
        state=payload.get("state", "open"),
        labels=frozenset(label["name"] for label in payload.get("labels", [])),
        body=body,
        created_at=payload.get("created_at", ""),
    )


def index_issues(issues: list[IssueRef]) -> dict[tuple[int, str], IssueRef]:
    """Map (PR number, check) to the issue that should receive a re-run.

    Open issues win over closed ones; among equals the newest issue wins, so a
    re-opened discussion is preferred over a stale duplicate.
    """
    index: dict[tuple[int, str], IssueRef] = {}
    for issue in issues:
        if issue.pr_number is None or issue.check_name is None:
            continue
        key: tuple[int, str] = (issue.pr_number, issue.check_name)
        current: IssueRef | None = index.get(key)
        if current is None or _rank(issue) > _rank(current):
            index[key] = issue
    return index


def _rank(issue: IssueRef) -> tuple[int, int]:
    return (1 if issue.state == "open" else 0, issue.number)


def format_marker(head_sha: str) -> str:
    return f"<!-- ctit-nightly sha={head_sha} -->"


def read_issue_state(
    issue: IssueRef, comments: list[dict[str, Any]], since: str
) -> IssueState:
    """Fold the issue body and its comments into what nightly runs recorded."""
    entries: list[tuple[str, str]] = [(issue.created_at, issue.body)]
    entries.extend(
        (comment.get("created_at", ""), comment.get("body") or "")
        for comment in comments
    )
    entries.sort(key=lambda entry: entry[0])

    recently_triggered: bool = False
    tested_sha: str | None = None
    for created_at, body in entries:
        match: re.Match[str] | None = _MARKER_RE.search(body)
        if not match:
            continue
        if created_at >= since:
            recently_triggered = True
        # Markers without a sha predate revision tracking; keep the last known.
        if match.group(1):
            tested_sha = match.group(1).lower()
    return IssueState(recently_triggered, tested_sha)


def plan_actions(
    targets: list[CheckTarget],
    issues: list[IssueRef],
    probe: Callable[[IssueRef], IssueState],
    limit: int,
) -> list[Action]:
    """Decide, for each target, whether to open an issue, re-run one, or skip."""
    index: dict[tuple[int, str], IssueRef] = index_issues(issues)
    actions: list[Action] = []
    triggered: int = 0

    for target in targets:
        issue: IssueRef | None = index.get((target.pr_number, target.check_name))
        if issue is None:
            kind, reason = CREATE, "no issue tracks this PR and check yet"
        elif not issue.labels & TRIGGER_LABELS:
            # Dropping the cpp/c label is how a maintainer mutes an issue, and
            # re-adding it would authorize check-tester against the issue
            # author rather than against this watcher. Checked before the probe
            # so a muted issue costs no request.
            actions.append(
                Action(SKIP, target, "issue has no cpp/c label", issue.number)
            )
            continue
        else:
            state: IssueState = probe(issue)
            if state.recently_triggered:
                actions.append(
                    Action(
                        SKIP, target, "already triggered in this window", issue.number
                    )
                )
                continue
            if state.tested_sha and target.head_sha.lower().startswith(
                state.tested_sha.lower()
            ):
                actions.append(
                    Action(
                        SKIP,
                        target,
                        f"no new commits since {state.tested_sha[:12]}",
                        issue.number,
                    )
                )
                continue
            kind, reason = REDO, f"new commits, now at {target.head_sha[:12]}"

        if triggered >= limit:
            actions.append(
                Action(
                    SKIP,
                    target,
                    f"nightly limit of {limit} runs reached",
                    issue.number if issue else None,
                )
            )
            continue
        triggered += 1
        actions.append(Action(kind, target, reason, issue.number if issue else None))

    return actions


def format_summary(actions: list[Action], since: str) -> str:
    """Render the job summary table for the GitHub Actions run."""
    lines: list[str] = [
        "## Nightly new-check watcher",
        "",
        f"Pull requests with activity since `{since}`.",
        "",
    ]
    if not actions:
        lines.append("_No llvm-project pull request added a new check._")
        return "\n".join(lines) + "\n"

    lines.append("| PR | Check | Action | Issue | Reason |")
    lines.append("|----|-------|--------|-------|--------|")
    for action in actions:
        issue: str = f"#{action.issue_number}" if action.issue_number else "-"
        # A failure reason is a server message and may contain a pipe.
        reason: str = action.reason.replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| [#{action.target.pr_number}]({action.target.pr_url}) "
            f"| `{action.target.check_name}` | {action.kind} | {issue} "
            f"| {reason} |"
        )
    started: int = sum(1 for action in actions if action.kind not in {SKIP, FAILED})
    lines.append("")
    lines.append(f"**Triggered {started} of {len(actions)} candidate run(s).**")
    return "\n".join(lines) + "\n"


def load_targets(path: str) -> list[CheckTarget]:
    try:
        with open(path, encoding="utf-8") as stream:
            return [CheckTarget(**entry) for entry in json.load(stream)]
    except (OSError, TypeError, ValueError) as error:
        raise SystemExit(f"Error: could not read targets from {path}: {error}")


def fetch_issues(client: GitHubClient, repo: str) -> list[IssueRef]:
    """Fetch every CTIT issue, dropping pull requests from the same endpoint."""
    payloads: list[IssuePayload] = client.paginate(
        f"repos/{repo}/issues", {"state": "all", "sort": "created", "direction": "desc"}
    )
    if len(payloads) >= MAX_PAGES * PAGE_SIZE:
        # Older issues fell off the listing, so a duplicate could be opened.
        print(
            f"Warning: only the newest {len(payloads)} issues were read; "
            "matches against older issues may be missed",
            file=sys.stderr,
        )
    return [parse_issue_ref(entry) for entry in payloads if "pull_request" not in entry]


def make_issue_probe(
    client: GitHubClient, repo: str, since: str
) -> Callable[[IssueRef], IssueState]:
    """Build the lookup that reads what earlier nightly runs left on an issue."""

    def probe(issue: IssueRef) -> IssueState:
        # Every comment, not just recent ones: the revision we last analysed may
        # have been recorded months ago.
        comments: list[dict[str, Any]] = client.paginate(
            f"repos/{repo}/issues/{issue.number}/comments"
        )
        return read_issue_state(issue, comments, since)

    return probe


def create_issue(client: GitHubClient, repo: str, target: CheckTarget) -> int:
    """Open the issue, then label it so check-tester.yaml picks it up."""
    # Only the first line is parsed by parse_issue.py; keep every other line
    # free of colons so it is never mistaken for a check option.
    body: str = (
        f"{target.pr_url} {target.check_name}\n\n{format_marker(target.head_sha)}\n"
    )
    issue: dict[str, Any] = client.post(
        f"repos/{repo}/issues",
        {"title": f"[Test] {target.check_name}", "body": body},
    )
    number: int = issue["number"]
    add_label(client, repo, number, target.language)
    return number


def add_label(client: GitHubClient, repo: str, number: int, language: str) -> None:
    client.post(f"repos/{repo}/issues/{number}/labels", {"labels": [language]})


def post_redo(
    client: GitHubClient, repo: str, number: int, target: CheckTarget
) -> None:
    body: str = (
        f"{format_marker(target.head_sha)}\n\n"
        f"/redo\n\n"
        f"New commits on the pull request, now at {target.head_sha[:12]}.\n"
    )
    client.post(f"repos/{repo}/issues/{number}/comments", {"body": body})


def apply_action(client: GitHubClient, repo: str, action: Action) -> Action:
    """Perform one planned action and return it with the issue number filled in."""
    if action.kind == CREATE:
        number: int = create_issue(client, repo, action.target)
        return Action(action.kind, action.target, action.reason, number)
    if action.kind == REDO:
        assert action.issue_number is not None
        post_redo(client, repo, action.issue_number, action.target)
    return action


def apply_actions(
    client: GitHubClient, repo: str, actions: list[Action]
) -> list[Action]:
    """Run every planned action, recording failures instead of aborting.

    One failure must not hide the rest of the night's work: the summary is the
    only record of what happened, so every action gets its turn and the plan is
    returned with failures marked.
    """
    applied: list[Action] = []
    for action in actions:
        try:
            applied.append(apply_action(client, repo, action))
        except GitHubError as error:
            print(f"Error: {error}", file=sys.stderr)
            applied.append(
                Action(FAILED, action.target, str(error), action.issue_number)
            )
    return applied


def _write_summary(summary: str, path: str) -> None:
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(summary)


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="CTIT repository (owner/name)")
    parser.add_argument(
        "--targets",
        default=OUTPUT_FILE,
        help=f"Targets file from find_new_check_prs (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum analysis runs to trigger (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        default=DEFAULT_SINCE_HOURS,
        help=f"Activity window in hours (default: {DEFAULT_SINCE_HOURS})",
    )
    parser.add_argument(
        "--summary-file",
        default=SUMMARY_FILE,
        help=f"Markdown summary to write (default: {SUMMARY_FILE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report the plan without acting"
    )
    args: argparse.Namespace = parser.parse_args()

    token: str | None = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    since: str = since_timestamp(args.since_hours)
    client: GitHubClient = GitHubClient(token)
    targets: list[CheckTarget] = load_targets(args.targets)

    try:
        actions: list[Action] = plan_actions(
            targets,
            fetch_issues(client, args.repo),
            make_issue_probe(client, args.repo, since),
            args.limit,
        )
    except GitHubError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    if not args.dry_run:
        actions = apply_actions(client, args.repo, actions)

    for action in actions:
        issue: str = f" (issue #{action.issue_number})" if action.issue_number else ""
        print(
            f"{action.kind}: PR #{action.target.pr_number} "
            f"{action.target.check_name}{issue} - {action.reason}"
        )

    _write_summary(format_summary(actions, since), args.summary_file)

    if any(action.kind == FAILED for action in actions):
        sys.exit(1)


if __name__ == "__main__":
    main()
