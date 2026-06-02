#!/usr/bin/env python3
"""Build a GitHub issue body for detected clang-tidy crashes."""

import argparse
import sys


def build_body(repo: str, run_id: str, artifact_url: str, summary_file: str) -> str:
    try:
        with open(summary_file) as f:
            summary = f.read()
    except OSError as e:
        print(f"Error reading {summary_file}: {e}", file=sys.stderr)
        sys.exit(1)

    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    return (
        f"Crashes detected in nightly all-checks run.\n\n"
        f"**Run:** {run_url}\n"
        f"**Logs:** {artifact_url}\n\n"
        f"{summary}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository (owner/name)")
    parser.add_argument("--run-id", required=True, help="GitHub Actions run ID")
    parser.add_argument("--artifact-url", required=True, help="Artifact download URL")
    parser.add_argument(
        "--summary-file", default="crash-summary.md", help="Crash summary markdown file"
    )
    args = parser.parse_args()

    print(
        build_body(args.repo, args.run_id, args.artifact_url, args.summary_file), end=""
    )


if __name__ == "__main__":
    main()
