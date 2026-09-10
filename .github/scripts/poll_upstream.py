#!/usr/bin/env python3
"""Detect open upstream LLVM PRs that modify a clang-tidy check.

Emits one TSV line per candidate to stdout: ``<pr_url>\\t<check_name>\\t<pr_title>``.
Informational/skip messages go to stderr.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

UPSTREAM_REPO = "llvm/llvm-project"
PR_LIST_LIMIT = 100
MAX_AGE_DAYS = 7

SOURCE_RE = re.compile(
    r"^clang-tools-extra/clang-tidy/([a-z0-9-]+)/([A-Z][A-Za-z0-9]+)Check\.(cpp|h)$"
)
DOC_RE = re.compile(
    r"^clang-tools-extra/docs/clang-tidy/checks/([a-z0-9-]+)/([a-z0-9-]+)\.rst$"
)
CLANG_TIDY_PREFIX_RE = re.compile(r"^\[clang-tidy\]", re.IGNORECASE)
ADD_WORD_RE = re.compile(r"\badd\b", re.IGNORECASE)
CHECK_WORD_RE = re.compile(r"\bcheck\b", re.IGNORECASE)


def camel_to_kebab(name: str) -> str:
    # Acronyms like "STL" expand to "s-t-l"; LLVM check class names use title case so this is fine.
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def looks_like_new_check(title: str) -> bool:
    """True when title has the ``[clang-tidy]`` prefix and contains both
    ``add`` and ``check`` as whole words.

    Matches "[clang-tidy] Add foo check" but rejects "Extend foo to ..." or
    "Fix false positive in foo".
    """
    return bool(
        CLANG_TIDY_PREFIX_RE.search(title)
        and ADD_WORD_RE.search(title)
        and CHECK_WORD_RE.search(title)
    )


def gh_json(*args: str) -> Any:
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def candidate_prs() -> Any:
    cutoff = (
        (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).date().isoformat()
    )
    search = f"clang-tidy in:title created:>={cutoff}"
    return gh_json(
        "pr",
        "list",
        "--repo",
        UPSTREAM_REPO,
        "--state",
        "open",
        "--limit",
        str(PR_LIST_LIMIT),
        "--search",
        search,
        "--json",
        "url,number,title,isDraft",
    )


def pr_files(pr_number: int) -> list[str]:
    data = gh_json(
        "pr",
        "view",
        str(pr_number),
        "--repo",
        UPSTREAM_REPO,
        "--json",
        "files",
    )
    return [str(f["path"]) for f in data.get("files", [])]


def detect_check(file_paths: list[str]) -> str | None:
    """Return ``<category>-<check>`` if the PR modifies a check.

    Prefer source-file evidence (``<CheckName>Check.cpp/h``); fall back to
    docs only when no source files changed. If multiple checks are touched
    (e.g. a new check plus an alias), pick the alphabetically first and log.
    """
    source_hits: set[str] = set()
    doc_hits: set[str] = set()
    for path in file_paths:
        if m := SOURCE_RE.match(path):
            source_hits.add(f"{m.group(1)}-{camel_to_kebab(m.group(2))}")
        elif m := DOC_RE.match(path):
            doc_hits.add(f"{m.group(1)}-{m.group(2)}")

    pool = source_hits or doc_hits
    if not pool:
        return None

    chosen = sorted(pool)[0]
    if len(pool) > 1:
        print(
            f"# multi-check PR {sorted(pool)} -> picked {chosen}",
            file=sys.stderr,
        )
    return chosen


def main() -> None:
    prs = candidate_prs()
    if len(prs) == PR_LIST_LIMIT:
        print(
            f"# warning: hit PR_LIST_LIMIT={PR_LIST_LIMIT}; some candidates may be missed",
            file=sys.stderr,
        )
    for pr in prs:
        if pr.get("isDraft"):
            print(f"# skip #{pr['number']} (draft): {pr['title']}", file=sys.stderr)
            continue
        if not looks_like_new_check(pr["title"]):
            print(
                f"# skip #{pr['number']} (not a new-check title): {pr['title']}",
                file=sys.stderr,
            )
            continue
        check = detect_check(pr_files(pr["number"]))
        if check is None:
            print(f"# skip #{pr['number']}: {pr['title']}", file=sys.stderr)
            continue
        print(f"{pr['url']}\t{check}\t{pr['title']}")


if __name__ == "__main__":
    main()
