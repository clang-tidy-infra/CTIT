#!/usr/bin/env python3
"""Trims issue.md to fit GitHub's PR comment limit.

Algorithm:
  1. Content fits within limit -> return as-is.
  2. If too long -> strip AI analysis.
  3. If still too long -> strip per-project findings too.
"""

import argparse
import sys

GITHUB_COMMENT_LIMIT = 65536
_AI_MARKER = "AI False-Positive Analysis"


def _find_details_blocks(text: str) -> list[tuple[int, int]]:
    """Return (start, end) index pairs for every top-level <details> block."""
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        start = text.find("<details>", pos)
        if start == -1:
            break
        end = text.find("</details>", start)
        if end == -1:
            break
        end += len("</details>")
        spans.append((start, end))
        pos = end
    return spans


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Return *text* with the given (start, end) ranges removed."""
    if not spans:
        return text
    parts: list[str] = []
    prev = 0
    for start, end in spans:
        parts.append(text[prev:start])
        prev = end
    parts.append(text[prev:])
    return "".join(parts)


def slim_comment(content: str, artifact_url: str) -> str:
    """Return content slimmed to fit within GITHUB_COMMENT_LIMIT."""
    if len(content) <= GITHUB_COMMENT_LIMIT:
        return content

    artifact_link = (
        f"\n\n[Full per-project details in workflow artifacts]({artifact_url})\n"
    )

    spans = _find_details_blocks(content)
    ai_spans = [(s, e) for s, e in spans if _AI_MARKER in content[s:e]]

    # Step 2: drop AI analysis, keep per-project findings.
    if ai_spans:
        candidate = _remove_spans(content, ai_spans).rstrip() + artifact_link
        if len(candidate) <= GITHUB_COMMENT_LIMIT:
            return candidate

    # Step 3: drop everything — keep summary table only.
    first_details = content.find("<details>")
    summary = (
        content[:first_details].rstrip() if first_details != -1 else content.rstrip()
    )
    return summary + artifact_link


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="Path to issue.md (edited in place)")
    parser.add_argument("artifact_url", help="Workflow artifact URL to link to")
    args = parser.parse_args()

    try:
        content = open(args.file).read()
    except OSError as e:
        print(f"Error reading {args.file}: {e}", file=sys.stderr)
        sys.exit(1)

    slimmed = slim_comment(content, args.artifact_url)

    if len(slimmed) > GITHUB_COMMENT_LIMIT:
        print(
            f"Warning: slimmed comment is {len(slimmed)} chars "
            f"(limit is {GITHUB_COMMENT_LIMIT})",
            file=sys.stderr,
        )

    try:
        with open(args.file, "w") as f:
            f.write(slimmed)
    except OSError as e:
        print(f"Error writing {args.file}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
