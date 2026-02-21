#!/usr/bin/env python3
"""Clone test projects defined in projects.json into a work directory."""

import argparse
import os
import subprocess

from testers.config import CONFIG_FILE, PROJECTS_DIR, load_projects


def clone_project(name: str, url: str, commit: str, dest_dir: str) -> None:
    """Clone a project and checkout a specific commit."""
    if not os.path.isdir(dest_dir):
        subprocess.run(
            ["git", "clone", url, dest_dir],
            check=True,
        )

    subprocess.run(
        ["git", "-C", dest_dir, "checkout", commit],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone test projects from config.")
    parser.add_argument(
        "--work-dir",
        default=PROJECTS_DIR,
        help=f"Directory to clone projects into (default: {PROJECTS_DIR})",
    )
    parser.add_argument(
        "--config",
        default=CONFIG_FILE,
        help=f"Path to config file (default: {CONFIG_FILE})",
    )
    args = parser.parse_args()

    projects = load_projects(args.config)
    os.makedirs(args.work_dir, exist_ok=True)

    for project in projects:
        dest_dir = os.path.join(args.work_dir, project.name)
        clone_project(project.name, project.url, project.commit, dest_dir)


if __name__ == "__main__":
    main()
