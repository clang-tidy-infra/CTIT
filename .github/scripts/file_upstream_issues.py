#!/usr/bin/env python3
"""For each TSV candidate, file a CTIT issue unless one already exists."""

import json
import os
import subprocess
import sys
from pathlib import Path


def issue_already_exists(repo: str, pr_url: str) -> bool:
    result = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--search",
            f'"{pr_url}" in:body',
            "--json",
            "number",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(json.loads(result.stdout))


def file_issue(repo: str, pr_url: str, check_name: str) -> None:
    subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            f"Upstream: {check_name} ({pr_url})",
            "--label",
            "cpp",
            "--body",
            f"{pr_url} {check_name}",
        ],
        check=True,
    )


def main() -> None:
    repo = os.environ.get("REPO")
    if not repo:
        sys.exit("REPO env var required")

    candidates_path = Path(sys.argv[1] if len(sys.argv) > 1 else "candidates.tsv")

    for line in candidates_path.read_text().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            print(f"Skipping malformed line: {line!r}", file=sys.stderr)
            continue
        pr_url, check_name = parts[0], parts[1]

        if issue_already_exists(repo, pr_url):
            print(f"Skip {pr_url} (already tracked)")
            continue

        print(f"Filing issue for {pr_url} ({check_name})")
        file_issue(repo, pr_url, check_name)


if __name__ == "__main__":
    main()
