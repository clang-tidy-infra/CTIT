"""Run clang-tidy checks over LLVM's own clang test inputs."""

from __future__ import annotations

import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TextIO

DEFAULT_LLVM_DIR = "llvm-project"
DEFAULT_CLANG_TEST_LOG_DIR = "logs/clang-tests"
DEFAULT_CLANG_TEST_OUTPUT = "clang-tests.md"
DEFAULT_TEST_TIMEOUT = 30

PASS = "PASS"
ERROR = "ERROR"
CRASH = "CRASH"

TEST_GLOBS = (
    "clang/test/**/*.c",
    "clang/test/**/*.cc",
    "clang/test/**/*.cpp",
    "clang/test/**/*.cxx",
    "clang/test/**/*.cppm",
    "clang-tools-extra/test/clang-tidy/**/*.c",
    "clang-tools-extra/test/clang-tidy/**/*.cc",
    "clang-tools-extra/test/clang-tidy/**/*.cpp",
    "clang-tools-extra/test/clang-tidy/**/*.cxx",
    "clang-tools-extra/test/clang-tidy/**/*.cppm",
)

CRASH_MARKERS = (
    "PLEASE submit a bug report",
    "Stack dump:",
    "Assertion failed:",
    "assertion failed",
    "LLVM ERROR:",
    "Segmentation fault",
    "Abort trap",
    "AddressSanitizer:",
    "UndefinedBehaviorSanitizer:",
)


@dataclass(frozen=True)
class ClangTestResult:
    """Result of running clang-tidy over one LLVM test input."""

    file_path: str
    status: str
    returncode: int | None
    reason: str
    log_file: str


def discover_test_files(llvm_dir: str) -> list[str]:
    """Find LLVM clang test files covered by the smoke run."""
    files: set[str] = set()
    for pattern in TEST_GLOBS:
        full_pattern = os.path.join(llvm_dir, pattern)
        files.update(glob.glob(full_pattern, recursive=True))
    return sorted(os.path.normpath(path) for path in files if os.path.isfile(path))


def compile_args_for_file(file_path: str, llvm_dir: str) -> list[str]:
    """Return simple compile arguments for one test file."""
    ext = os.path.splitext(file_path)[1]
    if ext == ".c":
        language_args = ["-x", "c", "-std=c17"]
    else:
        language_args = ["-x", "c++", "-std=c++20"]

    include_dirs = [
        os.path.join(llvm_dir, "clang", "test"),
        os.path.join(llvm_dir, "clang", "test", "Inputs"),
        os.path.join(llvm_dir, "clang-tools-extra", "test", "clang-tidy"),
        os.path.join(llvm_dir, "clang-tools-extra", "test", "clang-tidy", "Inputs"),
    ]

    args = language_args + ["-fsyntax-only", "-fno-color-diagnostics"]
    for include_dir in include_dirs:
        args.extend(["-I", include_dir])
    return args


