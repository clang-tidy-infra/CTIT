#!/usr/bin/env python3
"""Profile the slowest files: find top N from logs, re-run clang-tidy with check profiling."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

_TIMING_PATTERN = re.compile(r"\[\s*\d+/\d+\]\[(\d+\.?\d*)s\](.*)")


def _parse_timing_lines(log_dir: str) -> list[tuple[float, str, str, str]]:
    """Return [(seconds, file, build_dir, checks)] parsed from progress lines."""
    try:
        names = sorted(f for f in os.listdir(log_dir) if f.endswith(".log"))
    except OSError as e:
        print(f"Error reading log directory {log_dir}: {e}", file=sys.stderr)
        sys.exit(1)

    entries: list[tuple[float, str, str, str]] = []
    for name in names:
        path = os.path.join(log_dir, name)
        try:
            with open(path) as f:
                lines = f.readlines()
        except OSError as e:
            print(f"Warning: could not read {path}: {e}", file=sys.stderr)
            continue

        for line in lines:
            m = _TIMING_PATTERN.search(line)
            if not m:
                continue
            seconds = float(m.group(1))
            invocation_str = m.group(2).strip()
            try:
                tokens = shlex.split(invocation_str)
            except ValueError:
                continue
            if len(tokens) < 2:
                continue

            source_file = tokens[-1]
            build_dir = ""
            checks = ""
            for token in tokens:
                if token.startswith("-p="):
                    build_dir = token[3:]
                elif token.startswith("-checks="):
                    checks = token[len("-checks=") :]

            if source_file and build_dir:
                entries.append((seconds, source_file, build_dir, checks))

    return entries


def _run_profile(
    clang_tidy_bin: str, source_file: str, build_dir: str, checks: str
) -> dict[str, float]:
    """Run clang-tidy on one file with --store-check-profile, return {check: wall_seconds}."""
    with tempfile.TemporaryDirectory() as profile_dir:
        cmd = [
            clang_tidy_bin,
            f"-p={build_dir}",
            "--enable-check-profile",
            f"--store-check-profile={profile_dir}",
        ]
        if checks:
            cmd.append(f"-checks={checks}")
        cmd.append(source_file)

        subprocess.run(cmd, capture_output=True, check=False)

        result: dict[str, float] = {}
        for fname in os.listdir(profile_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(profile_dir, fname)) as f:
                    data = json.load(f)
                for key, val in data.get("profile", {}).items():
                    if key.startswith("time.clang-tidy.") and key.endswith(".wall"):
                        check = key[len("time.clang-tidy.") : -len(".wall")]
                        result[check] = result.get(check, 0.0) + val
            except (json.JSONDecodeError, OSError):
                continue
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log-dir", default="logs", help="Directory containing .log files"
    )
    parser.add_argument(
        "--clang-tidy-binary",
        default="llvm-project/build/bin/clang-tidy",
        help="Path to clang-tidy binary",
    )
    parser.add_argument(
        "--top", type=int, default=5, help="Number of slow files to profile"
    )
    args = parser.parse_args()

    if not os.path.isfile(args.clang_tidy_binary):
        print(f"Error: clang-tidy not found: {args.clang_tidy_binary}", file=sys.stderr)
        sys.exit(1)

    entries = _parse_timing_lines(args.log_dir)
    if not entries:
        print("No timing entries found in logs.")
        sys.exit(0)

    entries.sort(key=lambda e: -e[0])
    top = entries[: args.top]

    print(f"Top {len(top)} slowest files:\n")
    for secs, src, _, _ in top:
        print(f"  {secs:7.1f}s  {src}")
    print()

    for secs, source_file, build_dir, checks in top:
        print(f"--- {source_file} ({secs:.1f}s) ---")
        if not os.path.isfile(source_file):
            print("  (file not found, skipping)\n")
            continue

        profile = _run_profile(args.clang_tidy_binary, source_file, build_dir, checks)
        if not profile:
            print("  (no profile data)\n")
            continue

        print(f"  {'Check':<50}  Wall (s)")
        for check, wall in sorted(profile.items(), key=lambda x: -x[1])[:20]:
            print(f"  {check:<50}  {wall:.3f}")
        print()


if __name__ == "__main__":
    main()
