#!/usr/bin/env python3
"""Post the daily clang-tidy check timings as a comment on a tracking issue.

Each run adds one comment to the open issue labelled ``check-timings`` and
opens that issue if there is none. The comment compares the timings with the
previous comment on the issue, so the issue is also the history of timings.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from crash_detection.parse_check_profile import combine_profiles, load_profiles
from pr_watcher.github_api import PAGE_SIZE, GitHubClient, GitHubError

TRACKING_LABEL = "check-timings"
TRACKING_TITLE = "Daily check timings"
WORKFLOW_FILE = "daily-check-timings.yaml"
LLVM_REPO_URL = "https://github.com/llvm/llvm-project"
# A change is notable only above both thresholds. Between two consecutive runs
# on the same runner, checks drifted by about 2% (at most ~13%), and the
# slowest checks by up to ~35 s.
NOTABLE_PERCENT = 10.0
NOTABLE_SECONDS = 10.0

_MARKER_RE: re.Pattern[str] = re.compile(r"<!-- ctit-check-timings (\{.*?\}) -->")
_DATE_RE: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{7,40}$")
# The table with every check is also how the next run reads these timings.
_TABLE_HEADER = "| Check | Wall time (s) | % of total | Change |"
_ROW_RE: re.Pattern[str] = re.compile(r"^\| `([^`|]+)` \| (\d+(?:\.\d+)?) \|")


@dataclass(frozen=True)
class TimingsRecord:
    """One run's check timings, as written to and read back from a comment."""

    date: str
    llvm_revision: str
    runner: str
    timings: dict[str, float]
    url: str | None = None  # The comment the record was read from.


def format_marker(record: TimingsRecord) -> str:
    meta: str = json.dumps(
        {"date": record.date, "llvm": record.llvm_revision, "runner": record.runner}
    )
    # Escaped so a runner name cannot end the HTML comment early.
    meta = meta.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<!-- ctit-check-timings {meta} -->"


def parse_comment(body: str, url: str | None = None) -> TimingsRecord | None:
    """Read the record back from a comment written by ``build_comment``."""
    match: re.Match[str] | None = _MARKER_RE.search(body)
    if not match:
        return None
    try:
        meta: Any = json.loads(match.group(1))
    except ValueError:
        return None
    if not isinstance(meta, dict):
        return None

    timings: dict[str, float] = {}
    in_table: bool = False
    for line in body.splitlines():
        if line.strip() == _TABLE_HEADER:
            in_table = True
        elif in_table:
            row: re.Match[str] | None = _ROW_RE.match(line)
            if row:
                timings[row.group(1)] = float(row.group(2))
            elif not line.startswith("|"):
                break
    if not timings:
        return None

    # Anyone can comment on the issue, so only trust well-formed values.
    date: str = str(meta.get("date", ""))
    llvm_revision: str = str(meta.get("llvm", "")).lower()
    return TimingsRecord(
        date=date if _DATE_RE.match(date) else "previous run",
        llvm_revision=llvm_revision if _SHA_RE.match(llvm_revision) else "",
        runner=re.sub(r"[`\s]+", " ", str(meta.get("runner", ""))).strip(),
        timings=timings,
        url=url,
    )


def format_change(previous: float | None, current: float | None) -> str:
    if previous is None:
        return "new"
    if current is None:
        return "removed"
    delta: float = current - previous
    if previous == 0:
        return f"{delta:+.2f}"
    return f"{delta:+.2f} ({delta / previous:+.1%})"


def _is_notable(previous: float, current: float) -> bool:
    delta: float = abs(current - previous)
    if delta < NOTABLE_SECONDS:
        return False
    return previous == 0 or delta / previous * 100 >= NOTABLE_PERCENT


def notable_changes(
    previous: dict[str, float], current: dict[str, float]
) -> list[tuple[str, float | None, float | None]]:
    """Return (check, previous, current) for added, removed and notable checks.

    The biggest absolute changes come first.
    """
    rows: list[tuple[str, float | None, float | None]] = []
    for check in sorted(previous.keys() | current.keys()):
        before: float | None = previous.get(check)
        after: float | None = current.get(check)
        if before is None or after is None or _is_notable(before, after):
            rows.append((check, before, after))
    rows.sort(key=lambda row: -abs((row[2] or 0.0) - (row[1] or 0.0)))
    return rows


