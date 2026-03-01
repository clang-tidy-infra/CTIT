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
   - PR_URL: The URL of the clang-tidy PR.
   - CHECK_NAME: The name of the clang-tidy check you want to run (e.g. `bugprone-argument-comment`).
   - OPTIONS (Optional): Key-value pairs for check options. The check name prefix is automatically added.

   Example:
   ```text
   https://github.com/llvm/llvm-project/pull/123456 readability-identifier-naming
   VariableCase: camelBack
   VariablePrefix: v_
   ```

2. Label the issue with `cpp` or `c`.

3. Wait for the CI to run. The service will:
   - Apply the patch from your PR.
   - Build the modified `clang-tidy`.
   - Run the integration tests on supported projects.
   - Post a report comment back to the issue.

## Projects

- [Cppcheck](https://github.com/danmar/cppcheck)
- [LLVM/Clang](https://github.com/llvm/llvm-project)
- [Doxygen](https://github.com/doxygen/doxygen)
- [POCO](https://github.com/pocoproject/poco)
- [Abseil](https://github.com/abseil/abseil-cpp)
- [stdexec](https://github.com/NVIDIA/stdexec)
- [curl](https://github.com/curl/curl)

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

## TODO

- Add `mp-units`, suggested by @zwuis
