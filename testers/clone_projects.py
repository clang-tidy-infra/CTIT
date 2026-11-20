#!/usr/bin/env python3
"""Clone test projects defined in projects.json into a work directory."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

from testers.config import Project, load_projects

# Cloning waits on the network, so a few projects are cloned at once.
CLONE_JOBS = 8


def _git(dest_dir: str, *args: str) -> str:
    """Run a git command in dest_dir and return its combined output."""
    return subprocess.run(
        ["git", "-C", dest_dir, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    ).stdout


def _checked_out_commit(dest_dir: str) -> str | None:
    """Return the commit checked out in dest_dir, or None if it is not a clone."""
    result = subprocess.run(
        ["git", "-C", dest_dir, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def clone_project(
    url: str, commit: str, dest_dir: str, sparse_checkout: list[str] | None = None
) -> str:
    """Shallow-fetch a specific commit and check it out; return git's output.

    With sparse_checkout, only the files matching these non-cone patterns are
    checked out, and only their contents are downloaded.
    """
    if os.path.isdir(dest_dir) and _checked_out_commit(dest_dir) == commit:
        # Already checked out, e.g. restored from the CI cache.
        return ""

    output = ""
    if not os.path.isdir(dest_dir):
        # Unlike 'git clone', this does not download the default branch too.
        os.makedirs(dest_dir)
        output += _git(dest_dir, "init", "--quiet")
        output += _git(dest_dir, "remote", "add", "origin", url)

    fetch = ["fetch", "--depth", "1"]
    if sparse_checkout:
        output += _git(
            dest_dir, "sparse-checkout", "set", "--no-cone", *sparse_checkout
        )
        fetch.append("--filter=blob:none")
    output += _git(dest_dir, *fetch, "origin", commit)
    output += _git(dest_dir, "-c", "advice.detachedHead=false", "checkout", commit)
    return output


def _clone(project: Project, work_dir: str) -> None:
    dest_dir = os.path.join(work_dir, project.name)
    try:
        output = clone_project(
            project.url, project.commit, dest_dir, project.sparse_checkout
        )
    except subprocess.CalledProcessError as e:
        print(f"[{project.name}] Clone failed:\n{e.output}", flush=True)
        raise
    print(f"[{project.name}] {output.strip() or 'Up to date.'}", flush=True)


def clone_projects(work_dir: str, config_path: str) -> None:
    projects = load_projects(config_path)
    os.makedirs(work_dir, exist_ok=True)

    with ThreadPoolExecutor(CLONE_JOBS) as executor:
        futures = [executor.submit(_clone, project, work_dir) for project in projects]
        for future in futures:
            future.result()
