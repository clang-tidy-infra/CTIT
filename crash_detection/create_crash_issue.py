#!/usr/bin/env python3
"""Build a GitHub issue body for detected clang-tidy crashes."""

import argparse
import sys


def _read_file(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        sys.exit(1)


def build_body(
    repo: str,
    run_id: str,
    artifact_url: str,
    summary_file: str,
    profile_file: str | None = None,
) -> str:
    summary = _read_file(summary_file)
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    parts = [
        f"Crashes detected in nightly all-checks run.\n\n"
        f"**Run:** {run_url}\n"
        f"**Logs:** {artifact_url}\n\n",
    ]

    if profile_file:
        profile = _read_file(profile_file)
        parts.append(profile)
        parts.append("\n")

    parts.append(summary)

    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository (owner/name)")
    parser.add_argument("--run-id", required=True, help="GitHub Actions run ID")
    parser.add_argument("--artifact-url", required=True, help="Artifact download URL")
    parser.add_argument(
        "--summary-file", default="crash-summary.md", help="Crash summary markdown file"
    )
    parser.add_argument(
        "--profile-file",
        default=None,
        help="Optional check timings profile markdown file",
    )
    args = parser.parse_args()

    print(
        build_body(
            args.repo,
            args.run_id,
            args.artifact_url,
            args.summary_file,
            args.profile_file,
        ),
        end="",
    )


if __name__ == "__main__":
    main()