def _seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _link(text: str, url: str | None) -> str:
    return f"[{text}]({url})" if url else text


def _format_llvm(current: str, previous: TimingsRecord | None) -> str:
    text: str = f"[`{current[:12]}`]({LLVM_REPO_URL}/commit/{current})"
    if previous is None or not previous.llvm_revision:
        return text
    if previous.llvm_revision == current:
        return f"{text} (unchanged since {previous.date})"
    compare: str = f"{LLVM_REPO_URL}/compare/{previous.llvm_revision}...{current}"
    return f"{text} ([changes since {previous.date}]({compare}))"


def _format_total(current: float, previous: TimingsRecord | None) -> str:
    text: str = f"{current:.2f} s"
    if previous is None:
        return text
    before: float = sum(previous.timings.values())
    delta: float = current - before
    change: str = f"{delta:+.2f} s"
    if before > 0:
        change += f", {delta / before:+.1%}"
    return f"{text} ({change} vs {_link(previous.date, previous.url)})"


def build_comment(
    current: TimingsRecord,
    machine: str,
    run_url: str,
    previous: TimingsRecord | None,
) -> str:
    total: float = sum(current.timings.values())
    lines: list[str] = [
        format_marker(current),
        f"## Check timings: {current.date}",
        "",
        f"- **Runner:** `{current.runner}` ({machine})",
        f"- **LLVM:** {_format_llvm(current.llvm_revision, previous)}",
        f"- **Workflow run:** {run_url}",
        f"- **Total wall time:** {_format_total(total, previous)}",
        "",
    ]

    if previous is None:
        lines += ["_No earlier timings on this issue to compare with._", ""]
    else:
        lines += [
            f"### Changes since {_link(previous.date, previous.url)}",
            "",
        ]
        if previous.runner and previous.runner != current.runner:
            lines += [
                "> [!NOTE]",
                (
                    f"> The previous run used runner `{previous.runner}`, so the "
                    "changes include the hardware difference."
                ),
                "",
            ]
        changes = notable_changes(previous.timings, current.timings)
        if changes:
            lines += [
                f"| Check | {previous.date} (s) | {current.date} (s) | Change |",
                "|-------|------:|------:|-------:|",
            ]
            lines += [
                f"| `{check}` | {_seconds(before)} | {_seconds(after)} "
                f"| {format_change(before, after)} |"
                for check, before, after in changes
            ]
        else:
            lines.append(
                f"No check changed by more than {NOTABLE_PERCENT:.0f}% "
                f"and {NOTABLE_SECONDS:.0f} s."
            )
        lines.append("")

    lines += [
        "<details>",
        f"<summary>All {len(current.timings)} checks</summary>",
        "",
        _TABLE_HEADER,
        "|-------|--------------:|-----------:|-------:|",
    ]
    before_timings: dict[str, float] | None = previous.timings if previous else None
    for check, wall in sorted(current.timings.items(), key=lambda x: (-x[1], x[0])):
        share: float = wall / total if total > 0 else 0.0
        change: str = (
            "-"
            if before_timings is None
            else format_change(before_timings.get(check), wall)
        )
        lines.append(f"| `{check}` | {wall:.2f} | {share:.1%} | {change} |")
    lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def _cpu_model() -> str | None:
    try:
        output: str = subprocess.run(
            ["lscpu"],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "LC_ALL": "C"},
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in output.splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "Model name" and value.strip():
            return value.strip()
    return None


def _memory_gib() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return None


def describe_machine() -> str:
    """Describe the hardware the timings were measured on."""
    parts: list[str] = [f"{platform.system()} {platform.machine()}"]
    model: str | None = _cpu_model()
    if model:
        parts.append(model)
    parts.append(f"{os.cpu_count() or '?'} CPUs")
    memory: float | None = _memory_gib()
    if memory is not None:
        parts.append(f"{memory:.0f} GiB RAM")
    return ", ".join(parts)


