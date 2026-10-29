# Run CTIT locally

The `ctit` command-line tool runs the same steps as the GitHub service on your
own machine. To test a check through the service instead, see the
[README](../README.md#test-a-check-from-an-llvm-pull-request).

## Requirements

- Linux
- Python 3.10 or newer
- Git, CMake, and Ninja
- Clang as the C and C++ compiler
- A `clang-tidy` binary and the `run-clang-tidy` script. You can use a
  packaged clang-tidy, or [build a patched one](#test-a-patched-clang-tidy).

Alternatively, build the CI runner image, which has all of these installed:

```bash
make build-container    # builds the ctit-runner image
```

## Install

```bash
git clone https://github.com/clang-tidy-infra/CTIT.git
cd CTIT
pip install -e .
```

## Basic workflow

Run these commands from the repository root. Each step writes its output to the
current directory.

```bash
# 1. Clone every test project at its pinned commit into test_projects/
ctit clone

# 2. Run CMake for each project and build any generated sources it needs
CC=clang CXX=clang++ ctit configure

# 3. Run one check on every project; logs go to logs/<project>.log
ctit analyze --check-name bugprone-argument-comment

# 4. Turn the logs into a Markdown report (issue.md)
ctit report
```

`clone` and `configure` only need to run once. After that, you can run
`analyze` and `report` repeatedly for different checks.

Pass check options as a clang-tidy configuration string:

```bash
ctit analyze --check-name readability-identifier-naming \
  --tidy-config '{"CheckOptions": {"readability-identifier-naming.VariableCase": "camelBack"}}'
```

## Test a patched clang-tidy

The `llvm-project` submodule is the LLVM revision CTIT tests against. To test a
pull request locally, apply its diff to the submodule and build clang-tidy with
`build.sh`:

```bash
git submodule update --init llvm-project
curl -L https://github.com/llvm/llvm-project/pull/123456.diff \
  | git -C llvm-project apply --exclude='*/test/*' --exclude='*.rst' --exclude='*.md'
bash build.sh    # builds llvm-project/build/bin/clang-tidy

ctit analyze --check-name bugprone-argument-comment \
  --clang-tidy-binary llvm-project/build/bin/clang-tidy \
  --run-tidy-script llvm-project/clang-tools-extra/clang-tidy/tool/run-clang-tidy.py
ctit report
```

`build.sh` reads these optional environment variables: `CTIT_JOBS` (Ninja job
count), `LLVM_USE_LINKER` (for example `lld` or `mold`), and
`LLVM_TARGETS_TO_BUILD` (default `Native`). It uses `sccache` automatically
when it is installed.

To compare against unpatched LLVM, analyze with an unpatched clang-tidy first,
then pass both log directories to `report`:

```bash
ctit analyze --check-name my-check --clang-tidy-binary /path/to/unpatched/clang-tidy \
  --log-dir logs/baseline
ctit analyze --check-name my-check --clang-tidy-binary llvm-project/build/bin/clang-tidy
ctit report --baseline-log-dir logs/baseline
```

## Command reference

Run `ctit <command> --help` for the full list of options.

| Command                | What it does                                                                                                                     | Useful options                                                                                                                                                   |
|------------------------|----------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ctit clone`           | Clones the test projects at their pinned commits.                                                                                | `--work-dir` (default `test_projects`), `--config` (default: the bundled `projects.json`)                                                                        |
| `ctit configure`       | Runs CMake for each project, builds required targets, and removes project `.clang-tidy` files so they cannot override the check. | `--work-dir`, `--config`                                                                                                                                         |
| `ctit analyze`         | Runs the check on every project with `run-clang-tidy`.                                                                           | `--check-name` (required), `--clang-tidy-binary`, `--run-tidy-script`, `--tidy-config`, `--log-dir` (default `logs`), `--skip-headers`, `--enable-check-profile` |
| `ctit report`          | Writes a Markdown report of all diagnostics.                                                                                     | `--log-dir`, `--output` (default `issue.md`), `--baseline-log-dir`, `--baseline-revision`                                                                        |
| `ctit report-template` | Writes `report.md`, the table the AI agent fills in with true or false positive verdicts. See [AGENTS.md](../AGENTS.md).         | `--log-dir`, `--output`                                                                                                                                          |

Set `CTIT_JOBS` to limit how many clang-tidy processes `analyze` runs in
parallel.

## Shell completion

```bash
# Bash
echo 'eval "$(register-python-argcomplete ctit)"' >> ~/.bashrc

# Zsh
echo 'eval "$(register-python-argcomplete ctit)"' >> ~/.zshrc

# Fish
register-python-argcomplete --shell fish ctit > ~/.config/fish/completions/ctit.fish
```
