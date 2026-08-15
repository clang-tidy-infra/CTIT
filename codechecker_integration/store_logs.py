#!/usr/bin/env python3
"""Convert nightly clang-tidy logs to plist and store them on the CodeChecker server.

One CodeChecker "run" per project: re-storing the same run name updates it and
CodeChecker computes per-report detection status (NEW / UNRESOLVED / RESOLVED /
REOPENED) against the previous store. We also pin each store with a date tag
for ad-hoc historical comparisons.

Errors are isolated per project so a single bad project (or a transient server
outage) doesn't drop the rest of the nightly history.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

from testers.config import load_projects


def _run(cmd: list[str], env: dict[str, str]) -> None:
    print(f"[store_logs] $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, env=env, check=True)


def _write_token_file(url: str, token: str) -> str:
    """Write the CodeChecker session file the client reads for auth.

    Returns the directory the file lives in so it can be passed as HOME.
    """
    home = tempfile.mkdtemp(prefix="cc-home-")
    path = os.path.join(home, ".codechecker.passwords.json")
    payload = {"client_autologin": True, "credentials": {url: token}}
    with open(path, "w") as f:
        json.dump(payload, f)
    os.chmod(path, 0o600)
    return home


def store_project(
    project_name: str,
    log_path: str,
    reports_root: str,
    url: str,
    tag: str,
    env: dict[str, str],
) -> bool:
    if not os.path.exists(log_path) or os.path.getsize(log_path) == 0:
        print(f"[store_logs] {project_name}: log missing or empty, skipping")
        return True

    plist_dir = os.path.join(reports_root, project_name)
    os.makedirs(plist_dir, exist_ok=True)

    try:
        _run(
            [
                "report-converter",
                "-t",
                "clang-tidy",
                "-o",
                plist_dir,
                log_path,
            ],
            env=env,
        )
        _run(
            [
                "CodeChecker",
                "store",
                plist_dir,
                "--name",
                project_name,
                "--tag",
                tag,
                "--url",
                url,
            ],
            env=env,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(
            f"[store_logs] {project_name}: failed ({e.returncode}); continuing",
            file=sys.stderr,
        )
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument(
        "--reports-dir",
        default="codechecker_reports",
        help="Output directory for converted plist files",
    )
    parser.add_argument(
        "--tag",
        default=datetime.datetime.now(datetime.timezone.utc).strftime(
            "nightly-%Y-%m-%d"
        ),
        help="Tag attached to each stored run",
    )
    args = parser.parse_args()

    url = os.environ.get("CC_URL")
    token = os.environ.get("CC_TOKEN")
    if not url or not token:
        print(
            "[store_logs] CC_URL and CC_TOKEN must be set; skipping store",
            file=sys.stderr,
        )
        return 0

    home = _write_token_file(url, token)
    env = {**os.environ, "HOME": home}

    failed: list[str] = []
    for project in load_projects():
        log_path = os.path.join(args.log_dir, f"{project.name}.log")
        ok = store_project(
            project.name,
            log_path,
            args.reports_dir,
            url,
            args.tag,
            env,
        )
        if not ok:
            failed.append(project.name)

    if failed:
        print(
            f"[store_logs] {len(failed)} project(s) failed to store: "
            f"{', '.join(failed)}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
