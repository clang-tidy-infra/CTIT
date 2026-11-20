# Bugfix batch track

Testing every clang-tidy bugfix on its own would cost a full LLVM build and a
full analysis per pull request. The **Bugfix Batch Analysis** workflow instead
tests all open bugfixes in one run: one LLVM build, one analysis pass on
unpatched LLVM, and one on LLVM with all the patches applied. Each check then
gets its own issue and its own report.

For now the workflow only runs by hand, see [Manual runs](#manual-runs). Its
schedule, four times a day, is commented out in `bugfix-batch.yaml`.

The track is separate from the [new-check track](../README.md): it has its own
workflow, label, and Python package, and neither can start the other.

## What a run does

| Job       | Runs on      | What it does                                                                            |
|-----------|--------------|-----------------------------------------------------------------------------------------|
| `select`  | GitHub-hosted | Picks the pull requests, downloads their patches, and checks that they apply.          |
| `analyze` | `ARM64`      | Builds clang-tidy, analyzes the unpatched and the patched LLVM, and uploads the logs.   |
| `publish` | GitHub-hosted | Splits the logs by check and posts one report per check.                               |

Reports have the same format as a `/baseline` run, with the changes against
unpatched LLVM at the top. A report is posted to the `[Bugfix] CHECK_NAME` issue
of its pull request and check, which is opened on first use.

## Which pull requests join a batch

A batch only works if its patches cannot disturb each other, so a pull request
joins only if all of these hold:

- It is open, targets `main`, and is not a draft.
- It saw activity in the last 24 hours.
- It does not add a check. The new-check track tests those.
- Apart from tests and documentation, it modifies only the `*Check.cpp` and
  `*Check.h` files of registered checks. Changes to `utils/`, to module or build
  files, or outside of clang-tidy would affect other checks in the batch.
- Its LLVM CI passed: `Build and Test Linux` succeeded and no other
  `Build and Test` suite failed. Other checks, such as `code_formatter`, do not
  count. Pull requests whose CI waits for approval do not join until it has run.
- Its head revision has not been tested yet.
- It shares no check and no file with a pull request already in the batch.
- Its patch applies to the pinned LLVM revision.
- The batch has room. Ten pull requests fit by default.

The `select` job summary lists every candidate and why it was left out. Pull
requests that were left out are considered again by the next batch.

## When a patch does not compile

`analyze` applies the patches one at a time and builds incrementally after each,
so a failure points at one pull request. That patch is reverted and the batch
goes on without it. The `publish` job summary lists it and the next batch retries
it.

## Reading the results

- A crash loses every diagnostic of the translation unit, including those of the
  other checks in the batch. Reports warn about this and name the projects, since
  differences there may have nothing to do with the pull request.
- Only the default options of each check are tested.
- `/redo` does nothing on these issues. A new push to the pull request starts a
  new test in the next batch.
- To stop testing a pull request, remove the `test-bugfix` label from its issue.

## Isolation from the new-check track

- Issues carry the `test-bugfix` label, which `check-tester.yaml` ignores.
- `publish` writes with `github.token`, and events made with that token start no
  workflow. The workflow must not use a personal token such as
  `NIGHTLY_TRIGGER_TOKEN`.
- `bugfix_batch` imports the existing modules, and nothing imports it back.
- An issue opened by hand for the same pull request and check is left alone.
- `analyze` runs code from pull requests, so it holds no secrets and no write
  permissions, and it restores the shared test-projects cache without saving it.

`tests/test_bugfix_isolation.py` enforces these rules.

The two tracks do share the single `ARM64` runner: a run of `check-tester.yaml`
waits for a batch in progress. The commented-out schedule leaves room before the
new-check watcher starts at 1:00 and 13:00 UTC.

## Manual runs

Start the workflow from **Actions** > **Bugfix Batch Analysis** > **Run workflow**:

| Input            | Description                                                                            |
|------------------|----------------------------------------------------------------------------------------|
| `since_hours`    | Activity window in hours.                                                              |
| `limit`          | Maximum pull requests in the batch.                                                    |
| `include_drafts` | Also consider draft pull requests.                                                     |
| `dry_run`        | Run the batch without creating issues or comments. Reports go to the workflow artifact. |

To preview a batch without running it:

```bash
GITHUB_TOKEN=$(gh auth token) python3 -m bugfix_batch.select_batch \
  --repo clang-tidy-infra/CTIT
```

This only reads from GitHub. It needs an initialized `llvm-project` submodule.
