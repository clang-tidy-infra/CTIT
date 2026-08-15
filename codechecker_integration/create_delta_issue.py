#!/usr/bin/env python3
"""Build a GitHub issue body for the nightly diagnostic delta."""

import argparse
import os
import sys


def _read_file(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except OSError as e:
        print(f"Error reading {path}: {e}", file=sys.stderr)
        sys.exit(1)


def build_body(repo: str, run_id: str, delta_file: str) -> str:
    delta = _read_file(delta_file)
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    return (
        "New clang-tidy diagnostics detected since the previous nightly run.\n\n"
        f"**Run:** {run_url}\n\n"
        f"{delta}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository (owner/name)")
    parser.add_argument("--run-id", required=True, help="GitHub Actions run ID")
    parser.add_argument(
        "--delta-file", default="delta-report.md", help="Delta markdown file"
    )
    parser.add_argument(
        "--output-file",
        default="logs/delta-issue.md",
        help="File to write the issue body to",
    )
    args = parser.parse_args()

    body = build_body(args.repo, args.run_id, args.delta_file)

    if args.output_file:
        try:
            os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
            with open(args.output_file, "w") as f:
                f.write(body)
        except OSError as e:
            print(f"Error: could not write to {args.output_file}: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
