#!/usr/bin/env python3
"""Find llvm-project pull requests that add a brand-new clang-tidy check."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeAlias

from crash_detection.select_modified_checks import Registration, parse_registrations
from pr_watch.github_api import GitHubClient, GitHubError

LLVM_REPO = "llvm/llvm-project"
DEFAULT_SINCE_HOURS = 24
OUTPUT_FILE = "new-check-prs.json"

# llvm-project labels PRs by touched path, and check PRs carry a [clang-tidy]
# title tag by convention; the union of both keeps recall high.
SEARCH_FILTERS: tuple[str, ...] = ("label:clang-tidy", '"clang-tidy" in:title')

_TIDY_ROOT = "clang-tools-extra/clang-tidy/"
_DOCS_ROOT = "clang-tools-extra/docs/clang-tidy/checks/"
_TESTS_ROOT = "clang-tools-extra/test/clang-tidy/checkers/"

# Matches a new clang-tools-extra/clang-tidy/<module>/<Name>Check.{h,cpp}.
_CHECK_FILE_RE: re.Pattern[str] = re.compile(
    rf"^{re.escape(_TIDY_ROOT)}([^/]+)/([^/]+Check)\.(?:h|cpp)$"
)
# Matches docs/clang-tidy/checks/<module>/<stem>.{rst,md}, excluding list.*.
_DOC_RE: re.Pattern[str] = re.compile(
    rf"^{re.escape(_DOCS_ROOT)}([^/]+)/([^/]+)\.(?:rst|md)$"
)
# Matches test/clang-tidy/checkers/<module>/<stem>.<suffix>.
_TEST_RE: re.Pattern[str] = re.compile(
    rf"^{re.escape(_TESTS_ROOT)}([^/]+)/([^/]+)\.(c|cc|cpp|cxx|h|hpp)$"
)

ModuleName: TypeAlias = str  # e.g. "bugprone"
ClassName: TypeAlias = str  # e.g. "SmartPtrInitializationCheck"
CheckName: TypeAlias = str  # e.g. "bugprone-smart-ptr-initialization"
PullFile: TypeAlias = dict[str, Any]  # one entry of GET /pulls/{n}/files


@dataclass(frozen=True)
class CheckTarget:
    """One analysis to trigger: a pull request paired with one new check."""

    pr_number: int
    pr_url: str
    pr_title: str
    updated_at: str
    head_sha: str
    check_name: CheckName
    language: str  # "cpp" or "c", mapped to the CTIT trigger label


def added_patch_blocks(patch: str) -> list[str]:
    """Return runs of consecutive added lines with the leading ``+`` removed.

    Splitting on runs keeps unrelated hunks from being glued together, so a
    ``registerCheck<T>(`` opener can only pair with the string that follows it.
    Added lines are recognised only inside a hunk, because outside one a
    leading ``+`` belongs to a ``+++ b/path`` file header rather than to code.
    """
    blocks: list[str] = []
    current: list[str] = []
    in_hunk: bool = False

    def flush() -> None:
        if current:
            blocks.append("\n".join(current))
            current.clear()

    for line in patch.splitlines():
        if line.startswith("@@"):
            flush()
            in_hunk = True
            continue
        if in_hunk and line.startswith("+"):
            current.append(line[1:])
            continue
        flush()

    flush()
    return blocks


def added_check_classes(files: list[PullFile]) -> set[tuple[ModuleName, ClassName]]:
    """Return check classes whose implementation file is new in this PR."""
    classes: set[tuple[ModuleName, ClassName]] = set()
    for entry in files:
        if entry.get("status") != "added":
            continue
        match: re.Match[str] | None = _CHECK_FILE_RE.match(entry.get("filename", ""))
        if match:
            classes.add((match.group(1), match.group(2)))
    return classes


def added_registrations(files: list[PullFile]) -> set[Registration]:
    """Parse ``registerCheck<T>("name")`` calls added by this PR."""
    registrations: set[Registration] = set()
    for entry in files:
        filename: str = entry.get("filename", "")
        if not filename.startswith(_TIDY_ROOT) or not filename.endswith(
            "TidyModule.cpp"
        ):
            continue
        for block in added_patch_blocks(entry.get("patch") or ""):
            registrations.update(parse_registrations(block, filename))
    return registrations


def added_doc_checks(files: list[PullFile]) -> set[tuple[ModuleName, CheckName]]:
    """Return checks implied by newly added check documentation pages."""
    checks: set[tuple[ModuleName, CheckName]] = set()
    for entry in files:
        if entry.get("status") != "added":
            continue
        match: re.Match[str] | None = _DOC_RE.match(entry.get("filename", ""))
        if not match:
            continue
        module: ModuleName
        stem: str
        module, stem = match.groups()
        if stem == "list":
            continue
        checks.add((module, f"{module}-{stem}"))
    return checks


def check_language(files: list[PullFile], check_name: CheckName) -> str:
    """Pick the CTIT trigger label from the suffixes of the check's new tests."""
    module: ModuleName
    stem: str
    module, _, stem = check_name.partition("-")
    suffixes: set[str] = set()
    for entry in files:
        if entry.get("status") != "added":
            continue
        match: re.Match[str] | None = _TEST_RE.match(entry.get("filename", ""))
        if not match:
            continue
        test_module, basename, suffix = match.groups()
        if test_module != module:
            continue
        if basename != stem and not basename.startswith(f"{stem}-"):
            continue
        suffixes.add(suffix)
    if suffixes and suffixes <= {"c", "h"}:
        return "c"
    return "cpp"


def new_check_names(files: list[PullFile]) -> set[CheckName]:
    """Return checks this PR introduces, ignoring aliases of existing checks.

    A check is new when the class it registers is defined by a file this PR
    adds. An alias such as ``cert-mem56-cpp`` registers an existing class from
    another module, so its ``(module, class)`` pair does not match and it is
    dropped.
    """
    classes: set[tuple[ModuleName, ClassName]] = added_check_classes(files)
    if not classes:
        return set()

    # clang-format reflows neighbouring registrations when a new one is
    # inserted, so the diff alone over-reports; the class must be new too.
    names: set[CheckName] = {
        registration.check_name
        for registration in added_registrations(files)
        if (registration.module, registration.class_name) in classes
    }
    if names:
        return names

    # GitHub omits `patch` for files it considers too large, and a check class
    # need not match its file name. Newly documented checks in the same modules
    # stand in for the registrations that could not be read.
    modules: set[ModuleName] = {module for module, _ in classes}
    return {name for module, name in added_doc_checks(files) if module in modules}


def since_timestamp(hours: int, now: datetime | None = None) -> str:
    """Return the ISO 8601 lower bound of the activity window."""
    moment: datetime = now or datetime.now(timezone.utc)
    return (moment - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def search_recent_prs(
    client: GitHubClient, repo: str, since: str, include_drafts: bool
) -> list[dict[str, Any]]:
    """Return open PRs touching clang-tidy that saw activity since ``since``."""
    seen: set[int] = set()
    prs: list[dict[str, Any]] = []
    for search_filter in SEARCH_FILTERS:
        query: str = f"repo:{repo} is:pr is:open {search_filter} updated:>={since}"
        items: list[dict[str, Any]] = client.paginate(
            "search/issues",
            {"q": query, "sort": "updated", "order": "desc"},
            items_key="items",
        )
        for item in items:
            number: int = item["number"]
            if number in seen:
                continue
            seen.add(number)
            if item.get("draft") and not include_drafts:
                continue
            prs.append(item)
    prs.sort(key=lambda item: item["updated_at"], reverse=True)
    return prs


def collect_targets(
    client: GitHubClient, repo: str, since: str, include_drafts: bool
) -> list[CheckTarget]:
    """Turn recently active clang-tidy PRs into one target per new check."""
    targets: list[CheckTarget] = []
    for pull in search_recent_prs(client, repo, since, include_drafts):
        number: int = pull["number"]
        files: list[PullFile] = client.paginate(f"repos/{repo}/pulls/{number}/files")
        names: set[CheckName] = new_check_names(files)
        if not names:
            continue
        # Only PRs that survived the filter cost this extra request; the search
        # result carries no head revision.
        head_sha: str = client.get(f"repos/{repo}/pulls/{number}")["head"]["sha"]
        for check_name in sorted(names):
            targets.append(
                CheckTarget(
                    pr_number=number,
                    pr_url=f"https://github.com/{repo}/pull/{number}",
                    pr_title=pull["title"],
                    updated_at=pull["updated_at"],
                    head_sha=head_sha,
                    check_name=check_name,
                    language=check_language(files, check_name),
                )
            )
    return targets


def write_targets(targets: list[CheckTarget], output: str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as stream:
        json.dump([asdict(target) for target in targets], stream, indent=2)
        stream.write("\n")


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=LLVM_REPO, help="Upstream repository")
    parser.add_argument(
        "--since-hours",
        type=int,
        default=DEFAULT_SINCE_HOURS,
        help=f"Activity window in hours (default: {DEFAULT_SINCE_HOURS})",
    )
    parser.add_argument(
        "--include-drafts",
        action="store_true",
        help="Also consider draft pull requests",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help=f"File to write the targets to (default: {OUTPUT_FILE})",
    )
    args: argparse.Namespace = parser.parse_args()

    token: str | None = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN is not set", file=sys.stderr)
        sys.exit(1)

    since: str = since_timestamp(args.since_hours)
    print(f"Searching {args.repo} for clang-tidy PRs updated since {since}")
    try:
        targets: list[CheckTarget] = collect_targets(
            GitHubClient(token), args.repo, since, args.include_drafts
        )
    except GitHubError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    for target in targets:
        print(
            f"PR #{target.pr_number} adds {target.check_name} "
            f"({target.language}) at {target.head_sha[:12]} - {target.pr_title}"
        )
    print(f"Found {len(targets)} new check(s)")

    try:
        write_targets(targets, args.output)
    except OSError as error:
        print(f"Error: could not write {args.output}: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
