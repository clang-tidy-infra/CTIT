#!/usr/bin/env python3
"""Parse clang-tidy check profiling tables from log files and format as markdown."""

import argparse
import os
import re
import sys

_PROFILE_HEADER = re.compile(r"clang-tidy checks profiling")
_TOTAL_TIME = re.compile(
    r"Total Execution Time: ([\d.]+) seconds \(([\d.]+) wall clock\)"
)
_DATA_ROW = re.compile(
    r"\s+[\d.]+\s+\(\s*[\d.]+%\)"  # user
    r"\s+[\d.]+\s+\(\s*[\d.]+%\)"  # sys
    r"\s+[\d.]+\s+\(\s*[\d.]+%\)"  # user+sys
    r"\s+([\d.]+)\s+\(\s*[\d.]+%\)"  # wall (captured)
    r"\s+(\S+)$"  # name (captured)
)


def parse_profile(lines: list[str]) -> tuple[float, dict[str, float]]:
    """Return (total_wall, {check: wall_seconds}) from a log's profile section."""
    in_profile = False
    total_wall = 0.0
    checks: dict[str, float] = {}

    for line in lines:
        if _PROFILE_HEADER.search(line):
            in_profile = True
            continue
        if not in_profile:
            continue

        m = _TOTAL_TIME.search(line)
        if m:
            total_wall = float(m.group(2))
            continue

        m = _DATA_ROW.search(line)
        if m:
            name = m.group(2)
            if name != "Total":
                checks[name] = float(m.group(1))

    return total_wall, checks


def load_profiles(log_dir: str) -> dict[str, tuple[float, dict[str, float]]]:
    """Return {project: (total_wall, {check: wall})} for each log with a profile."""
    try:
        names = sorted(f for f in os.listdir(log_dir) if f.endswith(".log"))
    except OSError as e:
        print(f"Error reading log directory {log_dir}: {e}", file=sys.stderr)
        sys.exit(1)

    results: dict[str, tuple[float, dict[str, float]]] = {}
    for name in names:
        project = name[:-4]
        path = os.path.join(log_dir, name)
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError as e:
            print(f"Warning: could not read {path}: {e}", file=sys.stderr)
            continue

        total_wall, checks = parse_profile(lines)
        if checks:
            results[project] = (total_wall, checks)

    return results


def write_markdown(
    profiles: dict[str, tuple[float, dict[str, float]]],
    output: str,
    output_detailed: str | None = None,
) -> None:
    combined: dict[str, float] = {}
    for _, checks in profiles.values():
        for check, wall in checks.items():
            combined[check] = combined.get(check, 0.0) + wall

    total = sum(combined.values())

    lines: list[str] = ["## Check Timings Profile\n\n"]

    lines.append("| Check | Wall Time (s) | % of Total |\n")
    lines.append("|-------|--------------|------------|\n")
    for check, wall in sorted(combined.items(), key=lambda x: -x[1]):
        pct = wall / total * 100 if total > 0 else 0.0
        lines.append(f"| `{check}` | {wall:.2f} | {pct:.1f}% |\n")
    lines.append("\n")

    with open(output, "w") as f:
        f.writelines(lines)

    if output_detailed:
        detailed_lines = lines.copy()
        if len(profiles) > 1:
            detailed_lines.append(
                "<details>\n<summary>Per-project breakdown (click to expand)</summary>\n\n"
            )
            for project, (total_wall, checks) in sorted(profiles.items()):
                detailed_lines.append(
                    f"### {project} (total wall: {total_wall:.1f}s)\n\n"
                )
                detailed_lines.append("| Check | Wall Time (s) |\n")
                detailed_lines.append("|-------|---------------|\n")
                for check, wall in sorted(checks.items(), key=lambda x: -x[1]):
                    detailed_lines.append(f"| `{check}` | {wall:.2f} |\n")
                detailed_lines.append("\n")
            detailed_lines.append("</details>\n")

        with open(output_detailed, "w") as f:
            f.writelines(detailed_lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-dir", default="logs", help="Directory containing .log files"
    )
    parser.add_argument(
        "--output",
        default="profile-report.md",
        help="Output markdown file (summary only)",
    )
    parser.add_argument(
        "--output-detailed",
        default="profile-report-detailed.md",
        help="Output markdown file with per-project breakdown",
    )
    args = parser.parse_args()

    profiles = load_profiles(args.log_dir)
    if not profiles:
        print("No profiling data found in logs.", file=sys.stderr)
        sys.exit(0)

    write_markdown(profiles, args.output, args.output_detailed)
    print(
        f"Profile reports written: {args.output} (summary), "
        f"{args.output_detailed} (detailed) ({len(profiles)} project(s))"
    )


if __name__ == "__main__":
    main()
