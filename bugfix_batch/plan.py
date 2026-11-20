"""The batch plan, handed from one job of the bugfix track to the next.

Dependencies of the track point one way: this package imports pr_watcher,
testers and crash_detection, and none of them may import it, so nothing here
can break the new-check track.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PLAN_DIR = "batch"
PLAN_FILE = "plan.json"
BUILD_FILE = "build.json"
LLVM_DIR = "llvm-project"

# The paths apply_patch.sh excludes, and unit tests, which CTIT does not build.
APPLY_EXCLUDES: tuple[str, ...] = (
    "--exclude=*/test/*",
    "--exclude=*/unittests/*",
    "--exclude=*.rst",
    "--exclude=*.md",
)


@dataclass(frozen=True)
class BatchEntry:
    """One pull request of the batch and the checks to report on."""

    pr_number: int
    pr_url: str
    pr_title: str
    head_sha: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class Skipped:
    """A pull request left out of the batch, and why."""

    pr_number: int
    pr_url: str
    pr_title: str
    reason: str

    @classmethod
    def of(cls, entry: BatchEntry, reason: str) -> Skipped:
        return cls(entry.pr_number, entry.pr_url, entry.pr_title, reason)


@dataclass(frozen=True)
class Plan:
    entries: tuple[BatchEntry, ...]
    skipped: tuple[Skipped, ...]


@dataclass(frozen=True)
class BuildResult:
    """Which entries of the plan made it into the patched clang-tidy."""

    llvm_revision: str
    built: tuple[BatchEntry, ...]
    failed: tuple[Skipped, ...]


def patch_path(plan_dir: str, pr_number: int) -> Path:
    return Path(plan_dir) / f"{pr_number}.diff"


def joined_checks(entries: tuple[BatchEntry, ...]) -> str:
    """Return the entries' checks as a ``--check-name`` value."""
    return ",".join(check for entry in entries for check in entry.checks)


def set_github_output(key: str, value: str) -> None:
    path: str | None = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(f"{key}={value}\n")


def table_cell(text: str) -> str:
    """Escape PR titles and server messages for a Markdown table."""
    return text.replace("|", "\\|").replace("\n", " ")


def git_apply(llvm_dir: str, patch: Path, *flags: str) -> bool:
    """Run ``git apply`` on *patch* and report whether it succeeded."""
    command: list[str] = ["git", "-C", llvm_dir, "apply", *APPLY_EXCLUDES, *flags]
    command.append(str(patch.resolve()))
    return subprocess.run(command, check=False).returncode == 0


def _entry(data: dict[str, Any]) -> BatchEntry:
    return BatchEntry(**{**data, "checks": tuple(data["checks"])})


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        payload: dict[str, Any] = json.load(stream)
    return payload


def write_plan(plan: Plan, plan_dir: str) -> None:
    _write(Path(plan_dir) / PLAN_FILE, asdict(plan))


def read_plan(plan_dir: str) -> Plan:
    data: dict[str, Any] = _read(Path(plan_dir) / PLAN_FILE)
    return Plan(
        entries=tuple(_entry(entry) for entry in data["entries"]),
        skipped=tuple(Skipped(**entry) for entry in data["skipped"]),
    )


def write_build_result(result: BuildResult, plan_dir: str) -> None:
    _write(Path(plan_dir) / BUILD_FILE, asdict(result))


def read_build_result(plan_dir: str) -> BuildResult:
    data: dict[str, Any] = _read(Path(plan_dir) / BUILD_FILE)
    return BuildResult(
        llvm_revision=data["llvm_revision"],
        built=tuple(_entry(entry) for entry in data["built"]),
        failed=tuple(Skipped(**entry) for entry in data["failed"]),
    )