def find_tracking_issue(client: GitHubClient, repo: str) -> dict[str, Any] | None:
    issues: list[dict[str, Any]] = client.get(
        f"repos/{repo}/issues",
        {"labels": TRACKING_LABEL, "state": "open", "per_page": PAGE_SIZE},
    )
    for issue in issues:
        if "pull_request" not in issue:
            return issue
    return None


def fetch_latest_record(
    client: GitHubClient, repo: str, issue: dict[str, Any]
) -> TimingsRecord | None:
    """Return the newest timings a bot posted on the issue."""
    # Comments are listed oldest first, so walk the pages from the last one.
    last_page: int = max(1, math.ceil(issue.get("comments", 0) / PAGE_SIZE))
    for page in range(last_page, 0, -1):
        comments: list[dict[str, Any]] = client.get(
            f"repos/{repo}/issues/{issue['number']}/comments",
            {"per_page": PAGE_SIZE, "page": page},
        )
        for comment in reversed(comments):
            if (comment.get("user") or {}).get("type") != "Bot":
                continue
            record: TimingsRecord | None = parse_comment(
                comment.get("body") or "", comment.get("html_url")
            )
            if record:
                return record
    return None


def create_tracking_issue(client: GitHubClient, repo: str) -> int:
    try:
        client.post(
            f"repos/{repo}/labels",
            {
                "name": TRACKING_LABEL,
                "color": "c5def5",
                "description": "Daily clang-tidy check timings",
            },
        )
    except GitHubError as error:
        if "already_exists" not in str(error):
            raise
    workflow_url: str = f"https://github.com/{repo}/actions/workflows/{WORKFLOW_FILE}"
    body: str = (
        f"The [Daily Check Timings]({workflow_url}) workflow posts the wall time "
        "of every clang-tidy check, summed over all test projects, as a comment "
        "below. Each comment lists the changes since the previous one.\n"
    )
    issue: dict[str, Any] = client.post(
        f"repos/{repo}/issues",
        {"title": TRACKING_TITLE, "body": body, "labels": [TRACKING_LABEL]},
    )
    number: int = issue["number"]
    return number


def post_comment(client: GitHubClient, repo: str, number: int, body: str) -> str:
    comment: dict[str, Any] = client.post(
        f"repos/{repo}/issues/{number}/comments", {"body": body}
    )
    url: str = comment["html_url"]
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="CTIT repository (owner/name)")
    parser.add_argument(
        "--log-dir", default="logs", help="Directory containing .log files"
    )
    parser.add_argument(
        "--llvm-revision", required=True, help="LLVM commit clang-tidy was built from"
    )
    parser.add_argument("--runner", required=True, help="Name of the runner")
    parser.add_argument("--run-url", required=True, help="URL of the workflow run")
    parser.add_argument("--output", help="Also write the comment to this file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Build the comment without posting it"
    )
    args = parser.parse_args()

    token: str | None = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    profiles = load_profiles(args.log_dir)
    if not profiles:
        print(f"Error: no profiling data found in {args.log_dir}", file=sys.stderr)
        sys.exit(1)

    current = TimingsRecord(
        date=datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        llvm_revision=args.llvm_revision.lower(),
        runner=args.runner,
        # Rounded like the comment, so the next run compares the same numbers.
        timings={
            check: round(wall, 2) for check, wall in combine_profiles(profiles).items()
        },
    )
    client = GitHubClient(token)

    try:
        issue: dict[str, Any] | None = find_tracking_issue(client, args.repo)
        previous: TimingsRecord | None = (
            fetch_latest_record(client, args.repo, issue) if issue else None
        )
        body: str = build_comment(current, describe_machine(), args.run_url, previous)
        if args.output:
            with open(args.output, "w") as f:
                f.write(body)
        if args.dry_run:
            print(body)
            return

        number: int = (
            issue["number"] if issue else create_tracking_issue(client, args.repo)
        )
        print(f"Posted check timings: {post_comment(client, args.repo, number, body)}")
    except GitHubError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
