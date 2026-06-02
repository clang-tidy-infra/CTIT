#!/usr/bin/env python3
"""Find the top N longest clang-tidy runs across log files."""

import argparse
import os
import re
import sys
from dataclasses import dataclass

_TIMING_PATTERN = re.compile(r"\[\s*\d+/\d+\]\[(\d+\.?\d*)s\](.*)")


@dataclass
class _RunEntry:
    seconds: float
    project: str
    detail: str


def parse_timings(log_dir: str) -> list[_RunEntry]:
    try:
        names = sorted(f for f in os.listdir(log_dir) if f.endswith(".log"))
    except OSError as e:
        print(f"Error reading log directory {log_dir}: {e}", file=sys.stderr)
        sys.exit(1)

    entries: list[_RunEntry] = []
    for name in names:
        project = name[:-4]
        path = os.path.join(log_dir, name)
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError as e:
            print(f"Warning: could not read {path}: {e}", file=sys.stderr)
            continue

        for line in lines:
            m = _TIMING_PATTERN.search(line)
            if m:
                entries.append(
                    _RunEntry(
                        seconds=float(m.group(1)),
                        project=project,
                        detail=m.group(2).strip(),
                    )
                )

    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", default="logs", help="Directory containing .log files")
    parser.add_argument("--top", type=int, default=10, help="Number of results to show")
    args = parser.parse_args()

    entries = parse_timings(args.log_dir)
    if not entries:
        print("No timing entries found.")
        sys.exit(0)

    entries.sort(key=lambda e: -e.seconds)
    print(f"{'Time':>10}  {'Project':<20}  Detail")
    print("-" * 80)
    for entry in entries[: args.top]:
        print(f"{entry.seconds:>9.1f}s  {entry.project:<20}  {entry.detail}")


if __name__ == "__main__":
    main()
