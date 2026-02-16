import sys
import json
from typing import Dict, Union, List, Any, Tuple, Optional


def parse_body(body: str) -> Tuple[str, str, str]:
    """
    Parses the issue body to extract PR link, check name, and tidy configuration.
    """
    body = body.strip()
    if not body:
        raise ValueError("Empty body")

    lines: List[str] = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        raise ValueError("No valid lines found")

    # Parse [PR_URL] [CHECK_NAME]
    first_line: str = lines[0]
    parts: List[str] = first_line.split()
    if len(parts) < 2:
        raise ValueError("First line must contain PR_URL and CHECK_NAME")

    pr_link: str = parts[0]
    check_name: str = parts[1]

    # Parse options -- simple key and value
    check_options: Dict[str, Union[str, int, float, bool]] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue

        key_raw, value_raw = line.split(":", 1)
        key: str = key_raw.strip()
        value: str = value_raw.strip()

        # Auto-prefix if not already present
        full_key: str = (
            f"{check_name}.{key}" if not key.startswith(check_name + ".") else key
        )

        # Parse values
        parsed_value: Union[str, int, float, bool]
        if value.lower() == "true":
            parsed_value = True
        elif value.lower() == "false":
            parsed_value = False
        else:
            try:
                if "." in value:
                    parsed_value = float(value)
                else:
                    parsed_value = int(value)
            except ValueError:
                parsed_value = value

        check_options[full_key] = parsed_value

    # Format as clang-tidy config string
    tidy_config: str = ""
    if check_options:
        config_dict: Dict[str, Any] = {"CheckOptions": check_options}
        tidy_config = json.dumps(config_dict)

    return pr_link, check_name, tidy_config


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 parse_issue.py <output_env_file>")
        sys.exit(1)

    try:
        body: str = sys.stdin.read()
        pr_link, check_name, tidy_config = parse_body(body)

        # Write to GitHub Env file
        with open(sys.argv[1], "a") as f:
            f.write(f"PR_LINK<<EOF\n{pr_link}\nEOF\n")
            f.write(f"CHECK_NAME<<EOF\n{check_name}\nEOF\n")
            f.write(f"TIDY_CONFIG<<EOF\n{tidy_config}\nEOF\n")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
