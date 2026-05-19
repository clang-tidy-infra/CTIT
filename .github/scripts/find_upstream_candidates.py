#!/usr/bin/env python3
"""Run upstream PR detection, capture TSV, and write a count to GITHUB_OUTPUT."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    output_file = Path(sys.argv[1] if len(sys.argv) > 1 else "candidates.tsv")

    with output_file.open("w") as f:
        subprocess.run(
            [sys.executable, "poll_upstream.py"],
            stdout=f,
            check=True,
        )

    content = output_file.read_text()
    count = sum(1 for line in content.splitlines() if line.strip())

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"count={count}\n")

    print(f"Found {count} candidate PR(s):")
    print(content, end="")


if __name__ == "__main__":
    main()
