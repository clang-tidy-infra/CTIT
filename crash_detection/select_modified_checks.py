#!/usr/bin/env python3
"""Select clang-tidy checks whose implementation changed in a git range."""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import TypeAlias

_TIDY_ROOT = "clang-tools-extra/clang-tidy/"
_UTILS_ROOT = f"{_TIDY_ROOT}utils/"
# Matches clang-tools-extra/clang-tidy/<module>/<Name>Check.{cpp,h}.
_CHECK_FILE_RE: re.Pattern[str] = re.compile(
    rf"^{re.escape(_TIDY_ROOT)}([^/]+)/([^/]+Check)\.(?:cpp|h)$"
)
# Matches registerCheck<Type>("check-name"), including clang-format line wraps.
_REGISTER_RE: re.Pattern[str] = re.compile(
    r"registerCheck\s*<\s*([^>]+?)\s*>\s*\(\s*\"([^\"]+)\"",
    re.DOTALL,
)
# This is required because the filename is not always the registered class
# e.g. HeaderGuardCheck.cpp -> LLVMHeaderGuardCheck
#      FloatTypesCheck.h    -> RuntimeFloatCheck
_CLASS_DECL_RE: re.Pattern[str] = re.compile(
    r"\b(?:class|struct)\s+"
    r"(?:[A-Za-z_]\w*\s+)*"
    r"([A-Za-z_]\w*Check)\s*(?::|final\b|\{)"
)


GitRev: TypeAlias = str
CheckName: TypeAlias = str  # e.g. "modernize-use-auto"
ClassName: TypeAlias = str  # e.g. "UseAutoCheck"
ModuleName: TypeAlias = str  # e.g. "modernize"
TidyPath: TypeAlias = (
    str  # e.g. "clang-tools-extra/clang-tidy/modernize/UseAutoCheck.cpp"
)
# (module, class_name) -> check names
ChecksByClass: TypeAlias = dict[tuple[ModuleName, ClassName], set[CheckName]]


# registerCheck<UseAutoCheck>("modernize-use-auto")
# becomes module="modernize", class_name="UseAutoCheck", check_name="modernize-use-auto".
@dataclass(frozen=True)
class Registration:
    module: ModuleName
    class_name: ClassName
    check_name: CheckName


@dataclass
class SelectionResult:
    """Summary printed by CI for one ``base..head`` range."""

    base: GitRev
    head: GitRev
    changed_checks: set[CheckName] = field(default_factory=set)
    changed_utils: set[TidyPath] = field(default_factory=set)


def format_clang_tidy_checks(checks: set[CheckName]) -> str:
    """Return a clang-tidy ``-checks=`` value, e.g. ``-*,modernize-use-auto``."""
    if not checks:
        return ""
    return "-*," + ",".join(sorted(checks))


def format_ci_output(result: SelectionResult) -> str:
    """Print has_checks, check_name, checks, changed_utils."""
    check_name: str = ",".join(sorted(result.changed_checks))
    checks: str = format_clang_tidy_checks(result.changed_checks)
    utils: str = ",".join(sorted(result.changed_utils))
    has_checks: str = "true" if result.changed_checks else "false"
    text: str = "\n".join(
        [
            f"has_checks={has_checks}",
            f"check_name={check_name}",
            f"checks={checks}",
            f"changed_utils={utils}",
        ]
    )
    path: str | None = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return text


def _git(repo: str, *args: str, check: bool = True) -> str:
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "-C", repo, *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        detail: str = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def _resolve_revision(repo: str, revision: GitRev) -> GitRev:
    return _git(repo, "rev-parse", f"{revision}^{{commit}}").strip()


