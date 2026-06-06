#!/usr/bin/env python3
"""Build a GitHub issue body for detected clang-tidy crashes."""

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


def _trim_profile_to_top_n(profile: str, n: int = 15) -> str:
    """Keep only the top N checks by wall time from a profile markdown."""
    lines = profile.split("\n")
    header_lines = []
    data_lines = []
    footer_lines = []
    in_data = False

    for line in lines:
        if "|" in line and "Check" in line:
            header_lines.append(line)
            in_data = True
        elif in_data and "|" in line and "---" in line:
            header_lines.append(line)
        elif in_data and "|" in line and len(line.strip()) > 0:
            data_lines.append(line)
        elif in_data and ("|" not in line or len(line.strip()) == 0):
            in_data = False
            footer_lines.append(line)
        else:
            if not in_data:
                if len(header_lines) == 0:
                    header_lines.append(line)
                else:
                    footer_lines.append(line)

    result = "\n".join(header_lines) + "\n"
    result += "\n".join(data_lines[:n]) + "\n"
    if len(data_lines) > n:
        result += f"\n*... ({len(data_lines) - n} more checks in detailed logs)*\n"
    result += "\n".join(footer_lines)

    return result.strip() + "\n"


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

    parts.append(summary)

    if profile_file:
        profile = _read_file(profile_file)
        profile = _trim_profile_to_top_n(profile, n=15)
        parts.append("\n")
        parts.append(profile)

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
    parser.add_argument(
        "--output-file",
        default="logs/issue.md",
        help="Optional file to save the issue body to disk",
    )
    args = parser.parse_args()

    body = build_body(
        args.repo,
        args.run_id,
        args.artifact_url,
        args.summary_file,
        args.profile_file,
    )

    # Save to disk if output file is specified
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
