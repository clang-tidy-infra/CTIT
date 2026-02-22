#!/usr/bin/env python3
"""Clone test projects defined in projects.json into a work directory."""

import os
import subprocess

from testers.config import load_projects


def clone_project(name: str, url: str, commit: str, dest_dir: str) -> None:
    """Shallow-clone a project and checkout a specific commit."""
    if not os.path.isdir(dest_dir):
        subprocess.run(
            ["git", "clone", "--depth", "1", "--no-checkout", url, dest_dir],
            check=True,
        )

    subprocess.run(
        ["git", "-C", dest_dir, "fetch", "--depth", "1", "origin", commit],
        check=True,
    )
    subprocess.run(
        ["git", "-C", dest_dir, "checkout", commit],
        check=True,
    )


def clone_projects(work_dir: str, config_path: str) -> None:
    projects = load_projects(config_path)
    os.makedirs(work_dir, exist_ok=True)

    for project in projects:
        dest_dir = os.path.join(work_dir, project.name)
        clone_project(project.name, project.url, project.commit, dest_dir)
