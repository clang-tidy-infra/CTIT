# CTIT as a Public Service

**CTIT** (Clang Tidy Integration Tester) runs your clang-tidy check changes against real open-source C/C++ projects. You can use it in two ways:

- **GitHub service**: Open an issue with a PR URL and check name; the service builds your patch, runs the check on supported projects, and posts the results back to the issue.
- **Python package**: Install the `ctit` package and use the `ctit` CLI locally to clone projects, configure builds, run analysis, and generate reports.

This service is inspired by [Yingwei Zheng (dtcxzyw)'s llvm-fuzz-service](https://github.com/dtcxzyw/llvm-fuzz-service), which provides an automatic workflow for automatic fuzzing of LLVM.

## How to use

1. Open a new issue with the following body format:
   ```text
   [PR_URL] [CHECK_NAME]
   [OPTION_1]: [VALUE_1]
   [OPTION_2]: [VALUE_2]
   ```
   - PR_URL: The URL of the clang-tidy PR. Omit it to run an existing check without path.
   - CHECK_NAME: The name of the clang-tidy check you want to run (e.g. `bugprone-argument-comment`).
   - OPTIONS (Optional): Key-value pairs for check options. The check name prefix is automatically added.

   Example:
   ```text
   https://github.com/llvm/llvm-project/pull/123456 readability-identifier-naming
   VariableCase: camelBack
   VariablePrefix: v_
   ```

   To run a check that already exists upstream, drop the PR URL:

   ```text
   readability-identifier-naming
   VariableCase: camelBack
   ```

2. Label the issue with `cpp` or `c`.

3. Wait for the CI to run. The service will:
   - Apply the patch from your PR, when one was given.
   - Build `clang-tidy`.
   - Run the integration tests on supported projects.
   - Post a report comment back to the issue.

## Nightly new-check watcher

The `Nightly New Check PRs` workflow runs every night and looks at
`llvm/llvm-project` pull requests that saw activity in the last 24 hours. For
every pull request that adds a brand-new clang-tidy check it either:

- opens a `[Test] <check-name>` issue and labels it `cpp` or `c`, which starts
  an integration run, or
- comments `/redo` on the issue that already tracks that pull request and check.

An issue that carries neither `cpp` nor `c` is left untouched, so removing the
label is how you stop a pull request from being re-tested every night.

## Projects

- [Cppcheck](https://github.com/danmar/cppcheck)
- [LLVM/Clang](https://github.com/llvm/llvm-project)
- [Doxygen](https://github.com/doxygen/doxygen)
- [POCO](https://github.com/pocoproject/poco)
- [Abseil](https://github.com/abseil/abseil-cpp)
- [stdexec](https://github.com/NVIDIA/stdexec)
- [curl](https://github.com/curl/curl)
- [zstd](https://github.com/facebook/zstd)
- [libuv](https://github.com/libuv/libuv)
- [libgit2](https://github.com/libgit2/libgit2)
- [Catch2](https://github.com/catchorg/Catch2)
- [yaml-cpp](https://github.com/jbeder/yaml-cpp)
- [Assimp](https://github.com/assimp/assimp)

## Local development

To install development dependencies run:

```bash
make activate
```

### Shell autocomplete

To enable tab completion for the `ctit` command:

**Bash:**

```bash
echo 'eval "$(register-python-argcomplete ctit)"' >> ~/.bashrc
source ~/.bashrc
```

**Zsh:**

```bash
echo 'eval "$(register-python-argcomplete ctit)"' >> ~/.zshrc
source ~/.zshrc
```

**Fish:**

```bash
register-python-argcomplete --shell fish ctit > ~/.config/fish/completions/ctit.fish
```

### Running clang test inputs

After building `clang-tidy`, you can smoke-test a check against LLVM's own clang
test inputs:

```bash
./ctit.py clang-tests \
  --check-name bugprone-argument-comment \
  --clang-tidy-binary llvm-project/build/bin/clang-tidy \
  --llvm-dir llvm-project
```

The command writes `clang-tests.md` with crash-only results and per-file logs
under `logs/clang-tests/`.

## TODO

- Add `mp-units`, suggested by @zwuis
