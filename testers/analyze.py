"""Run clang-tidy analysis on test projects."""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

from testers.config import CONFIG_FILE, PROJECTS_DIR, Project, load_projects

DEFAULT_CLANG_TIDY_BIN = "llvm-project/build/bin/clang-tidy"
DEFAULT_RUN_TIDY_SCRIPT = (
    "llvm-project/clang-tools-extra/clang-tidy/tool/run-clang-tidy.py"
)
DEFAULT_LOG_DIR = "logs"

ANALYSIS_CONFIG_FIELDS = {
    "cmake_source_subdir",
    "cmake_flags",
    "build_targets",
    "file_regex",
}


@dataclass
class AnalysisConfig:
    """Analysis settings for a single project."""

    name: str
    cmake_source_subdir: str | None = None
    cmake_flags: list[str] = field(default_factory=list)
    build_targets: list[str] = field(default_factory=list)
    file_regex: str | None = None


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


def remove_clang_tidy_configs(source_dir: str) -> None:
    """Remove .clang-tidy files to prevent them from overriding check settings."""
    for root, _dirs, files in os.walk(source_dir):
        for name in files:
            if name == ".clang-tidy":
                os.remove(os.path.join(root, name))


def configure_cmake(source_dir: str, build_dir: str, extra_flags: list[str]) -> None:
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
    subprocess.run(cmd, check=True)


def build_project(build_dir: str, targets: list[str]) -> None:
    """Build specific project targets. Does nothing if targets is empty."""
    if not targets:
        return
    subprocess.run(["ninja", "-C", build_dir] + targets, check=True)


def run_clang_tidy(
    clang_tidy_bin: str,
    run_tidy_script: str,
    build_dir: str,
    check_name: str,
    source_dir: str,
    file_regex: str | None,
    log_file: str,
    tidy_config: str | None,
) -> None:
    """Run run-clang-tidy.py and save output to log file."""
    cmd = [
        "python3",
        run_tidy_script,
        "-clang-tidy-binary",
        clang_tidy_bin,
        "-p",
        build_dir,
        f"-checks=-*,{check_name}",
        "-quiet",
    ]

    if tidy_config:
        cmd.append(f"-config={tidy_config}")

    if file_regex:
        full_regex = f"^{re.escape(source_dir)}/{file_regex}"
        cmd.append(full_regex)

    with open(log_file, "w") as log:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
            log.write(line)
        proc.wait()


def configure_project(
    project: Project,
    config: AnalysisConfig,
    source_dir: str,
) -> None:
    """Configure and build a single project."""
    source_dir = os.path.abspath(source_dir)
    build_dir = os.path.join(source_dir, "build")

    cmake_source = source_dir
    if config.cmake_source_subdir:
        cmake_source = os.path.join(source_dir, config.cmake_source_subdir)

    print(f"[{project.name}] Configuring...")
    remove_clang_tidy_configs(source_dir)
    configure_cmake(cmake_source, build_dir, config.cmake_flags)
    build_project(build_dir, config.build_targets)
    print(f"[{project.name}] Done.")


def configure(
    work_dir: str = PROJECTS_DIR,
    config_path: str = CONFIG_FILE,
) -> None:
    """Configure all projects (cmake + build targets)."""
    projects = load_projects(config_path)
    configs = get_analysis_configs(config_path)

    for project in projects:
        config = configs.get(project.name, AnalysisConfig(name=project.name))
        source_dir = os.path.join(work_dir, project.name)
        configure_project(project, config, source_dir)


def analyze_project(
    project: Project,
    config: AnalysisConfig,
    source_dir: str,
    clang_tidy_bin: str,
    run_tidy_script: str,
    check_name: str,
    log_dir: str,
    tidy_config: str | None = None,
) -> None:
    """Run clang-tidy analysis on a single project."""
    source_dir = os.path.abspath(source_dir)
    build_dir = os.path.join(source_dir, "build")
    log_file = os.path.join(log_dir, f"{project.name}.log")

    print(f"[{project.name}] Starting analysis for check: {check_name}")

    run_clang_tidy(
        clang_tidy_bin,
        run_tidy_script,
        build_dir,
        check_name,
        source_dir,
        config.file_regex,
        log_file,
        tidy_config,
    )

    print(f"[{project.name}] Finished. Log saved to {log_file}")


def analyze(
    check_name: str,
    tidy_config: str | None = None,
    work_dir: str = PROJECTS_DIR,
    clang_tidy_bin: str = DEFAULT_CLANG_TIDY_BIN,
    run_tidy_script: str = DEFAULT_RUN_TIDY_SCRIPT,
    log_dir: str = DEFAULT_LOG_DIR,
    config_path: str = CONFIG_FILE,
) -> None:
    """Run clang-tidy analysis on all configured projects."""
    if not os.path.isfile(clang_tidy_bin):
        print(
            f"Error: clang-tidy binary not found at {clang_tidy_bin}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.path.isfile(run_tidy_script):
        print(
            f"Error: run-clang-tidy.py not found at {run_tidy_script}",
            file=sys.stderr,
        )
        sys.exit(1)

    projects = load_projects(config_path)
    configs = get_analysis_configs(config_path)
    os.makedirs(log_dir, exist_ok=True)

    for project in projects:
        config = configs.get(project.name, AnalysisConfig(name=project.name))
        source_dir = os.path.join(work_dir, project.name)
        analyze_project(
            project,
            config,
            source_dir,
            clang_tidy_bin,
            run_tidy_script,
            check_name,
            log_dir,
            tidy_config,
        )
