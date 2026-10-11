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
├── llvm-project/                     # LLVM monorepo (with the PR patch applied, if any)
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

For `clang-diagnostic-lifetime-safety-*`, the warning comes from the **Clang
compiler's LifetimeSafety analysis**, not a clang-tidy check. Use these paths
instead (all relative to `llvm-project/`):

- **Docs** - `clang/docs/LifetimeSafety.md`; annotation semantics are documented
  in `clang/include/clang/Basic/AttrDocs.td`.
- **Diagnostic text and groups** - `clang/include/clang/Basic/DiagnosticSemaKinds.td`
  and `clang/include/clang/Basic/DiagnosticGroups.td`.
- **Implementation** - `clang/lib/Analysis/LifetimeSafety/` (especially
  `Checker.cpp`, `FactsGenerator.cpp`, and `LifetimeAnnotations.cpp`) and
  `clang/lib/Sema/SemaLifetimeSafety.h`.
- **Regression examples** - `clang/test/Sema/LifetimeSafety/`. CTIT excludes test
  files when applying PR patches, so these tests may not include the PR's changes.

Use the checked-out implementation and diagnostic text to resolve gaps in the
documentation. Do not assume upstream's latest behavior matches the tested revision.

## Analysis Procedure

The file `report.md` already exists as a **pre-filled table with one row per
warning**, in the same order as `issue.md`. Your job is to **edit it in place**:
replace the `TBD` cells in the `Verdict` and `Rationale` columns, then update
the `**Summary**` line counts at the bottom.

If `issue.md` includes baseline results, analyze only the PR diagnostics listed
in `report.md`. Baseline diagnostics are reference data and do not require
separate verdicts. A warning also appearing in the baseline is not necessarily
a true positive.

Process rows top-to-bottom. For each row:

1. **Read the warning** - the `Location` column links to the exact file:line in
   the project's source.
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

## LifetimeSafety Verdicts

CTIT enables `-Wlifetime-safety-all`, which includes safety warnings, annotation
suggestions, and annotation validations. **A TP does not always mean a memory
safety bug.** Identify the diagnostic's category before judging it:

- **Safety warnings** (`use-after-scope`, `use-after-free`, `return-stack-addr`,
  `dangling-field`, `dangling-global`, `invalidation`, and their variants): trace
  the owning storage, the pointer/reference/view borrowing it, and the relevant
  destruction, escape, invalidation, or later use. A real dangling return or
  escape can be TP without a demonstrated dereference; apply the specific
  diagnostic's rule, not a universal requirement for a use-after-free crash.
- **Annotation suggestions** (`*-suggestions`, including constructor suggestions):
  judge whether the returned value or constructed object actually borrows from
  the indicated parameter or implicit `this`. A correct missing lifetime contract
  is TP even when all observed callers are safe. A by-value copy that owns its
  storage is not itself a borrow. Check the suggested contract, not merely the
  presence or absence of `[[clang::lifetimebound]]`.
- **Annotation validations**: check `noescape` against actual escape behavior;
  check misplaced/inapplicable `lifetimebound` against declaration visibility
  and type semantics. For `lifetimebound-violation`, inability of the analysis
  to verify a contract is not proof that the contract is wrong. Inspect the
  implementation; use Uncertain when you cannot establish correctness or a violation.

Read the diagnostic's **notes** in `issue.md` together as evidence of the reported
path, not as independent warnings. Follow referenced declarations, constructors,
destructors, callees, macro expansions, and template instantiations beyond the
initial source window when needed. Consult `logs/<project>.log` for context or
fix-it details omitted from the Markdown. Judge the warning and the fix-it
separately: an incorrect insertion location need not make the warning itself FP;
mention that distinction in the rationale.

Do not classify `*-moved`, lambda-capture, or invalidation warnings as FP solely
because the analysis documents limitations. Check whether ownership transfer
really preserves the borrowed storage, whether a callback resets the field in
time, and the actual container/operation's invalidation rules. `std::move` alone
does not prove that an alias remains valid. Intentional borrowing alone is also
not evidence of safety. If the necessary ownership or control-flow evidence is
unavailable, use Uncertain rather than assume safety or a bug.

In the rationale, name the lifetime relationship or annotation contract and the
source evidence that establishes or contradicts it. Baseline presence and warning
count changes do not establish TP/FP. Reuse `Same as #N` only when the relevant
ownership/annotation evidence is also equivalent, not just the diagnostic name.

## Hard Rules

- **Edit `report.md` in place.** Do NOT rewrite the file from scratch.
- Do **NOT** add, remove, or reorder rows.
- Do **NOT** modify columns 1–2 (`#`, `Project`) or column 5 (`Location`) — the
  links are pre-rendered for the final issue comment.
- Do **NOT** modify `issue.md`.
- If `report.md` contains the line `_No warnings to analyze._`, leave it as-is
  and stop.
- Be **conservative** - only mark FP when you are confident the warning is wrong.
