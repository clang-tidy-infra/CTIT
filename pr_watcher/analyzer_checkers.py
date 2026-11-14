"""Find Clang Static Analyzer checkers that a pull request adds."""

from __future__ import annotations

import re
from typing import Any, TypeAlias

CHECKERS_TD = "clang/include/clang/StaticAnalyzer/Checkers/Checkers.td"
_DOCS_RE: re.Pattern[str] = re.compile(r"^clang/docs/analyzer/checkers\.(?:md|rst)$")

# The corpus has no code for these frameworks, so a run would only produce an
# empty report.
SKIPPED_PACKAGES: frozenset[str] = frozenset({"webkit", "osx", "fuchsia", "mpi"})

# Matches the name in an added line such as '+def FooChecker : Checker<"Foo">,'.
_ADDED_CHECKER_RE: re.Pattern[str] = re.compile(
    r'^\+.*\bChecker\s*<\s*"([^"]+)"', re.MULTILINE
)
# Matches an added or removed checker heading, "+#### unix.Stream (C)" in
# checkers.md or "+unix.Stream (C)" above an underline in checkers.rst. A few
# headings have no language list.
_HEADING_RE: re.Pattern[str] = re.compile(
    r"^([+-])(?:#+\s+)?([A-Za-z][\w-]*(?:\.[\w-]+)+)(?:\s*\(([^)]*)\))?\s*$",
    re.MULTILINE,
)

CheckerName: TypeAlias = str  # e.g. "alpha.unix.Stream"
PullFile: TypeAlias = dict[str, Any]  # one entry of GET /pulls/{n}/files


def _added_short_names(files: list[PullFile]) -> set[str]:
    for entry in files:
        if entry.get("filename") == CHECKERS_TD:
            return set(_ADDED_CHECKER_RE.findall(entry.get("patch") or ""))
    return set()


def _language(languages: str) -> str:
    """Pick the CTIT trigger label from a heading's languages, e.g. "C, C++"."""
    return "c" if {part.strip() for part in languages.split(",")} == {"C"} else "cpp"


def new_analyzer_checkers(files: list[PullFile]) -> dict[CheckerName, str]:
    """Map the analyzer checkers this PR adds to their CTIT trigger labels.

    A Checkers.td line names a checker without its package, which comes from an
    enclosing block that the diff rarely shows. The full name is therefore taken
    from a documentation heading the PR adds. The heading counts if Checkers.td
    gains a ``Checker<"...">`` line with the same short name, or if it replaces
    the heading of the same checker in alpha.
    """
    added: dict[CheckerName, str] = {}
    removed: set[CheckerName] = set()
    for entry in files:
        if not _DOCS_RE.match(entry.get("filename", "")):
            continue
        sign: str
        name: CheckerName
        languages: str
        for sign, name, languages in _HEADING_RE.findall(entry.get("patch") or ""):
            if sign == "+":
                added[name] = _language(languages)
            else:
                removed.add(name)

    # Moving a checker out of alpha may move its package block instead of its
    # def, so Checkers.td does not always re-add the checker line.
    short_names: set[str] = _added_short_names(files)
    return {
        name: language
        for name, language in added.items()
        if name.rsplit(".", 1)[-1] in short_names or f"alpha.{name}" in removed
    }


def skip_reason(name: CheckerName) -> str | None:
    """Return why a checker is not worth a CTIT run, or None to run it."""
    for package in name.split(".")[:-1]:
        if package in SKIPPED_PACKAGES:
            return f"the corpus has no {package} code"
    return None
