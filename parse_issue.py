import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass
class ParseResult:
    pr_link: str
    check_name: str
    tidy_config: str


def parse_body(body: str) -> ParseResult:
    """
    Parses the issue body to extract PR link, check name, and tidy configuration.
    """
    body = body.strip()
    if not body:
        raise ValueError("Empty body")

    lines: list[str] = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        raise ValueError("No valid lines found")

    # Parse [PR_URL] [CHECK_NAME]
    first_line: str = lines[0]
    parts: list[str] = first_line.split()
    if len(parts) < 2:
        raise ValueError("First line must contain PR_URL and CHECK_NAME")

    pr_link: str = parts[0]
    check_name: str = parts[1]

    # Parse options -- simple key and value
    check_options: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue

        key_raw, value_raw = line.split(":", 1)
        key: str = key_raw.strip()
        value: str = value_raw.strip()

        # Handle prefixing and warn if mismatch
        if "." in key:
            prefix, actual_key = key.split(".", 1)
            if prefix != check_name:
                print(
                    f"Warning: Prefix mismatch. Expected '{check_name}', got '{prefix}'. "
                    f"Overriding to '{check_name}.{actual_key}'",
                    file=sys.stderr,
                )
            full_key = f"{check_name}.{actual_key}"
        else:
            full_key = f"{check_name}.{key}"

        check_options[full_key] = value

    # Format as clang-tidy config string
    tidy_config: str = ""
    if check_options:
        config_dict: dict[str, Any] = {"CheckOptions": check_options}
        tidy_config = json.dumps(config_dict)

    return ParseResult(pr_link=pr_link, check_name=check_name, tidy_config=tidy_config)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse issue body for PR link, check name, and tidy configuration."
    )
    parser.add_argument("output_env_file", help="Path to the output environment file.")
    args = parser.parse_args()

    try:
        body: str = sys.stdin.read()
        result = parse_body(body)

        # Write to GitHub Env file
        with open(args.output_env_file, "a") as f:
            f.write(f"PR_LINK<<EOF\n{result.pr_link}\nEOF\n")
            f.write(f"CHECK_NAME<<EOF\n{result.check_name}\nEOF\n")
            f.write(f"TIDY_CONFIG<<EOF\n{result.tidy_config}\nEOF\n")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
