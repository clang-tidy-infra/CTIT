#!/usr/bin/env python3
"""Compute per-project NEW / RESOLVED diagnostic deltas via CodeChecker.

For each project run, query the server for reports whose detection-status is
NEW or RESOLVED *since the previous store*. CodeChecker records these
automatically as part of the store operation, so we don't need to track
baseline tags ourselves.

Output is a markdown report grouped by project and by check, plus the GitHub
Actions step output `has_new=true|false`.
"""

import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass, field

from testers.config import Project, load_projects

_MAX_EXAMPLES_PER_PROJECT = 20


@dataclass
class _ProjectDelta:
    project: str
    new: list[dict] = field(default_factory=list)
    resolved: list[dict] = field(default_factory=list)


def _write_token_file(url: str, token: str) -> str:
    home = tempfile.mkdtemp(prefix="cc-home-")
    path = os.path.join(home, ".codechecker.passwords.json")
    payload = {"client_autologin": True, "credentials": {url: token}}
    with open(path, "w") as f:
        json.dump(payload, f)
    os.chmod(path, 0o600)
    return home


def _query_results(
    run_name: str, detection_status: str, url: str, env: dict[str, str]
) -> list[dict]:
    cmd = [
        "CodeChecker",
        "cmd",
        "results",
        run_name,
        "--detection-status",
        detection_status,
        "--url",
        url,
        "-o",
        "json",
    ]
    print(f"[diff_runs] $ {' '.join(cmd)}", flush=True)
    try:
        out = subprocess.check_output(cmd, env=env, text=True)
    except subprocess.CalledProcessError as e:
        print(
            f"[diff_runs] {run_name} ({detection_status}): query failed "
            f"({e.returncode}); treating as empty",
            file=sys.stderr,
        )
        return []
    try:
        return json.loads(out) or []
    except json.JSONDecodeError:
        print(
            f"[diff_runs] {run_name} ({detection_status}): non-JSON output; "
            "treating as empty",
            file=sys.stderr,
        )
        return []


def _ui_link(base_url: str, project: str) -> str:
    """Best-effort UI link for a project's reports filtered to NEW."""
    product = base_url.rstrip("/").split("/")[-1] or "Default"
    server_root = "/".join(base_url.rstrip("/").split("/")[:-1])
    query = urllib.parse.urlencode(
        {"run": project, "detection-status": "New"}, doseq=True
    )
    return f"{server_root}/{product}/reports?{query}"


def _by_check(reports: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = collections.Counter()
    for r in reports:
        counts[r.get("checkerId") or r.get("checker_name") or "(unknown)"] += 1
    return dict(counts)


def _format_example(report: dict) -> str:
    path = report.get("checkedFile") or report.get("file") or "?"
    line = report.get("line") or report.get("lastBugPosition", {}).get("startLine") or 0
    msg = report.get("checkerMsg") or report.get("message") or ""
    check = report.get("checkerId") or report.get("checker_name") or "?"
    return f"- `{path}:{line}` — [{check}] {msg}"


def render_report(
    deltas: list[_ProjectDelta], base_url: str, output_path: str
) -> tuple[int, int]:
    total_new = sum(len(d.new) for d in deltas)
    total_resolved = sum(len(d.resolved) for d in deltas)

    lines: list[str] = ["# Nightly diagnostic delta\n\n"]
    lines.append(f"**Total:** {total_new} new, {total_resolved} resolved\n\n")

    lines.append("| Project | New | Resolved | UI |\n")
    lines.append("|---------|----:|---------:|----|\n")
    for d in deltas:
        lines.append(
            f"| `{d.project}` | {len(d.new)} | {len(d.resolved)} | "
            f"[browse]({_ui_link(base_url, d.project)}) |\n"
        )
    lines.append("\n")

    for d in deltas:
        if not d.new and not d.resolved:
            continue
        lines.append(f"## `{d.project}`\n\n")

        if d.new:
            lines.append(f"### New ({len(d.new)})\n\n")
            for check, count in sorted(_by_check(d.new).items(), key=lambda x: -x[1]):
                lines.append(f"- `{check}`: {count}\n")
            lines.append("\n<details>\n<summary>Examples</summary>\n\n")
            for report in d.new[:_MAX_EXAMPLES_PER_PROJECT]:
                lines.append(_format_example(report) + "\n")
            if len(d.new) > _MAX_EXAMPLES_PER_PROJECT:
                lines.append(
                    f"\n*… {len(d.new) - _MAX_EXAMPLES_PER_PROJECT} more in UI*\n"
                )
            lines.append("\n</details>\n\n")

        if d.resolved:
            lines.append(f"### Resolved ({len(d.resolved)})\n\n")
            for check, count in sorted(
                _by_check(d.resolved).items(), key=lambda x: -x[1]
            ):
                lines.append(f"- `{check}`: {count}\n")
            lines.append("\n")

    with open(output_path, "w") as f:
        f.writelines(lines)

    return total_new, total_resolved


def _set_github_output(key: str, value: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{key}={value}\n")


def collect_deltas(
    projects: list[Project], url: str, env: dict[str, str]
) -> list[_ProjectDelta]:
    deltas: list[_ProjectDelta] = []
    for project in projects:
        deltas.append(
            _ProjectDelta(
                project=project.name,
                new=_query_results(project.name, "new", url, env),
                resolved=_query_results(project.name, "resolved", url, env),
            )
        )
    return deltas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="delta-report.md")
    args = parser.parse_args()

    url = os.environ.get("CC_URL")
    token = os.environ.get("CC_TOKEN")
    if not url or not token:
        print(
            "[diff_runs] CC_URL and CC_TOKEN must be set; skipping delta",
            file=sys.stderr,
        )
        _set_github_output("has_new", "false")
        return 0

    home = _write_token_file(url, token)
    env = {**os.environ, "HOME": home}

    deltas = collect_deltas(load_projects(), url, env)
    total_new, total_resolved = render_report(deltas, url, args.output)

    print(
        f"[diff_runs] total: {total_new} new, {total_resolved} resolved "
        f"across {len(deltas)} project(s)"
    )
    _set_github_output("has_new", "true" if total_new > 0 else "false")
    _set_github_output("new_count", str(total_new))
    _set_github_output("projects_with_new", str(sum(1 for d in deltas if d.new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