def build_clang_tidy_command(
    clang_tidy_bin: str,
    file_path: str,
    check_name: str,
    tidy_config: str | None,
    llvm_dir: str,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build the clang-tidy command for one test file."""
    cmd = [
        clang_tidy_bin,
        file_path,
        f"-checks=-*,{check_name}",
        "-quiet",
    ]
    if tidy_config:
        cmd.append(f"-config={tidy_config}")

    compile_args = compile_args_for_file(file_path, llvm_dir)
    if extra_args:
        compile_args.extend(extra_args)

    return cmd + ["--"] + compile_args


def log_file_for_test(file_path: str, llvm_dir: str, log_dir: str) -> str:
    """Return a stable log file path for one test file."""
    rel_path = os.path.relpath(file_path, llvm_dir)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "__", rel_path)
    return os.path.join(log_dir, f"{safe_name}.log")


def classify_result(returncode: int, output: str) -> tuple[str, str]:
    """Classify clang-tidy output into PASS, ERROR, or CRASH."""
    for marker in CRASH_MARKERS:
        if marker in output:
            return CRASH, marker

    if returncode < 0:
        return CRASH, f"terminated by signal {-returncode}"

    if returncode != 0:
        return ERROR, f"clang-tidy exited with status {returncode}"

    return PASS, "completed"


def _write_log(log_file: str, cmd: list[str], output: str) -> None:
    with open(log_file, "w", errors="replace") as f:
        f.write("$ ")
        f.write(" ".join(shlex.quote(arg) for arg in cmd))
        f.write("\n\n")
        f.write(output)


def run_clang_test_file(
    file_path: str,
    check_name: str,
    clang_tidy_bin: str,
    llvm_dir: str,
    log_dir: str,
    tidy_config: str | None = None,
    timeout: int = DEFAULT_TEST_TIMEOUT,
    extra_args: list[str] | None = None,
) -> ClangTestResult:
    """Run clang-tidy over a single LLVM test input."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = log_file_for_test(file_path, llvm_dir, log_dir)
    rel_path = os.path.relpath(file_path, llvm_dir)
    cmd = build_clang_tidy_command(
        clang_tidy_bin,
        file_path,
        check_name,
        tidy_config,
        llvm_dir,
        extra_args,
    )

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        output = proc.stdout or ""
        _write_log(log_file, cmd, output)
        status, reason = classify_result(proc.returncode, output)
        return ClangTestResult(rel_path, status, proc.returncode, reason, log_file)
    except subprocess.TimeoutExpired as exc:
        raw_output = exc.stdout or ""
        if isinstance(raw_output, bytes):
            output = raw_output.decode(errors="replace")
        else:
            output = raw_output
        output += f"\nTimed out after {timeout} seconds.\n"
        _write_log(log_file, cmd, output)
        return ClangTestResult(rel_path, CRASH, None, "timeout", log_file)


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _write_result_rows(f: TextIO, results: list[ClangTestResult]) -> None:
    f.write("| File | Return Code |\n")
    f.write("| :--- | :--- |\n")
    for result in results:
        returncode = "-" if result.returncode is None else result.returncode
        f.write(
            f"| `{_markdown_cell(result.file_path)}` "
            f"| {_markdown_cell(returncode)} |\n"
        )


def write_markdown_report(results: list[ClangTestResult], output_path: str) -> None:
    """Write a markdown report containing crash results only."""
    crashes = [result for result in results if result.status == CRASH]

    with open(output_path, "w") as f:
        f.write("### Clang Test Crashes\n\n")
        f.write(
            f"**Summary**: {len(crashes)} CRASH out of {len(results)} total files.\n"
        )

        if not crashes:
            f.write("\n_No crashes detected._\n")
            return

        f.write("\n")
        _write_result_rows(f, crashes)


def _run_files(
    files: list[str],
    check_name: str,
    clang_tidy_bin: str,
    llvm_dir: str,
    log_dir: str,
    tidy_config: str | None,
    timeout: int,
    jobs: int,
    extra_args: list[str] | None,
) -> list[ClangTestResult]:
    if jobs <= 1:
        return [
            run_clang_test_file(
                file_path,
                check_name,
                clang_tidy_bin,
                llvm_dir,
                log_dir,
                tidy_config,
                timeout,
                extra_args,
            )
            for file_path in files
        ]

    results: list[ClangTestResult] = []
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = [
            executor.submit(
                run_clang_test_file,
                file_path,
                check_name,
                clang_tidy_bin,
                llvm_dir,
                log_dir,
                tidy_config,
                timeout,
                extra_args,
            )
            for file_path in files
        ]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda result: result.file_path)


def run_clang_tests(
    check_name: str,
    clang_tidy_bin: str,
    llvm_dir: str = DEFAULT_LLVM_DIR,
    tidy_config: str | None = None,
    log_dir: str = DEFAULT_CLANG_TEST_LOG_DIR,
    output: str = DEFAULT_CLANG_TEST_OUTPUT,
    timeout: int = DEFAULT_TEST_TIMEOUT,
    jobs: int = 1,
    extra_args: list[str] | None = None,
) -> None:
    """Run clang-tidy over LLVM clang tests and write a grouped report."""
    if not shutil.which(clang_tidy_bin) and not os.path.isfile(clang_tidy_bin):
        print(f"Error: clang-tidy binary not found: {clang_tidy_bin}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(llvm_dir):
        print(f"Error: LLVM directory not found: {llvm_dir}", file=sys.stderr)
        sys.exit(1)

    files = discover_test_files(llvm_dir)
    if not files:
        print(f"No clang test files found under '{llvm_dir}'.", file=sys.stderr)

    os.makedirs(log_dir, exist_ok=True)
    results = _run_files(
        files,
        check_name,
        clang_tidy_bin,
        llvm_dir,
        log_dir,
        tidy_config,
        timeout,
        jobs,
        extra_args,
    )
    write_markdown_report(results, output)
    print(f"Clang test report generated: {output}")
