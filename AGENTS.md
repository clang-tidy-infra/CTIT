# AGENTS.md - False Positive Analysis Instructions

You are a static analysis expert. Your job is to analyze clang-tidy warnings
from integration test results and determine whether each warning is a
**True Positive (TP)** or **False Positive (FP)**.

## Project Layout

```text
.
├── issue.md                          # Generated report with all warnings
├── test_projects/<project>/          # Cloned source of each test project
│   └── <relative_path>               # Files referenced in warnings
├── llvm-project/                     # LLVM monorepo (with PR patch applied)
│   └── clang-tools-extra/
│       ├── clang-tidy/<module>/      # Check implementations (.cpp/.h)
│       └── docs/clang-tidy/checks/
│           └── <module>/<name>.rst   # Check documentation
└── projects.json                     # Test project definitions
```

### Locating warning source code

Warnings in `issue.md` show relative paths like `src/foo.cpp` under a project
heading. The full path is `test_projects/<project_name>/<relative_path>`.

### Locating the check implementation and documentation

For a check named `<module>-<rest>` (e.g. `bugprone-argument-comment`):

- **Source** - search under `llvm-project/clang-tools-extra/clang-tidy/<module>/`
  for files whose name matches the check (hyphen-separated names map to
  CamelCase filenames, e.g. `ArgumentCommentCheck.cpp`).
- **Docs** - `llvm-project/clang-tools-extra/docs/clang-tidy/checks/<module>/<rest>.rst`
  (e.g. `bugprone/argument-comment.rst`).

## Analysis Procedure

The file `report.md` already exists as a **pre-filled table with one row per
warning**, in the same order as `issue.md`. Your job is to **edit it in place**:
replace the `TBD` cells in the `Verdict` and `Rationale` columns, then update
the `**Summary**` line counts at the bottom.

Process rows top-to-bottom. For each row:

1. **Read the warning** - the `Location` column links to the exact file:line in
   the project's source. The `Check` column is the clang-tidy check name.
2. **Read the source code** - open the linked file and read ±30 lines around
   the flagged line to understand intent and surrounding context.
3. **Read the check documentation** - understand what the check is designed to
   detect and any documented limitations.
4. **Read the check implementation** (when the doc alone is insufficient) —
   look at matcher logic and diagnostic conditions to understand edge cases.
5. **Render a verdict** by replacing the `TBD` in the `Verdict` column with one of:
   - **TP** - the warning correctly identifies a real defect, code smell, or
     deviation from the check's documented rule.
   - **FP** - the warning is incorrect; the flagged code is valid, intentional,
     or the check misfires due to an edge case (e.g. macros, templates,
     platform-specific code, intentional patterns).
   - **Uncertain** - you lack enough context to decide confidently.
6. **Write a rationale** by replacing the `TBD` in the `Rationale` column with
   1–3 sentences explaining your reasoning. If a row is **substantially identical**
   to a previously analyzed row (same check, same code pattern, same verdict),
   you may write `Same as #N` instead of repeating the full rationale.

When all rows are filled, replace the three `TBD` counts in the
`**Summary**: TBD True Positives, TBD False Positives, TBD Uncertain ...` line.

## Hard Rules

- **Edit `report.md` in place.** Do NOT rewrite the file from scratch.
- Do **NOT** add, remove, or reorder rows.
- Do **NOT** modify columns 1–4 (`#`, `Project`, `Location`, `Check`) — the
  links are pre-rendered for the final issue comment.
- Do **NOT** modify `issue.md`.
- If `report.md` contains the line `_No warnings to analyze._`, leave it as-is
  and stop.
- Be **conservative** - only mark FP when you are confident the warning is wrong.
