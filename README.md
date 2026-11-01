# CTIT: Clang-Tidy Integration Tester

CTIT runs a clang-tidy check against a corpus of real open-source C and C++
projects and reports every diagnostic it produces. Use it to find false
positives, crashes, and slowdowns in a check before it lands in LLVM.

To use the GitHub service, open an issue in this repository with an
`llvm/llvm-project` pull request URL and a check name. CTIT applies the patch,
builds clang-tidy, runs the check on every test project, and posts the results
as a comment on the issue. You can also install the `ctit` Python package and
run the same clone, build, analyze, and report steps on your own machine.

- [Test a check from an LLVM pull request](#test-a-check-from-an-llvm-pull-request)
- [Run CTIT locally](docs/local-usage.md)
- [Test projects](docs/test-projects.md)
- [Contributing to CTIT](CONTRIBUTING.md)

## Test a check from an LLVM pull request

### Who can start a run

Runs start only for users with commit access to `llvm/llvm-project`. If you do
not have commit access, open the issue anyway and ask a clang-tidy maintainer
or reviewer to comment `/redo` on it. Their comment starts the run.

### Steps

1. [Open a new issue](https://github.com/clang-tidy-infra/CTIT/issues/new/choose) using the **Integration test**
   template.
2. Replace the issue body with your request (see the format below).
3. Make sure the issue has the `test-cpp` or `test-c` label, since the label
   starts the run. The template adds `test-cpp` for you.
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
| `/baseline`          | No       | Also run the check on unpatched LLVM `main` and list the diagnostics the PR adds or removes. Only works with a `PR_URL`.                            |

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
3. Configures every [test project](docs/test-projects.md) with CMake and runs the
   check on it with `run-clang-tidy`.
4. Posts a report listing every diagnostic per project, with links to the
   exact source lines.
5. Asks an AI agent to label each diagnostic as a true positive, a false
   positive, or uncertain, and attaches its analysis to the report in a
   collapsed section. The labels can be wrong, so check the diagnostics
   yourself before relying on them.

Full logs, `issue.md`, and `report.md` are uploaded as the `ctit-logs` workflow
artifact.

### Rerun or stop a run

- To run again, for example after pushing new commits to the pull request,
  comment `/redo` on the issue.
- To stop the nightly watcher from re-testing a pull request, remove the
  `test-cpp` and `test-c` labels from its issue.

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

## Acknowledgements

1. CTIT is inspired by [Yingwei Zheng (dtcxzyw)'s
   llvm-fuzz-service](https://github.com/dtcxzyw/llvm-fuzz-service), which
   automates fuzzing of LLVM.
2. Thanks to [Yanzuo Liu (zwuis)](https://github.com/zwuis) for suggesting
   test ideas.
3. Thanks to [Victor Baranov (vbvictor)](https://github.com/vbvictor) for
   providing the x86 runner.
4. Thanks to [SOLE Lab](https://solelab.tech/) for providing the ARM runner.
