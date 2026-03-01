# CTIT as a Public Service

> If you don't know what it is, you probably don't want it...

**CTIT: Clang Tidy Integration Tester**

Based on the admirable work of Yingwei Zheng (dtcxzyw) who kindly shared [their framework for automatic fuzzing](https://github.com/dtcxzyw/llvm-fuzz-service).

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

## TODO

- Add `mp-units`, suggested by @zwuis

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
