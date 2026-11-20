"""Run clang-tidy analysis on test projects."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import IO

from testers.config import CONFIG_FILE, PROJECTS_DIR, Project, load_projects

DEFAULT_CLANG_TIDY_BIN = "clang-tidy"
DEFAULT_LOG_DIR = "logs"

# run-clang-tidy progress lines, e.g. "[  1/165]"; they go to progress.log.
_PROGRESS_RE = re.compile(r"^\[\s*\d+/\d+\]|^Running clang-tidy in ")
# run-clang-tidy prints this and exits before analyzing any file when clang-tidy
# cannot start, e.g. when no check matches -checks or the config is invalid.
STARTUP_FAILURE = "Unable to run clang-tidy."

ANALYSIS_CONFIG_FIELDS = {
    "cmake_source_subdir",
    "cmake_flags",
    "build_targets",
    "file_regex",
    "static_analyzer",
}

ANALYZER_PREFIX = "clang-analyzer-"
DIAGNOSTIC_PREFIX = "clang-diagnostic-"
_LEVEL_DIAGNOSTICS = {"error", "warning", "remark", "unknown"}

# Number of `ninja -t query` targets per call, to keep command lines short.
NINJA_QUERY_CHUNK = 500

_print_lock = threading.Lock()
# CMake configures projects in parallel, but each ninja build already uses
# every core, so builds run one at a time.
_build_lock = threading.Lock()


@dataclass
class AnalysisConfig:
    """Analysis settings for a single project."""

    name: str
    cmake_source_subdir: str | None = None
    cmake_flags: list[str] = field(default_factory=list)
    build_targets: list[str] = field(default_factory=list)
    file_regex: str | None = None
    static_analyzer: bool = True


def get_analysis_configs(
    config_path: str = CONFIG_FILE,
) -> dict[str, AnalysisConfig]:
    """Load analysis configs from projects.json."""
    with open(config_path) as f:
        data = json.load(f)

    configs: dict[str, AnalysisConfig] = {}
    for name, proj in data["projects"].items():
        fields = {k: v for k, v in proj.items() if k in ANALYSIS_CONFIG_FIELDS}
        configs[name] = AnalysisConfig(name=name, **fields)
    return configs


def needs_static_analyzer(check_name: str) -> bool:
    """Whether the -checks glob enables any clang-analyzer-* check.

    As in clang-tidy, a later pattern overrides an earlier one, so
    ``*,-clang-analyzer-*`` enables none. A positive pattern counts if it can
    match an analyzer check, a negative one only if it matches all of them.
    """
    enabled = False
    for pattern in check_name.split(","):
        pattern = pattern.strip()
        negative = pattern.startswith("-")
        pattern = pattern.removeprefix("-").strip()
        if not pattern:
            continue
        literal = pattern.split("*", 1)[0]
        if negative:
            if pattern == f"{literal}*" and ANALYZER_PREFIX.startswith(literal):
                enabled = False
        elif ANALYZER_PREFIX.startswith(literal) or literal.startswith(ANALYZER_PREFIX):
            enabled = True
    return enabled


def names_compiler_warnings(check_name: str) -> bool:
    """Whether the -checks glob names a Clang warning, e.g. clang-diagnostic-shadow."""
    return any(
        check.startswith(DIAGNOSTIC_PREFIX) and check != f"{DIAGNOSTIC_PREFIX}error"
        for check in map(str.strip, check_name.split(","))
    )


def find_run_tidy_script() -> str | None:
    """Try to find run-clang-tidy script in PATH."""
    for name in ("run-clang-tidy", "run-clang-tidy.py"):
        path = shutil.which(name)
        if path:
            return path
    return None


def remove_clang_tidy_configs(source_dir: str) -> None:
    """Remove .clang-tidy files to prevent them from overriding check settings."""
    for root, _dirs, files in os.walk(source_dir):
        for name in files:
            if name == ".clang-tidy":
                os.remove(os.path.join(root, name))


def _resolve_compiler(env_var: str, fallback: str) -> str:
    """Resolve which compiler CMake would use: env var, then PATH lookup."""
    return os.environ.get(env_var) or shutil.which(fallback) or fallback


def _is_clang(compiler: str) -> bool:
    """Check if a compiler path/name is clang-based."""
    return "clang" in os.path.basename(compiler)


def check_clang_compiler() -> None:
    """Verify that the C/C++ compiler is clang-based."""
    cc = _resolve_compiler("CC", "cc")
    cxx = _resolve_compiler("CXX", "c++")

    if not _is_clang(cc) or not _is_clang(cxx):
        print(
            f"Error: clang compiler required for clang-tidy analysis, current compiler:\n"
            f"  CC={cc}\n"
            f"  CXX={cxx}\n"
            f"Set CC and CXX environment variables to a clang compiler, e.g.:\n"
            f"  export CC=clang CXX=clang++",
            file=sys.stderr,
        )
        sys.exit(1)


def configure_cmake(
    source_dir: str,
    build_dir: str,
    extra_flags: list[str],
    output: IO[str] | None = None,
) -> None:
    """Run cmake configure with Ninja generator."""
    os.makedirs(build_dir, exist_ok=True)

    cmd = [
        "cmake",
        "-G",
        "Ninja",
        "-S",
        source_dir,
        "-B",
        build_dir,
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        "-DCMAKE_BUILD_TYPE=Release",
    ]

    if shutil.which("sccache"):
        cmd += [
            "-DCMAKE_C_COMPILER_LAUNCHER=sccache",
            "-DCMAKE_CXX_COMPILER_LAUNCHER=sccache",
        ]

    cmd += extra_flags
    subprocess.run(cmd, check=True, stdout=output, stderr=output)


def build_project(
    build_dir: str, targets: list[str], output: IO[str] | None = None
) -> None:
    """Build specific project targets. Does nothing if targets is empty."""
    if not targets:
        return
    subprocess.run(
        ["ninja", "-C", build_dir] + targets, check=True, stdout=output, stderr=output
    )


def analyzed_files_regex(source_dir: str, file_regex: str | None) -> str | None:
    """Return the regex run-clang-tidy matches against absolute file paths."""
    if not file_regex:
        return None
    return f"^{re.escape(source_dir)}/{file_regex}"


def analyzed_objects(
    build_dir: str, source_dir: str, file_regex: str | None
) -> list[str]:
    """Return the ninja outputs compiled from the files run-clang-tidy analyzes."""
    with open(os.path.join(build_dir, "compile_commands.json")) as f:
        database = json.load(f)

    regex = analyzed_files_regex(source_dir, file_regex)
    file_re = re.compile(regex) if regex else None
    objects = set()
    for entry in database:
        # Select files the way run-clang-tidy does.
        path = os.path.abspath(os.path.join(entry["directory"], entry["file"]))
        if file_re and not file_re.search(path):
            continue
        output = os.path.join(entry["directory"], entry["output"])
        objects.add(os.path.relpath(output, build_dir))
    return sorted(objects)


def _ninja_tool(build_dir: str, *args: str) -> str:
    return subprocess.run(
        ["ninja", "-t", *args],
        cwd=build_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def prerequisite_targets(build_dir: str, objects: list[str]) -> list[str]:
    """Return what ninja must build before it can compile objects.

    These are generated headers and sources and the targets ordered before the
    compilation, so building them lets clang-tidy parse every analyzed file
    without compiling or linking the project itself.
    """
    if not objects:
        return []

    generated = {
        line.rsplit(": ", 1)[0]
        for line in _ninja_tool(build_dir, "targets", "all").splitlines()
    }

    inputs: set[str] = set()
    for i in range(0, len(objects), NINJA_QUERY_CHUNK):
        chunk = objects[i : i + NINJA_QUERY_CHUNK]
        section = None
        for line in _ninja_tool(build_dir, "query", *chunk).splitlines():
            if line.startswith("    "):
                if section == "input":
                    # "|", "||" and "|@" mark implicit, order-only and
                    # validation inputs.
                    inputs.add(re.sub(r"^\|[|@]? ", "", line.strip()))
            elif line.startswith("  "):
                section = line.strip().split(":", 1)[0]
            else:
                section = None
    # Only generated files and phony targets need building.
    return sorted((inputs & generated) - set(objects))


def check_flags(check_name: str) -> list[str]:
    """Return the run-clang-tidy flags the enabled checks need to report anything."""
    flags: list[str] = []
    for check in check_name.split(","):
        check = check.strip()
        if not check.startswith(DIAGNOSTIC_PREFIX):
            continue
        # clang-tidy does not count compiler diagnostics as enabled checks.
        flags.append("-allow-no-checks")
        name = check.removeprefix(DIAGNOSTIC_PREFIX)
        if name in _LEVEL_DIAGNOSTICS:
            # These have no warning option; -Werror would promote warnings.
            continue
        if name.startswith("lifetime-safety"):
            # Enable the known parent group; -checks retains the output filter.
            group = "lifetime-safety-all"
        else:
            group = name.rstrip("*").rstrip("-")
            if not group or "*" in group:
                continue
        flags += [f"-extra-arg=-W{group}", f"-extra-arg=-Wno-error={group}"]
    return list(dict.fromkeys(flags))


def run_clang_tidy(
    clang_tidy_bin: str,
    run_tidy_script: str,
    build_dir: str,
    check_name: str,
    source_dir: str,
    file_regex: str | None,
    log_file: str,
    progress_file: str,
    tidy_config: str | None,
    skip_headers: bool = False,
    profile: bool = False,
) -> bool:
    """Run run-clang-tidy.py and save output to log file.

    Return False if clang-tidy did not start, so no check ran.
    """
    cmd = [
        "python3",
        "-u",
        run_tidy_script,
        "-clang-tidy-binary",
        clang_tidy_bin,
        "-p",
        build_dir,
        f"-checks=-*,{check_name}",
        "-quiet",
        "-allow-enabling-alpha-checkers",
        *check_flags(check_name),
    ]

    jobs = os.environ.get("CTIT_JOBS")
    if jobs:
        cmd.extend(["-j", jobs])

    if skip_headers:
        cmd.append("-header-filter=")

    if profile:
        cmd.append("-enable-check-profile")

    if tidy_config:
        cmd.append(f"-config={tidy_config}")

    full_regex = analyzed_files_regex(source_dir, file_regex)
    if full_regex:
        cmd.append(full_regex)

    with open(log_file, "w") as log, open(progress_file, "a") as progress:
        start = time.monotonic()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        assert proc.stdout is not None
        started = True
        for line in proc.stdout:
            if _PROGRESS_RE.match(line):
                print(line, end="")
                progress.write(line)
            else:
                log.write(line)
                if line.strip() == STARTUP_FAILURE:
                    started = False
        proc.wait()
        elapsed = time.monotonic() - start
        log.write(f"\nCTIT analysis elapsed seconds: {elapsed:.6f}\n")
        print(f"Analysis time: {elapsed:.2f}s")
    return started


def configure_project(
    project: Project,
    config: AnalysisConfig,
    source_dir: str,
    output: IO[str] | None = None,
) -> None:
    """Configure a project and build what clang-tidy needs to parse its files."""
    source_dir = os.path.abspath(source_dir)
    build_dir = os.path.join(source_dir, "build")

    cmake_source = source_dir
    if config.cmake_source_subdir:
        cmake_source = os.path.join(source_dir, config.cmake_source_subdir)

    remove_clang_tidy_configs(source_dir)
    configure_cmake(cmake_source, build_dir, config.cmake_flags, output)
    objects = analyzed_objects(build_dir, source_dir, config.file_regex)
    targets = config.build_targets + prerequisite_targets(build_dir, objects)
    with _build_lock:
        build_project(build_dir, list(dict.fromkeys(targets)), output)


def _configure_logged(
    project: Project, config: AnalysisConfig, source_dir: str
) -> None:
    """Configure a project, then print its whole log at once."""
    start = time.monotonic()
    status = "Failed"
    # Projects are configured in parallel, so collect the output to keep their
    # logs from interleaving.
    with tempfile.TemporaryFile("w+") as output:
        try:
            configure_project(project, config, source_dir, output)
            status = "Done"
        finally:
            output.seek(0)
            elapsed = time.monotonic() - start
            with _print_lock:
                print(f"[{project.name}] Configuring...")
                print(output.read(), end="")
                print(f"[{project.name}] {status} in {elapsed:.1f}s.", flush=True)


def configure(
    work_dir: str = PROJECTS_DIR,
    config_path: str = CONFIG_FILE,
) -> None:
    """Configure all projects and build what their analyzed files need."""
    check_clang_compiler()
    projects = load_projects(config_path)
    configs = get_analysis_configs(config_path)

    # CMake configures a project on a single core, so configure them in parallel.
    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(
                _configure_logged,
                project,
                configs.get(project.name, AnalysisConfig(name=project.name)),
                os.path.join(work_dir, project.name),
            )
            for project in projects
        ]
    # Raise the first failure only after every project has finished.
    for future in futures:
        future.result()


def analyze_project(
    project: Project,
    config: AnalysisConfig,
    source_dir: str,
    clang_tidy_bin: str,
    run_tidy_script: str,
    check_name: str,
    log_dir: str,
    progress_file: str,
    tidy_config: str | None = None,
    skip_headers: bool = False,
    profile: bool = False,
) -> bool:
    """Run clang-tidy analysis on a single project.

    Return False if clang-tidy did not start.
    """
    source_dir = os.path.abspath(source_dir)
    build_dir = os.path.join(source_dir, "build")
    log_file = os.path.join(log_dir, f"{project.name}.log")

    print(f"[{project.name}] Starting analysis for check: {check_name}")

    started = run_clang_tidy(
        clang_tidy_bin,
        run_tidy_script,
        build_dir,
        check_name,
        source_dir,
        config.file_regex,
        log_file,
        progress_file,
        tidy_config,
        skip_headers,
        profile,
    )

    print(f"[{project.name}] Finished. Log saved to {log_file}")
    return started


def analyze(
    check_name: str,
    tidy_config: str | None = None,
    work_dir: str = PROJECTS_DIR,
    clang_tidy_bin: str = DEFAULT_CLANG_TIDY_BIN,
    run_tidy_script: str | None = None,
    log_dir: str = DEFAULT_LOG_DIR,
    config_path: str = CONFIG_FILE,
    skip_headers: bool = False,
    profile: bool = False,
) -> None:
    """Run clang-tidy analysis on all configured projects."""
    if not shutil.which(clang_tidy_bin) and not os.path.isfile(clang_tidy_bin):
        print(
            f"Error: clang-tidy binary not found: {clang_tidy_bin}",
            file=sys.stderr,
        )
        sys.exit(1)

    if run_tidy_script is None:
        run_tidy_script = find_run_tidy_script()
        if run_tidy_script is None:
            print(
                "Error: run-clang-tidy script not found in PATH.\n"
                "Install it or use '--run-tidy-script' flag.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif not os.path.isfile(run_tidy_script) and not shutil.which(run_tidy_script):
        print(
            f"Error: run-clang-tidy script not found: {run_tidy_script}",
            file=sys.stderr,
        )
        sys.exit(1)

    projects = load_projects(config_path)
    configs = get_analysis_configs(config_path)
    os.makedirs(log_dir, exist_ok=True)

    progress_file = os.path.join(log_dir, "progress.log")
    open(progress_file, "w").close()

    static_analyzer = needs_static_analyzer(check_name)
    for project in projects:
        config = configs.get(project.name, AnalysisConfig(name=project.name))
        if static_analyzer and not config.static_analyzer:
            print(f"[{project.name}] Skipped: excluded from static analyzer checks")
            continue
        source_dir = os.path.join(work_dir, project.name)
        started = analyze_project(
            project,
            config,
            source_dir,
            clang_tidy_bin,
            run_tidy_script,
            check_name,
            log_dir,
            progress_file,
            tidy_config,
            skip_headers,
            profile,
        )
        if not started:
            log_file = os.path.join(log_dir, f"{project.name}.log")
            with open(log_file, errors="replace") as log:
                output = log.read().strip()
            print(
                f"Error: clang-tidy did not start, so no check ran:\n{output}",
                file=sys.stderr,
            )
            sys.exit(1)
