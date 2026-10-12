import argparse
import json
import secrets
import shlex
import sys
from dataclasses import dataclass, field
from typing import Any

FLAGS_DIRECTIVE = "/flags"
# The run-clang-tidy flags an issue may pass with /flags. The others could load
# code (-load), change files (-fix, -export-fixes), or replace what CTIT sets
# itself (-checks, -config, -p, -j, the binaries).
ALLOWED_TIDY_FLAGS = (
    "extra-arg",
    "extra-arg-before",
    "removed-arg",
    "header-filter",
    "exclude-header-filter",
    "line-filter",
    "source-filter",
)


@dataclass
class ParseResult:
    pr_link: str
    check_name: str
    tidy_config: str
    compare_baseline: bool = False
    # Extra run-clang-tidy arguments, e.g. ["-extra-arg=-std=c++20"].
    tidy_args: list[str] = field(default_factory=list)


def parse_flags(text: str) -> list[str]:
    """Parse the arguments of a /flags line, quoted like in a shell."""
    args: list[str] = []
    try:
        tokens = shlex.split(text)
    except ValueError as e:
        raise ValueError(f"Cannot parse {FLAGS_DIRECTIVE} {text.strip()}: {e}") from e
    for token in tokens:
        name, has_value, value = token.lstrip("-").partition("=")
        if not token.startswith("-") or not has_value or name not in ALLOWED_TIDY_FLAGS:
            raise ValueError(
                f"Unsupported flag {token!r} in {FLAGS_DIRECTIVE}: expected "
                f"-NAME=VALUE with NAME one of {', '.join(ALLOWED_TIDY_FLAGS)}"
            )
        args.append(f"-{name}={value}")
    return args


def _looks_like_pr_link(token: str) -> bool:
    return "://" in token or token.startswith("github.com/")


def parse_body(body: str) -> ParseResult:
    """
    Parses the issue body to extract PR link (optional), check name, and tidy configuration.
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
    pr_link: str = ""
    if _looks_like_pr_link(parts[0]):
        pr_link = parts[0]
        parts = parts[1:]
    if not parts:
        raise ValueError("First line must contain CHECK_NAME, optionally after PR_URL")

    check_name: str = parts[0]

    # Parse options -- simple key and value
    check_options: dict[str, str] = {}
    tidy_args: list[str] = []
    for line in lines[1:]:
        directive, _, rest = line.partition(" ")
        if directive == FLAGS_DIRECTIVE:
            tidy_args += parse_flags(rest)
            continue
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

    return ParseResult(
        pr_link=pr_link,
        check_name=check_name,
        tidy_config=tidy_config,
        tidy_args=tidy_args,
        compare_baseline=bool(pr_link)
        and (
            "/baseline" in lines[1:]
            or any(
                check.startswith("clang-diagnostic-lifetime-safety")
                for check in check_name.split(",")
            )
        ),
    )


def write_env(path: str, values: dict[str, str]) -> None:
    """Append values to a GitHub environment file.

    The values come from the issue, so each one is written with a random
    delimiter, which the value cannot contain to end its entry early and set
    other variables.
    """
    delimiter = f"CTIT_{secrets.token_hex(16)}"
    with open(path, "a") as f:
        for name, value in values.items():
            if delimiter in value:
                raise ValueError(f"{name} contains the delimiter")
            f.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse issue body for PR link, check name, and tidy configuration."
    )
    parser.add_argument("output_env_file", help="Path to the output environment file.")
    args = parser.parse_args()

    try:
        body: str = sys.stdin.read()
        try:
            result = parse_body(body)
        except ValueError as e:
            # The failure comment on the issue shows this to the requester.
            write_env(args.output_env_file, {"PARSE_ERROR": str(e)})
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        write_env(
            args.output_env_file,
            {
                "PR_LINK": result.pr_link,
                "CHECK_NAME": result.check_name,
                "TIDY_CONFIG": result.tidy_config,
                "TIDY_ARGS": shlex.join(result.tidy_args),
                "COMPARE_BASELINE": str(result.compare_baseline).lower(),
            },
        )
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
