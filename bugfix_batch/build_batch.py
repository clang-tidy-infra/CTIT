"""Apply the batch to LLVM and build clang-tidy, dropping what does not compile.

Patches go in one at a time with an incremental build after each, so a failure
points at one pull request and costs only that pull request its place. Entries
touch nothing but check sources, so each step recompiles a few files and links.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from bugfix_batch.plan import (
    LLVM_DIR,
    PLAN_DIR,
    BatchEntry,
    BuildResult,
    Plan,
    Skipped,
    git_apply,
    joined_checks,
    patch_path,
    read_plan,
    set_github_output,
    write_build_result,
)

BUILD_DIR = "llvm-project/build"


def integrate(
    entries: tuple[BatchEntry, ...],
    apply: Callable[[BatchEntry], bool],
    revert: Callable[[BatchEntry], bool],
    build: Callable[[], bool],
) -> tuple[list[BatchEntry], list[Skipped]]:
    """Add entries one by one, reverting each one that breaks the build."""
    built: list[BatchEntry] = []
    failed: list[Skipped] = []

    for entry in entries:
        if not apply(entry):
            failed.append(Skipped.of(entry, "patch does not apply"))
        elif build():
            built.append(entry)
        elif revert(entry):
            failed.append(Skipped.of(entry, "does not compile"))
        else:
            raise RuntimeError(f"could not revert PR {entry.pr_number}")

    # A failed link leaves no binary behind, and the analysis needs one that
    # matches the surviving patches.
    if failed and not build():
        raise RuntimeError("clang-tidy does not build without the failed patches")
    return built, failed


def build_clang_tidy(build_dir: str) -> bool:
    command: list[str] = ["ninja", "-C", build_dir, "clang-tidy"]
    jobs: str | None = os.environ.get("CTIT_JOBS")
    if jobs:
        command += ["-j", jobs]
    return subprocess.run(command, check=False).returncode == 0


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-dir", default=LLVM_DIR, help="LLVM checkout to patch")
    parser.add_argument("--build-dir", default=BUILD_DIR, help="Configured LLVM build")
    parser.add_argument("--plan-dir", default=PLAN_DIR, help="Directory of the plan")
    args: argparse.Namespace = parser.parse_args()

    plan: Plan = read_plan(args.plan_dir)
    llvm_revision: str = subprocess.run(
        ["git", "-C", args.llvm_dir, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    def patch(entry: BatchEntry) -> Path:
        return patch_path(args.plan_dir, entry.pr_number)

    try:
        built, failed = integrate(
            plan.entries,
            lambda entry: git_apply(args.llvm_dir, patch(entry)),
            lambda entry: git_apply(args.llvm_dir, patch(entry), "--reverse"),
            lambda: build_clang_tidy(args.build_dir),
        )
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    result: BuildResult = BuildResult(llvm_revision, tuple(built), tuple(failed))
    write_build_result(result, args.plan_dir)
    for skip in failed:
        print(f"Dropped PR {skip.pr_number}: {skip.reason}")
    print(f"Built {len(built)} of {len(plan.entries)} pull request(s)")
    set_github_output("checks", joined_checks(result.built))


if __name__ == "__main__":
    main()