def _read_file(repo: str, revision: GitRev, path: TidyPath) -> str | None:
    proc: subprocess.CompletedProcess[str] = subprocess.run(
        ["git", "-C", repo, "show", f"{revision}:{path}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def parse_registrations(source: str, module_file: TidyPath) -> set[Registration]:
    """Parse check registrations from one ``*TidyModule.cpp`` source file."""
    module: ModuleName = module_file[len(_TIDY_ROOT) :].split("/", 1)[0]
    registrations: set[Registration] = set()
    type_name: str
    check_name: CheckName
    for type_name, check_name in _REGISTER_RE.findall(source):
        class_name: ClassName = re.sub(r"\s+", "", type_name).split("::")[-1]
        registrations.add(Registration(module, class_name, check_name))
    return registrations


def _checks_by_class(repo: str, revision: GitRev) -> ChecksByClass:
    paths: list[TidyPath] = _git(
        repo,
        "ls-tree",
        "-r",
        "--name-only",
        revision,
        "--",
        _TIDY_ROOT.rstrip("/"),
    ).splitlines()
    checks_by_class: ChecksByClass = {}
    for path in paths:
        if not path.endswith("TidyModule.cpp"):
            continue
        source: str | None = _read_file(repo, revision, path)
        if source is None:
            continue
        for registration in parse_registrations(source, path):
            key: tuple[ModuleName, ClassName] = (
                registration.module,
                registration.class_name,
            )
            checks_by_class.setdefault(key, set()).add(registration.check_name)
    return checks_by_class


def _changed_tidy_paths(repo: str, base: GitRev, head: GitRev) -> list[TidyPath]:
    output: str = _git(
        repo,
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        base,
        head,
        "--",
        _TIDY_ROOT.rstrip("/"),
    )
    return [path for path in output.splitlines() if path]


def _check_classes(repo: str, revision: GitRev, path: TidyPath) -> set[ClassName]:
    """Find check class names declared by a concrete check file."""
    stem: str
    extension: str
    stem, extension = posixpath.splitext(posixpath.basename(path))
    candidates: set[ClassName] = {stem}
    paths: list[TidyPath] = [path]
    if extension == ".cpp":
        paths.append(f"{posixpath.splitext(path)[0]}.h")

    for candidate_path in paths:
        source: str | None = _read_file(repo, revision, candidate_path)
        if source:
            candidates.update(_CLASS_DECL_RE.findall(source))
    return candidates


def _checks_for_path(
    repo: str, revision: GitRev, path: TidyPath, checks_by_class: ChecksByClass
) -> set[CheckName]:
    match: re.Match[str] | None = _CHECK_FILE_RE.match(path)
    if not match:
        return set()
    module: ModuleName
    _stem: str
    module, _stem = match.groups()
    check_names: set[CheckName] = set()
    for class_name in _check_classes(repo, revision, path):
        check_names.update(checks_by_class.get((module, class_name), set()))
    return check_names


def select_modified_checks(repo: str, base: GitRev, head: GitRev) -> SelectionResult:
    """Return checks and utils that changed in ``base..head``."""
    repo = os.path.abspath(repo)
    resolved_base: GitRev = _resolve_revision(repo, base)
    resolved_head: GitRev = _resolve_revision(repo, head)
    result: SelectionResult = SelectionResult(base=resolved_base, head=resolved_head)
    checks_by_class: ChecksByClass = _checks_by_class(repo, resolved_head)

    for path in _changed_tidy_paths(repo, resolved_base, resolved_head):
        check_names: set[CheckName] = _checks_for_path(
            repo, resolved_head, path, checks_by_class
        )
        if check_names:
            result.changed_checks.update(check_names)
        elif path.startswith(_UTILS_ROOT):
            result.changed_utils.add(path)

    return result


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-dir", required=True, help="Path to llvm-project")
    parser.add_argument("--base", required=True, help="Old LLVM revision")
    parser.add_argument("--head", default="HEAD", help="New LLVM revision")
    parser.add_argument(
        "--format",
        choices=("report", "checks"),
        default="report",
        help="CI log (default) or clang-tidy glob such as -*,check-a,check-b",
    )
    args: argparse.Namespace = parser.parse_args()

    try:
        result: SelectionResult = select_modified_checks(
            args.llvm_dir, args.base, args.head
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    output: str = format_ci_output(result)
    if args.format == "checks":
        print(format_clang_tidy_checks(result.changed_checks))
    else:
        print(output)


if __name__ == "__main__":
    main()
