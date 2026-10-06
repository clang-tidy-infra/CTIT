# CTIT: Clang-Tidy Integration Tester

CTIT runs a clang-tidy check against a corpus of real open-source C and C++
projects and reports every diagnostic it produces. Use it to find false
positives, crashes, and slowdowns in a check before it lands in LLVM.

There are two ways to use it:

- **As a GitHub service.** Open an issue in this repository with an
  `llvm/llvm-project` pull request URL and a check name. CTIT applies the patch,
  builds clang-tidy, runs the check on every test project, and posts the
  results as a comment on the issue.
- **As a local CLI.** Install the `ctit` Python package and run the same
  clone, build, analyze, and report steps on your own machine.

- [Test a check from an LLVM pull request](#test-a-check-from-an-llvm-pull-request)
- [Run CTIT locally](#run-ctit-locally)
- [Test projects](#test-projects)
- [Scheduled automation](#scheduled-automation)
- [Developing CTIT](#developing-ctit)

## Test a check from an LLVM pull request

### Who can start a run

Runs start only for users with commit access to `llvm/llvm-project`. If you do
not have commit access, open the issue anyway and ask a clang-tidy maintainer
or reviewer to comment `/redo` on it. Their comment starts the run.

### Steps

1. [Open a new issue](https://github.com/clang-tidy-infra/CTIT/issues/new/choose) using the **Integration test**
   template.
2. Replace the issue body with your request (see the format below).
3. Make sure the issue has the `cpp` or `c` label. The template adds `cpp`
   automatically. Adding the label is what starts the run.
4. Wait for the results. CTIT posts a "Run started" comment with a link to the
   workflow run, and replaces it with the report when the run finishes.

### Issue body format

```text
[PR_URL] CHECK_NAME
[OPTION_NAME: VALUE]
[OPTION_NAME: VALUE]
[/baseline]
```

| Part                 | Required | Description                                                                                                                                         |
|----------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `PR_URL`             | No       | URL of the `llvm/llvm-project` pull request to test. Omit it to test a check that already exists on LLVM `main`.                                    |
| `CHECK_NAME`         | Yes      | The clang-tidy check to run, for example `bugprone-argument-comment`. Glob patterns such as `bugprone-*` also work.                                 |
| `OPTION_NAME: VALUE` | No       | Check options, one per line. CTIT adds the `CHECK_NAME.` prefix for you, so write `VariableCase`, not `readability-identifier-naming.VariableCase`. |
| `/baseline`          | No       | Also run the check on unpatched LLVM `main` and show both results side by side. Only takes effect when a `PR_URL` is given.                         |

### Examples

Test a check from a pull request:

```text
https://github.com/llvm/llvm-project/pull/123456 bugprone-argument-comment
```

Test a pull request with check options:

```text
https://github.com/llvm/llvm-project/pull/123456 readability-identifier-naming
VariableCase: camelBack
VariablePrefix: v_
```

Compare a pull request against the current behavior of the check on `main`:

```text
https://github.com/llvm/llvm-project/pull/123456 readability-identifier-naming
/baseline
```

Test a check that already exists upstream, with no patch:

```text
readability-identifier-naming
VariableCase: camelBack
```

### What a run does

1. Downloads the pull request diff and applies it to the pinned LLVM checkout.
   Test files and documentation (`*/test/*`, `*.rst`, `*.md`) are excluded
   from the patch.
2. Builds `clang-tidy` with assertions enabled.
3. Configures every [test project](#test-projects) with CMake and runs the
   check on it with `run-clang-tidy`.
4. Posts a report listing every diagnostic per project, with links to the
   exact source lines.
5. Asks an AI agent to label each diagnostic as a true positive, a false
   positive, or uncertain. This analysis is attached to the report in a
   collapsed section. Treat it as a starting point, not a verdict.

Full logs, `issue.md`, and `report.md` are uploaded as the `ctit-logs` workflow
artifact.

### Rerun or stop a run

- To run again, for example after pushing new commits to the pull request,
  comment `/redo` on the issue.
- To stop the nightly watcher from re-testing a pull request, remove the `cpp`
  and `c` labels from its issue (see
  [Scheduled automation](#scheduled-automation)).

### Manual runs from the Actions tab

Maintainers can start the **Integration Testing** workflow directly from
**Actions** > **Integration Testing** > **Run workflow**. Manual runs do not
post to an issue; the results are only in the workflow artifact. They accept
these inputs:

| Input              | Description                                              |
|--------------------|----------------------------------------------------------|
| `pr_link`          | Pull request URL. Leave empty to test unpatched LLVM.    |
| `check_name`       | The check to run.                                        |
| `extra_config`     | One check option, for example `VariableCase: camelBack`. |
| `compare_baseline` | Also run unpatched LLVM, like `/baseline`.               |
| `skip_ai_analysis` | Skip the AI false-positive analysis step.                |

## Run CTIT locally

### Requirements

- Linux
- Python 3.10 or newer
- Git, CMake, and Ninja
- Clang as the C and C++ compiler.
- A `clang-tidy` binary and the `run-clang-tidy` script. You can use a
  packaged clang-tidy, or [build a patched one](#test-a-patched-clang-tidy).

Alternatively, build the CI runner image, which has all of these installed:

```bash
make build-container    # builds the ctit-runner image
```

### Install

```bash
git clone https://github.com/clang-tidy-infra/CTIT.git
cd CTIT
pip install -e .
```

### Basic workflow

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

### Test a patched clang-tidy

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

### Command reference

Run `ctit <command> --help` for the full list of options.

| Command                | What it does                                                                                                                     | Useful options                                                                                                                                                   |
|------------------------|----------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ctit clone`           | Clones the test projects at their pinned commits.                                                                                | `--work-dir` (default `test_projects`), `--config` (default: the bundled `projects.json`)                                                                        |
| `ctit configure`       | Runs CMake for each project, builds required targets, and removes project `.clang-tidy` files so they cannot override the check. | `--work-dir`, `--config`                                                                                                                                         |
| `ctit analyze`         | Runs the check on every project with `run-clang-tidy`.                                                                           | `--check-name` (required), `--clang-tidy-binary`, `--run-tidy-script`, `--tidy-config`, `--log-dir` (default `logs`), `--skip-headers`, `--enable-check-profile` |
| `ctit report`          | Writes a Markdown report of all diagnostics.                                                                                     | `--log-dir`, `--output` (default `issue.md`), `--baseline-log-dir`, `--baseline-revision`                                                                        |
| `ctit report-template` | Writes `report.md`, the table the AI agent fills in with true or false positive verdicts. See [AGENTS.md](AGENTS.md).            | `--log-dir`, `--output`                                                                                                                                          |

Set `CTIT_JOBS` to limit how many clang-tidy processes `analyze` runs in
parallel.

### Shell completion

```bash
# Bash
echo 'eval "$(register-python-argcomplete ctit)"' >> ~/.bashrc

# Zsh
echo 'eval "$(register-python-argcomplete ctit)"' >> ~/.zshrc

# Fish
register-python-argcomplete --shell fish ctit > ~/.config/fish/completions/ctit.fish
```

## Test projects

| Project    | Repository                                                |
|------------|-----------------------------------------------------------|
| Cppcheck   | [danmar/cppcheck](https://github.com/danmar/cppcheck)     |
| LLVM/Clang | [llvm/llvm-project](https://github.com/llvm/llvm-project) |
| Doxygen    | [doxygen/doxygen](https://github.com/doxygen/doxygen)     |
| POCO       | [pocoproject/poco](https://github.com/pocoproject/poco)   |
| Abseil     | [abseil/abseil-cpp](https://github.com/abseil/abseil-cpp) |
| curl       | [curl/curl](https://github.com/curl/curl)                 |
| stdexec    | [NVIDIA/stdexec](https://github.com/NVIDIA/stdexec)       |
| zstd       | [facebook/zstd](https://github.com/facebook/zstd)         |
| libuv      | [libuv/libuv](https://github.com/libuv/libuv)             |
| libgit2    | [libgit2/libgit2](https://github.com/libgit2/libgit2)     |
| Catch2     | [catchorg/Catch2](https://github.com/catchorg/Catch2)     |
| yaml-cpp   | [jbeder/yaml-cpp](https://github.com/jbeder/yaml-cpp)     |
| Assimp     | [assimp/assimp](https://github.com/assimp/assimp)         |

### Add a project

Projects are defined in [`testers/projects.json`](testers/projects.json). Each
entry looks like this:

```json
"my-project": {
  "url": "https://github.com/example/my-project.git",
  "commit": "<full commit SHA>",
  "cmake_flags": ["-DBUILD_TESTING=OFF", "-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON"],
  "build_targets": ["generated_headers"],
  "cmake_source_subdir": "build/cmake",
  "file_regex": "(?!third_party/).*"
}
```

| Field                 | Required | Description                                                                                                                         |
|-----------------------|----------|-------------------------------------------------------------------------------------------------------------------------------------|
| `url`                 | Yes      | Git URL to clone.                                                                                                                   |
| `commit`              | Yes      | Commit to pin. Pinning keeps results comparable between runs.                                                                       |
| `cmake_flags`         | No       | Extra CMake flags. Existing projects pass `-DCMAKE_DISABLE_PRECOMPILE_HEADERS=ON` and turn off tests and examples they do not need. |
| `build_targets`       | No       | Ninja targets to build before analysis, for projects that generate headers or sources.                                              |
| `cmake_source_subdir` | No       | Subdirectory containing the top-level `CMakeLists.txt`.                                                                             |
| `file_regex`          | No       | Regular expression, relative to the project root, selecting which files to analyze. Use it to skip vendored or generated code.      |

## Developing CTIT

```bash
make activate          # create venv/ and install CTIT with dev dependencies
make test              # run the unit tests
make lint              # run black, ruff, mypy, yamllint, shellcheck, zizmor, and more
make format            # format Python code with black
make build-container   # build the runner image locally
make test-container    # build the runner image and run its smoke tests
```

## Acknowledgements

1. CTIT is inspired by [Yingwei Zheng (dtcxzyw)'s
   llvm-fuzz-service](https://github.com/dtcxzyw/llvm-fuzz-service), which
   automates fuzzing of LLVM.
2. Thanks to [Yanzuo Liu (zwuis)](https://github.com/zwuis) for suggesting
   test ideas.
3. Thanks to [Victor Baranov (vbvictor)](https://github.com/vbvictor) for
   providing the x86 runner.
4. Thanks to [SOLE Lab](https://solelab.tech/) for providing the ARM runner.
